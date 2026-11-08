#!/usr/bin/env python3
"""Dry-runs an Everlake world import slice by the fork's updater rules, twice, and checks it (docs/forever-import.md,
"How a run works").

    import_dryrun.py                     dry-run slice1 from world-data/ (import_slice1.py's output)
    import_dryrun.py --slice slice1 --data DIR
    import_dryrun.py --skip-scratch      only the stepped run (quick; the report says the scratch run was skipped)
    import_dryrun.py --drop              remove the dry-run tables afterwards

Both runs build a world in the scratch schema acore_world_dryrun, as tables with their own prefix, so nothing else in
that schema is touched (only tables named elscratch_* and elstep_* are created or dropped):
- from scratch (elscratch_*): the fork's world release, then the fork's sql/updates and sql/custom world files and the
  slice's files in file-name order, as a new realm builds it (custom_sql.UpdatePlan, the same code load_tc.py runs);
- stepped (elstep_*): the deployed state, then the new files, as the realm will. Today the deployed state is the fork
  world with no import files: acore_forever.tc_* with its updates list (load_tc.py's world). Every fork file must
  then be skipped by the updater, or the deployed state isn't what tc_* says.

Checks:
- the two runs end with the same world (every table's rows; the updates list by name and hash);
- every fork row outside the corrections is unchanged: per table, the rows added are exactly the keys in
  everlake_import_rows, the rows removed or changed exactly those the corrections name;
- no recorded key was a fork row (no key collides), and every recorded key's row is there;
- every new row points at things that exist: givers and enders are creature or gameobject templates, quests exist,
  objectives' targets exist;
- running the slice's files again changes nothing (run directly, and the updater skips them), and after a simulated
  fork change (a quest's givers taken over, a corrected row re-sniffed, a removed giver put back) a re-run leaves the
  fork's rows alone (this runs last and changes the stepped world);
- the gap report on the stepped world: every item of the slice's categories is closed or on the review or held-back
  list with its reason, and no category gains an item.
Writes <data>/<slice>/dry-run.md and dry-run.json. Exit status 1 when a check fails.
"""
import argparse
import collections
import datetime
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import custom_sql  # noqa: E402
import import_sql as isql  # noqa: E402
import load_tc  # noqa: E402
from load_sources import SOURCES, connect  # noqa: E402

DRYRUN = "acore_world_dryrun"
FORK = "acore_forever"
SCRATCH, STEP = "elscratch_", "elstep_"
SLICE_CATEGORIES = ["quests_no_giver", "quests_giver_differs", "quests_no_ender", "quests_ender_differs", "quests_no_text",
                    "quests_no_objectives", "quests_no_progress_text", "quests_no_completion_text"]
# what each kind of recorded row must point at: (column, table it must be in, that table's key column)
REFERENCES = {
    "creature_queststarter": [("id", "creature_template", "entry"), ("quest", "quest_template", "ID")],
    "creature_questender": [("id", "creature_template", "entry"), ("quest", "quest_template", "ID")],
    "gameobject_queststarter": [("id", "gameobject_template", "entry"), ("quest", "quest_template", "ID")],
    "gameobject_questender": [("id", "gameobject_template", "entry"), ("quest", "quest_template", "ID")],
    "quest_request_items": [("ID", "quest_template", "ID")],
    "quest_offer_reward": [("ID", "quest_template", "ID")],
    "quest_objectives": [("QuestID", "quest_template", "ID")],
}


class Checks:
    def __init__(self):
        self.items = []

    def add(self, name, ok, detail=""):
        self.items.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""), flush=True)

    @property
    def ok(self):
        return all(i["ok"] for i in self.items)


def tables(cur, schema, prefix):
    """Base tables named prefix<name> (not load_tc.py's __new/__old/__tmp leftovers): {name: full name}."""
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE' "
                "AND table_name LIKE %s", (schema, prefix.replace("_", "\\_") + "%"))
    out = {}
    for (t,) in cur.fetchall():
        name = t[len(prefix):]
        if not re.search(r"__(new|old|tmp)$", name):
            out[name] = t
    return out


def drop_prefix(cur, prefix):
    if prefix not in (SCRATCH, STEP):
        raise SystemExit(f"refusing to drop tables named {prefix}*")
    for full in tables(cur, DRYRUN, prefix).values():
        cur.execute(f"DROP TABLE `{DRYRUN}`.`{full}`")
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_name LIKE %s",
                (DRYRUN, prefix.replace("_", "\\_") + "%"))
    for (full,) in cur.fetchall():        # leftovers of a failed run
        cur.execute(f"DROP TABLE `{DRYRUN}`.`{full}`")


def columns(cur, schema, table):
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position", (schema, table))
    return [r[0] for r in cur.fetchall()]


def primary_key(cur, schema, table):
    cur.execute("SELECT column_name FROM information_schema.statistics WHERE table_schema = %s AND table_name = %s "
                "AND index_name = 'PRIMARY' ORDER BY seq_in_index", (schema, table))
    return [r[0] for r in cur.fetchall()]


def row_sql(cols, alias=""):
    a = f"{alias}." if alias else ""
    return "MD5(CONCAT_WS(',', " + ", ".join(f"QUOTE({a}`{c}`)" for c in cols) + "))"


def fingerprint(cur, schema, table, cols):
    """(rows, sum of the first 60 bits of each row's MD5): the same for the same rows in any order."""
    cur.execute(f"SELECT COUNT(*), COALESCE(SUM(CAST(CONV(SUBSTRING({row_sql(cols)}, 1, 15), 16, 10) AS UNSIGNED)), 0) "
                f"FROM `{schema}`.`{table}`")
    n, s = cur.fetchone()
    return int(n), int(s)


def our_files(data):
    folder = os.path.join(data, "sql", "world")
    out = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith(".sql"):
            isql.check_name(name)
            with open(os.path.join(folder, name), "rb") as handle:
                out[name] = handle.read()
    return out


def fork_mapping(cur, prefix, raw_all, skipped):
    """Every world table name -> prefix + name, as load_tc.py maps them (tables the files create included)."""
    have = set(tables(cur, DRYRUN, prefix))
    created = {t: tmp for t, tmp in custom_sql.created_tables(b.decode("utf-8") for b in raw_all.values()).items()
               if not load_tc.SKIP.search(t)}
    mapping = {t: prefix + t for t in have | {t for t, tmp in created.items() if not tmp}}
    mapping.update({t: f"{prefix}{t}__tmp" for t, tmp in created.items() if tmp})
    return mapping, {t for t in skipped if t != "updates_include"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--slice", default="slice1")
    ap.add_argument("--data", default=os.path.join(HERE, "world-data"))
    ap.add_argument("--sources", default=SOURCES)
    ap.add_argument("--skip-scratch", action="store_true")
    ap.add_argument("--drop", action="store_true")
    args = ap.parse_args()
    with open(os.path.join(args.data, args.slice, "manifest.json")) as handle:
        manifest = json.load(handle)
    with open(os.path.join(args.sources, "manifest.json")) as handle:
        current = json.load(handle)["current"]
    release, custom_pin = current["tc-release"], current["tc-forever"]
    ours = our_files(args.data)
    names = {f["name"] for f in manifest["files"]}
    if set(ours) != names:
        raise SystemExit(f"{args.data}/sql/world holds {sorted(ours)}, the manifest names {sorted(names)}")
    fork_raw, fork_paths = load_tc.read_update_files(args.sources, custom_pin)
    clash = set(fork_raw) & set(ours)
    if clash:
        raise SystemExit(f"our files have the fork's names: {sorted(clash)}")
    raw = dict(fork_raw, **ours)
    paths = dict(fork_paths, **{n: f"sql/custom/world/{n}" for n in ours})
    conn = connect(DRYRUN)
    cur = conn.cursor()
    cur.execute("SET SESSION foreign_key_checks = 0, unique_checks = 0")
    checks, timings, runs = Checks(), {}, {}
    print(f"dry run of {args.slice}: {', '.join(sorted(ours))}", flush=True)

    # the deployed state: the fork world (acore_forever.tc_*), copied
    started = time.time()
    drop_prefix(cur, STEP)
    fork_tables = tables(cur, FORK, "tc_")
    for name, full in sorted(fork_tables.items()):
        cur.execute(f"CREATE TABLE `{STEP}{name}` LIKE `{FORK}`.`{full}`")
        cur.execute(f"INSERT INTO `{STEP}{name}` SELECT * FROM `{FORK}`.`{full}`")
        conn.commit()
    cur.execute(f"SELECT name, hash, state FROM `{STEP}updates`")
    held = {r[0]: (r[1] or "", r[2]) for r in cur.fetchall()}
    cur.execute(f"SELECT tables_json FROM `{FORK}`.src_pins WHERE source = 'tc-release'")
    skipped = set(json.loads(cur.fetchone()[0]).get("skipped", []))
    mapping, skipped_tables = fork_mapping(cur, STEP, raw, skipped)
    applied = load_tc.apply_update_files(conn, cur, raw, paths, mapping, skipped_tables, held, load_tc.updates_state(cur, f"{STEP}updates"))
    runs["stepped"] = applied
    timings["stepped"] = round(time.time() - started)
    fork_moved = [a for a in applied if a["file"] not in ours]
    checks.add("stepped run: the updater skips every fork file (the deployed state is the fork world)", not fork_moved,
               "; ".join(f"{a['file']} {a['mode']}" for a in fork_moved[:10]))
    checks.add("stepped run: the updater applies each of our files once",
               sorted(a["file"] for a in applied if a["file"] in ours and a["mode"] == "applied") == sorted(ours),
               json.dumps([a for a in applied if a["file"] in ours]))

    # from scratch: the release, then every file by the updater's rules
    if not args.skip_scratch:
        started = time.time()
        drop_prefix(cur, SCRATCH)
        folder = os.path.join(args.sources, release["folder"])
        archive = next(os.path.join(folder, f) for f in release["files"] if f.endswith(".7z"))
        print("  loading the world release (from scratch) ...", flush=True)
        _, skipped_s = load_tc.load_release(conn, cur, archive, lambda t: f"{SCRATCH}{t}")
        cur.execute(f"SELECT name, hash, state FROM `{SCRATCH}updates`")
        held_s = {r[0]: (r[1] or "", r[2]) for r in cur.fetchall()}
        mapping_s, skipped_tables_s = fork_mapping(cur, SCRATCH, raw, skipped_s)
        print("  applying the fork's files and ours ...", flush=True)
        applied_s = load_tc.apply_update_files(conn, cur, raw, paths, mapping_s, skipped_tables_s, held_s,
                                               load_tc.updates_state(cur, f"{SCRATCH}updates"))
        runs["scratch"] = [a for a in applied_s if a["file"] in ours]
        timings["scratch"] = round(time.time() - started)
        checks.add("from scratch: each of our files applied once, after every fork file",
                   [a["file"] for a in applied_s if a["mode"].startswith("applied")][-len(ours):] == sorted(ours))

        # the two runs end with the same world
        s_tables, t_tables = tables(cur, DRYRUN, SCRATCH), tables(cur, DRYRUN, STEP)
        checks.add("both runs have the same tables", set(s_tables) == set(t_tables),
                   f"only scratch: {sorted(set(s_tables) - set(t_tables))}; only stepped: {sorted(set(t_tables) - set(s_tables))}")
        differ = []
        for name in sorted(set(s_tables) & set(t_tables)):
            cols = columns(cur, DRYRUN, s_tables[name])
            if cols != columns(cur, DRYRUN, t_tables[name]):
                differ.append(f"{name} (columns)")
                continue
            if name == "updates":
                cols = ["name", "hash"]             # when each file ran differs, by design
            if fingerprint(cur, DRYRUN, s_tables[name], cols) != fingerprint(cur, DRYRUN, t_tables[name], cols):
                differ.append(name)
        checks.add("both runs end with the same world", not differ, ", ".join(differ[:20]))

    # every fork row outside the corrections is unchanged
    step_tables = tables(cur, DRYRUN, STEP)
    added_expect = collections.defaultdict(set)
    cur.execute(f"SELECT tbl, k1, k2, k3, k4, file FROM `{STEP}{isql.IMPORT_ROWS}`")
    recorded = cur.fetchall()
    for tbl, k1, k2, k3, k4, _ in recorded:
        added_expect[tbl].add((k1, k2, k3, k4))
    removed_expect, changed_expect = collections.defaultdict(set), collections.defaultdict(set)
    for f in manifest["fixes"]:
        if f["kind"] == "relations":
            for d in f["delete"]:
                removed_expect[d["table"]].add((d["id"], d["quest"], 0, 0))
        else:
            changed_expect[f["table"]].add(tuple(list(f["key"].values()) + [0] * (4 - len(f["key"]))))
    unexpected, per_table = [], {}
    for name, full in sorted(fork_tables.items()):
        cols = columns(cur, FORK, full)
        if name == "updates":
            cols = ["name", "hash"]
        if fingerprint(cur, FORK, full, cols) == fingerprint(cur, DRYRUN, step_tables[name], cols):
            continue
        if name == "updates":
            cur.execute(f"SELECT name FROM `{STEP}updates` s WHERE NOT EXISTS (SELECT 1 FROM `{FORK}`.tc_updates t "
                        f"WHERE t.name = s.name AND t.hash = s.hash)")
            extra = {r[0] for r in cur.fetchall()}
            cur.execute(f"SELECT COUNT(*) FROM `{FORK}`.tc_updates t WHERE NOT EXISTS (SELECT 1 FROM `{STEP}updates` s "
                        f"WHERE t.name = s.name AND t.hash = s.hash)")
            gone = cur.fetchone()[0]
            if extra != set(ours) or gone:
                unexpected.append(f"updates: {sorted(extra)} added, {gone} gone")
            continue
        pk = primary_key(cur, FORK, full)
        if not pk or len(pk) > 4:
            unexpected.append(f"{name} changed (no usable primary key to say how)")
            continue
        on = " AND ".join(f"t.`{k}` = s.`{k}`" for k in pk)
        keys = ", ".join(f"s.`{k}`" for k in pk)
        cur.execute(f"SELECT {keys} FROM `{STEP}{name}` s WHERE NOT EXISTS (SELECT 1 FROM `{FORK}`.`{full}` t WHERE {on})")
        added = {tuple(list(r) + [0] * (4 - len(pk))) for r in cur.fetchall()}
        cur.execute(f"SELECT {keys.replace('s.', 't.')} FROM `{FORK}`.`{full}` t WHERE NOT EXISTS (SELECT 1 FROM `{STEP}{name}` s WHERE {on})")
        removed = {tuple(list(r) + [0] * (4 - len(pk))) for r in cur.fetchall()}
        cur.execute(f"SELECT {keys} FROM `{STEP}{name}` s JOIN `{FORK}`.`{full}` t ON {on} WHERE {row_sql(cols, 's')} <> {row_sql(cols, 't')}")
        changed = {tuple(list(r) + [0] * (4 - len(pk))) for r in cur.fetchall()}
        per_table[name] = {"added": len(added), "removed": len(removed), "changed": len(changed)}
        if added != added_expect.get(name, set()) or removed != removed_expect.get(name, set()) or changed != changed_expect.get(name, set()):
            unexpected.append(f"{name}: added {len(added)} (recorded {len(added_expect.get(name, ()))}), removed {len(removed)} "
                              f"(corrections {len(removed_expect.get(name, ()))}), changed {len(changed)} (corrections {len(changed_expect.get(name, ()))})")
    new_tables = sorted(set(step_tables) - set(fork_tables))
    checks.add("fork rows outside the corrections are unchanged (rows added = rows recorded; removed and changed = the corrections')",
               not unexpected, "; ".join(unexpected))
    checks.add("the only new table is everlake_import_rows", new_tables == [isql.IMPORT_ROWS], str(new_tables))

    # keys: recorded rows are there, none was a fork row
    missing_rows, collisions = [], []
    for tbl, keys in sorted(added_expect.items()):
        pk = primary_key(cur, FORK, fork_tables[tbl])
        for key in keys:
            where = " AND ".join(f"`{k}` = {int(v)}" for k, v in zip(pk, key))
            cur.execute(f"SELECT COUNT(*) FROM `{STEP}{tbl}` WHERE {where}")
            if not cur.fetchone()[0]:
                missing_rows.append(f"{tbl} {key}")
            cur.execute(f"SELECT COUNT(*) FROM `{FORK}`.`{fork_tables[tbl]}` WHERE {where}")
            if cur.fetchone()[0]:
                collisions.append(f"{tbl} {key}")
    checks.add("every recorded key's row is in the world", not missing_rows, ", ".join(missing_rows[:10]))
    checks.add("no key collides with a fork row", not collisions, ", ".join(collisions[:10]))
    files_of = collections.Counter(r[5] for r in recorded)
    checks.add("every recorded row names one of our files", set(files_of) <= set(ours), str(dict(files_of)))

    # references
    broken = []
    for tbl, refs in REFERENCES.items():
        for col, target, tkey in refs:
            pk = primary_key(cur, FORK, fork_tables[tbl])
            on = " AND ".join(f"r.`k{n + 1}` = w.`{k}`" for n, k in enumerate(pk))
            cur.execute(f"SELECT w.`{col}` FROM `{STEP}{isql.IMPORT_ROWS}` r JOIN `{STEP}{tbl}` w ON {on} "
                        f"WHERE r.tbl = %s AND NOT EXISTS (SELECT 1 FROM `{STEP}{target}` x WHERE x.`{tkey}` = w.`{col}`)", (tbl,))
            broken += [f"{tbl}.{col} {r[0]} (no {target})" for r in cur.fetchall()]
    for f in manifest["fixes"]:          # the corrections' own rows: updates of a quest that must exist
        if f["kind"] == "update":
            cur.execute(f"SELECT COUNT(*) FROM `{STEP}quest_template` WHERE ID = %s", (f["quest"],))
            if not cur.fetchone()[0]:
                broken.append(f"fix {f['fix']}: quest {f['quest']} missing")
    cur.execute(f"SELECT o.ID, o.Type, o.ObjectID FROM `{STEP}{isql.IMPORT_ROWS}` r JOIN `{STEP}quest_objectives` o ON r.k1 = o.ID "
                "WHERE r.tbl = 'quest_objectives'")
    for oid, otype, target in cur.fetchall():
        table = {0: "creature_template", 3: "creature_template", 2: "gameobject_template"}.get(otype)
        if table:
            cur.execute(f"SELECT COUNT(*) FROM `{STEP}{table}` WHERE entry = %s", (target,))
            if not cur.fetchone()[0]:
                broken.append(f"objective {oid}: {table} {target} missing")
        elif otype == 1:             # items live in the client's tables, not the world: forever-db's item list
            cur.execute(f"SELECT COUNT(*) FROM `{FORK}`.src_forever_db WHERE tbl = 'item' AND id = %s", (target,))
            if not cur.fetchone()[0]:
                broken.append(f"objective {oid}: item {target} unknown to Forever's client data")
        else:
            broken.append(f"objective {oid}: type {otype} can't be checked here")
    checks.add("every new row points at things that exist", not broken, "; ".join(broken[:20]))

    # running the files again changes nothing
    watched = sorted(set(added_expect) | set(removed_expect) | set(changed_expect) | {isql.IMPORT_ROWS})
    before = {t: fingerprint(cur, DRYRUN, f"{STEP}{t}", columns(cur, DRYRUN, f"{STEP}{t}")) for t in watched}
    rerun_errors = []
    for name in sorted(ours):
        for statement in custom_sql.statements(ours[name].decode("utf-8")):
            sql, _, problems = custom_sql.retarget(statement, mapping)
            if problems:
                raise SystemExit(f"{name}: {problems}")
            try:
                cur.execute(sql)
            except Exception as error:  # noqa: BLE001 - a file that can't run twice fails the check, not the tool
                rerun_errors.append(f"{name}: {error}")
                conn.rollback()
                break
        conn.commit()
    after = {t: fingerprint(cur, DRYRUN, f"{STEP}{t}", columns(cur, DRYRUN, f"{STEP}{t}")) for t in watched}
    checks.add("running our files again changes nothing", before == after and not rerun_errors,
               "; ".join(rerun_errors + [t for t in watched if before[t] != after[t]]))
    cur.execute(f"SELECT name, hash, state FROM `{STEP}updates`")
    held2 = {r[0]: (r[1] or "", r[2]) for r in cur.fetchall()}
    again = load_tc.apply_update_files(conn, cur, raw, paths, mapping, skipped_tables, held2, "RELEASED")
    checks.add("the updater skips every file on the next start", not again, json.dumps(again[:5]))
    after2 = {t: fingerprint(cur, DRYRUN, f"{STEP}{t}", columns(cur, DRYRUN, f"{STEP}{t}")) for t in watched}
    checks.add("... and the world stays the same", after2 == after)

    # the gap report on the stepped world against the fork world's
    gaps = {}
    for label, world in (("before", f"{FORK}.tc_"), ("after", f"{DRYRUN}.{STEP}")):
        out = os.path.join(args.data, args.slice, "gaps-" + label)
        subprocess.run([sys.executable, os.path.join(HERE, "gap_report.py"), "--world", world, "--out", out, "--sources", args.sources],
                       check=True, stdout=subprocess.DEVNULL)
        with open(os.path.join(out, "everlake-gaps.json")) as handle:
            report = json.load(handle)
        gaps[label] = {}
        for zone, cats in report["zones"].items():
            for cat, items in cats.items():
                for i in items:
                    gaps[label].setdefault(cat, set()).add(i.get("quest") or i.get("npc") or i.get("object"))
        gaps[label + "_totals"] = report["totals"]
    outcomes = manifest["outcomes"]
    closed, left, unexplained, new = {}, {}, [], []
    for cat in gaps["before_totals"]:
        b, a = gaps["before"].get(cat, set()), gaps["after"].get(cat, set())
        # a quest may move from "no giver" to "other givers" when only some of the vote's givers could be added
        moved = {q for q in a - b if outcomes.get(cat, {}).get(str(q), "").split(":")[0] in ("review", "held back")}
        if a - b - moved:
            new.append(f"{cat}: {sorted(a - b - moved)[:10]}")
        if cat in SLICE_CATEGORIES:
            closed[cat] = len(b - a)
            left[cat] = collections.Counter()
            for q in sorted(a):
                why = outcomes.get(cat, {}).get(str(q), "")
                kind = why.split(":")[0]
                if kind in ("review", "held back", "kept"):
                    left[cat][kind] += 1
                else:
                    unexplained.append(f"{cat} {q} ({why or 'no decision'})")
            for q in sorted(b - a):
                if not outcomes.get(cat, {}).get(str(q), "").startswith(("added", "corrected")):
                    unexplained.append(f"{cat} {q} closed without a decision ({outcomes.get(cat, {}).get(str(q))})")
    checks.add("the gap report: each slice-1 gap is closed, or on the review or held-back list", not unexplained,
               "; ".join(unexplained[:20]))
    checks.add("the gap report: no category gains an item", not new, "; ".join(new[:10]))

    # the fork changes our rows between two runs of our files (rule 5: the updater runs them again later)
    simulate(cur, conn, manifest, ours, mapping, checks)

    if args.drop:
        drop_prefix(cur, STEP)
        drop_prefix(cur, SCRATCH)
    conn.commit()
    result = {"slice": args.slice, "made": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "files": manifest["files"], "world": manifest["world"], "checks": checks.items, "ok": checks.ok,
              "scratch_run": not args.skip_scratch, "timings_s": timings, "tables_changed": per_table,
              "recorded": dict(collections.Counter(r[0] for r in recorded)),
              "gaps_before": gaps["before_totals"], "gaps_after": gaps["after_totals"], "closed": closed,
              "left": {c: dict(v) for c, v in left.items()}}
    with open(os.path.join(args.data, args.slice, "dry-run.json"), "w") as handle:
        json.dump(result, handle, indent=1, sort_keys=True)
    with open(os.path.join(args.data, args.slice, "dry-run.md"), "w") as handle:
        handle.write(report_md(result, manifest))
    print(f"wrote {os.path.join(args.data, args.slice, 'dry-run.md')}: {'all checks pass' if checks.ok else 'CHECKS FAILED'}")
    sys.exit(0 if checks.ok else 1)


def run_file(cur, conn, text, mapping):
    for statement in custom_sql.statements(text):
        sql, _, problems = custom_sql.retarget(statement, mapping)
        if problems:
            raise SystemExit(f"{problems}")
        cur.execute(sql)
    conn.commit()


def simulate(cur, conn, manifest, ours, mapping, checks):
    """Change the stepped world as a later fork file might, run our files again, and check they leave the fork's rows
    alone. Runs last: the stepped world is changed afterwards (the scratch world is not)."""
    by_kind = {f["kind"]: f["name"] for f in manifest["files"]}
    imp, fixes = by_kind.get("import"), by_kind.get("corrections")
    # 1. a fork file takes over a quest we gave givers or enders: DELETE its rows, INSERT one of ours with its own build
    cur.execute(f"SELECT tbl, k2, COUNT(*) AS n FROM `{STEP}{isql.IMPORT_ROWS}` WHERE file = %s AND tbl LIKE %s "
                "GROUP BY tbl, k2 ORDER BY n DESC, k2 LIMIT 1", (imp, "%quest%er"))
    row = cur.fetchone()
    if row:
        tbl, quest, _ = row
        cur.execute(f"SELECT k1 FROM `{STEP}{isql.IMPORT_ROWS}` WHERE tbl = %s AND k2 = %s ORDER BY k1", (tbl, quest))
        ids = [r[0] for r in cur.fetchall()]
        cur.execute(f"DELETE FROM `{STEP}{tbl}` WHERE quest = %s", (quest,))
        cur.execute(f"INSERT INTO `{STEP}{tbl}` (id, quest, VerifiedBuild) VALUES (%s, %s, 70900)", (ids[0], quest))
        conn.commit()
        run_file(cur, conn, ours[imp].decode("utf-8"), mapping)
        other = tbl.replace("creature_", "gameobject_") if tbl.startswith("creature_") else tbl.replace("gameobject_", "creature_")
        cur.execute(f"SELECT id, VerifiedBuild FROM `{STEP}{tbl}` WHERE quest = %s UNION ALL "
                    f"SELECT -id, VerifiedBuild FROM `{STEP}{other}` WHERE quest = %s", (quest, quest))
        got = sorted(cur.fetchall())
        checks.add(f"after the fork takes over quest {quest}'s {tbl} rows ({len(ids)} were ours), a re-run adds nothing next to its",
                   got == [(ids[0], 70900)], str(got))
    # 2. the fork re-sniffs a row a correction filled in: the correction must not act again
    upd = next((f for f in manifest["fixes"] if f["kind"] == "update"), None)
    if upd and fixes:
        col = next(iter(upd["set"]))
        where = " AND ".join(f"`{k}` = {int(v)}" for k, v in upd["key"].items())
        cur.execute(f"UPDATE `{STEP}{upd['table']}` SET `{col}` = '', VerifiedBuild = 70900 WHERE {where}")
        conn.commit()
        run_file(cur, conn, ours[fixes].decode("utf-8"), mapping)
        cur.execute(f"SELECT `{col}` FROM `{STEP}{upd['table']}` WHERE {where}")
        checks.add(f"after the fork re-sniffs {upd['table']} {upd['key']}, a re-run of the corrections leaves it", cur.fetchone()[0] == "")
    # 3. the fork puts back a giver a correction removed: the correction must not remove it again
    rel = next((f for f in manifest["fixes"] if f["kind"] == "relations" and f["delete"]), None)
    if rel and fixes:
        d = rel["delete"][0]
        cur.execute(f"INSERT INTO `{STEP}{d['table']}` (id, quest, VerifiedBuild) VALUES (%s, %s, 70900)", (d["id"], d["quest"]))
        conn.commit()
        run_file(cur, conn, ours[fixes].decode("utf-8"), mapping)
        cur.execute(f"SELECT COUNT(*) FROM `{STEP}{d['table']}` WHERE id = %s AND quest = %s", (d["id"], d["quest"]))
        checks.add(f"after the fork puts back {d['table']} {d['id']} for quest {d['quest']}, a re-run of the corrections leaves it",
                   cur.fetchone()[0] == 1)


def report_md(r, manifest):
    adds = {t: len(v) for t, v in manifest["adds"].items()}
    fixes = manifest["fixes"]
    rel = [f for f in fixes if f["kind"] == "relations"]
    out = [f"# Everlake world import, {r['slice']}: dry run", "",
           f"Made {r['made']} by tools/forever-data/import_dryrun.py against the fork world {r['world']}. "
           f"Result: **{'every check passes' if r['ok'] else 'a check FAILED'}**.", "",
           "## Files", ""]
    out += [f"- `{f['name']}` ({f['kind']}, SHA1 {f['sha1'][:12]})" for f in r["files"]]
    out += ["", "## What the files do", "",
            "| | Rows |", "|---|---|"]
    out += [f"| add `{t}` | {n} |" for t, n in sorted(adds.items())]
    out += [f"| corrections: other givers or enders | {len(rel)} quests: {sum(len(f['add']) for f in rel)} rows added, "
            f"{sum(len(f['delete']) for f in rel)} fork rows removed |",
            f"| corrections: empty text filled in | {sum(1 for f in fixes if f['kind'] == 'update')} |",
            f"| close calls (review list, not in the files) | {len(manifest['review'])} |",
            f"| held back | {len(manifest['held_back'])} |", ""]
    out += ["Objective rows: " + (f"written with Flags,Flags2 = {manifest['objective_flags']}" if manifest["objective_flags"]
                                  else "none written: no public source records their Flags (see held back)") + ".", ""]
    out += ["## Runs", ""]
    out.append(f"- Stepped (the fork world as deployed, then our files): {r['timings_s'].get('stepped', '?')} s.")
    out.append("- From scratch (the world release, then every fork file and ours in name order): "
               + (f"{r['timings_s'].get('scratch', '?')} s." if r["scratch_run"] else "skipped (--skip-scratch)."))
    out += ["", "## Checks", ""]
    out += [f"- {'pass' if c['ok'] else '**FAIL**'}: {c['check']}" + (f" ({c['detail']})" if c["detail"] and not c["ok"] else "")
            for c in r["checks"]]
    out += ["", "Tables changed against the fork world (rows): " +
            ", ".join(f"`{t}` +{v['added']} -{v['removed']} ~{v['changed']}" for t, v in sorted(r["tables_changed"].items())), ""]
    out += ["## Gap report, before and after", "", "| Gap | Before | After | Closed | Left: review | Left: held back | Left: kept |",
            "|---|---|---|---|---|---|---|"]
    for cat in SLICE_CATEGORIES:
        left = r["left"].get(cat, {})
        out.append(f"| {cat} | {r['gaps_before'].get(cat, 0)} | {r['gaps_after'].get(cat, 0)} | {r['closed'].get(cat, 0)} | "
                   f"{left.get('review', 0)} | {left.get('held back', 0)} | {left.get('kept', 0)} |")
    others = [c for c in r["gaps_before"] if c not in SLICE_CATEGORIES and r["gaps_before"][c] != r["gaps_after"].get(c)]
    out += ["", "Other categories: " + ("unchanged." if not others else "changed: " + ", ".join(
        f"{c} {r['gaps_before'][c]} -> {r['gaps_after'].get(c)}" for c in others)), ""]
    held = collections.Counter(h.get("reason") or h["why"] for h in manifest["held_back"])
    out += ["## Held back, by reason", "", "Full list: held-back.md.", ""]
    out += [f"- {n} x {why}" for why, n in held.most_common()]
    out += ["", "## Close calls", "", "Full list: review.md.", ""]
    review = collections.Counter(i["category"] for i in manifest["review"])
    out += [f"- {cat}: {n}" for cat, n in sorted(review.items())]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    main()
