#!/usr/bin/env python3
"""Dry-runs every Everlake world import file by the fork's updater rules, twice, and checks them (docs/forever-import.md,
"How a run works").

    import_dryrun.py                     dry-run world-data/ (the import_slice*.py output)
    import_dryrun.py --data DIR          a clone of wow-everlake-world-data
    import_dryrun.py --report slice2     where the report goes (default: the newest slice)
    import_dryrun.py --skip-scratch      only the stepped run (quick; the report says the scratch run was skipped)
    import_dryrun.py --drop              remove the dry-run tables afterwards

Every slice's files run together: <data>/sql/world holds them all, and <data>/slices/<slice>/manifest.json (or the
older <data>/<slice>/manifest.json) says what each slice's files do. The files there must be exactly the ones the
manifests name.

Both runs build a world in the scratch schema acore_world_dryrun, as tables with their own prefix, so nothing else in
that schema is touched (only tables named elscratch_* and elstep_* are created or dropped):
- from scratch (elscratch_*): the fork's world release, then the fork's sql/updates and sql/custom world files and all
  our files in file-name order, as a new realm builds it (custom_sql.UpdatePlan, the same code load_tc.py runs);
- stepped (elstep_*): the deployed state, then the new files, as the realm will. Nothing is deployed yet, so the
  deployed state is the fork world with no import files: acore_forever.tc_* with its updates list (load_tc.py's
  world). Every fork file must then be skipped by the updater, or the deployed state isn't what tc_* says.

Checks:
- the two runs end with the same world (every table's rows; the updates list by name and hash);
- every fork row outside the corrections is unchanged: per table, the rows added are exactly the keys in
  everlake_import_rows, the rows removed or changed exactly those the corrections name (a table with no primary key,
  like creature_loot_template, is compared by its first index's columns, duplicates included);
- no recorded key was a fork row (no key collides), and every recorded key's row is there;
- every new row points at things that exist: givers and enders are creature or gameobject templates, quests exist,
  objectives' targets exist, loot items are in Forever's client item list, reference lists exist, every new loot table
  is some creature's, and every corrected row is there;
- running the files again changes nothing (run directly, and the updater skips them), and after simulated fork changes
  (each slice's own: a quest's givers taken over, a corrected row re-sniffed, a removed giver put back, a loot row we
  added removed, a creature given its own loot table) a re-run leaves the fork's rows alone (this runs last and changes
  the stepped world);
- the gap report on the stepped world: every item of the slices' categories is closed or on the review or held-back
  list with its reason, and no category gains an item. Loot, trainer-spell and vendor-item gaps count per item of an
  NPC (npc/item), the rest per quest or NPC.
Writes <slice folder>/dry-run.md and dry-run.json for the --report slice. Exit status 1 when a check fails.
"""
import argparse
import collections
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
# gap categories counted per item of an NPC (npc/item: a drop, a trainer spell, a vendor item), not per whole NPC
PER_ITEM = {"loot_items_missing", "npcs_no_loot", "trainer_spells_missing", "vendor_items_missing"}
# what each kind of recorded row must point at: (column, table it must be in, that table's key column)
REFERENCES = {
    "creature_queststarter": [("id", "creature_template", "entry"), ("quest", "quest_template", "ID")],
    "creature_questender": [("id", "creature_template", "entry"), ("quest", "quest_template", "ID")],
    "gameobject_queststarter": [("id", "gameobject_template", "entry"), ("quest", "quest_template", "ID")],
    "gameobject_questender": [("id", "gameobject_template", "entry"), ("quest", "quest_template", "ID")],
    "quest_request_items": [("ID", "quest_template", "ID")],
    "quest_offer_reward": [("ID", "quest_template", "ID")],
    "quest_objectives": [("QuestID", "quest_template", "ID")],
    "trainer_spell": [("TrainerId", "trainer", "Id")],
    "npc_vendor": [("entry", "creature_template", "entry")],
    "creature": [("id", "creature_template", "entry")],
    "gameobject": [("id", "gameobject_template", "entry")],
    "creature_template_difficulty": [("Entry", "creature_template", "entry")],
    "creature_template_model": [("CreatureID", "creature_template", "entry")],
    "creature_classic_level": [("entry", "creature_template", "entry")],
    "gameobject_questitem": [("GameObjectEntry", "gameobject_template", "entry")],
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


def row_key(cur, schema, table):
    """(key columns, unique?): the primary key, or for a table without one (TrinityCore's loot tables) the columns of
    its first index, under which several rows may stand."""
    pk = primary_key(cur, schema, table)
    if pk:
        return pk, True
    cur.execute("SELECT index_name, column_name FROM information_schema.statistics WHERE table_schema = %s AND table_name = %s "
                "ORDER BY index_name = 'idx_primary' DESC, index_name, seq_in_index", (schema, table))
    got = cur.fetchall()
    first = got[0][0] if got else None
    return [c for i, c in got if i == first], False


def row_sql(cols, alias=""):
    a = f"{alias}." if alias else ""
    return "MD5(CONCAT_WS(',', " + ", ".join(f"QUOTE({a}`{c}`)" for c in cols) + "))"


def fingerprint(cur, schema, table, cols):
    """(rows, sum of the first 60 bits of each row's MD5): the same for the same rows in any order."""
    cur.execute(f"SELECT COUNT(*), COALESCE(SUM(CAST(CONV(SUBSTRING({row_sql(cols)}, 1, 15), 16, 10) AS UNSIGNED)), 0) "
                f"FROM `{schema}`.`{table}`")
    n, s = cur.fetchone()
    return int(n), int(s)


def pad(key):
    key = list(key)
    return tuple(key + [0] * (4 - len(key)))


def our_files(data):
    folder = os.path.join(data, "sql", "world")
    out = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith(".sql"):
            isql.check_name(name)
            with open(os.path.join(folder, name), "rb") as handle:
                out[name] = handle.read()
    return out


def load_manifests(data):
    """Every slice's manifest, in the order of its first file (the order the updater runs them): [(folder, manifest)]."""
    paths = sorted(glob.glob(os.path.join(data, "slices", "*", "manifest.json")))
    if not paths:
        paths = sorted(glob.glob(os.path.join(data, "*", "manifest.json")))
    out = []
    for path in paths:
        with open(path) as handle:
            out.append((os.path.dirname(path), json.load(handle)))
    if not out:
        raise SystemExit(f"{data}: no slices/<slice>/manifest.json")
    return sorted(out, key=lambda fm: min(f["name"] for f in fm[1]["files"]))


def fork_mapping(cur, prefix, raw_all, skipped):
    """Every world table name -> prefix + name, as load_tc.py maps them (tables the files create included)."""
    have = set(tables(cur, DRYRUN, prefix))
    created = {t: tmp for t, tmp in custom_sql.created_tables(b.decode("utf-8") for b in raw_all.values()).items()
               if not load_tc.SKIP.search(t)}
    mapping = {t: prefix + t for t in have | {t for t, tmp in created.items() if not tmp}}
    mapping.update({t: f"{prefix}{t}__tmp" for t, tmp in created.items() if tmp})
    return mapping, {t for t in skipped if t != "updates_include"}


def gap_keys(cat, item):
    if cat in PER_ITEM:
        return {f"{item['npc']}/{i}" for i in item.get("items", ())}
    return {str(item.get("quest") or item.get("npc") or item.get("object"))}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--report", "--slice", dest="report", help="the slice whose folder gets the report (default: the newest)")
    ap.add_argument("--data", default=os.path.join(HERE, "world-data"))
    ap.add_argument("--sources", default=SOURCES)
    ap.add_argument("--skip-scratch", action="store_true")
    ap.add_argument("--drop", action="store_true")
    args = ap.parse_args()
    manifests = load_manifests(args.data)
    slices = {m["slice"]: (folder, m) for folder, m in manifests}
    report_slice = args.report or manifests[-1][1]["slice"]
    if report_slice not in slices:
        raise SystemExit(f"--report {report_slice}: the slices are {sorted(slices)}")
    with open(os.path.join(args.sources, "manifest.json")) as handle:
        current = json.load(handle)["current"]
    release, custom_pin = current["tc-release"], current["tc-forever"]
    ours = our_files(args.data)
    names = {f["name"] for _, m in manifests for f in m["files"]}
    if set(ours) != names:
        raise SystemExit(f"{args.data}/sql/world holds {sorted(ours)}, the manifests name {sorted(names)}")
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
    print(f"dry run of {', '.join(slices)}: {', '.join(sorted(ours))}", flush=True)

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
    checks.add("stepped run: the updater applies each of our files once, in name order",
               [a["file"] for a in applied if a["file"] in ours and a["mode"] == "applied"] == sorted(ours),
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
    all_fixes = [f for _, m in manifests for f in m["fixes"]]
    for f in all_fixes:
        if f["kind"] == "relations":
            for d in f["delete"]:
                removed_expect[d["table"]].add((d["id"], d["quest"], 0, 0))
        else:               # in the table's key order: the manifest's keys are sorted by name
            changed_expect[f["table"]].add(pad(f["key"][c] for c in row_key(cur, FORK, fork_tables[f["table"]])[0]))
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
        key, unique = row_key(cur, FORK, full)
        if not key or len(key) > 4:
            unexpected.append(f"{name} changed (no usable key to say how)")
            continue
        added, removed, changed = diff_rows(cur, full, name, key, unique, cols)
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
        key, _ = row_key(cur, FORK, fork_tables[tbl])
        for k in keys:
            where = " AND ".join(f"`{c}` = {int(v)}" for c, v in zip(key, k))
            cur.execute(f"SELECT COUNT(*) FROM `{STEP}{tbl}` WHERE {where}")
            if cur.fetchone()[0] != 1:
                missing_rows.append(f"{tbl} {k}")
            cur.execute(f"SELECT COUNT(*) FROM `{FORK}`.`{fork_tables[tbl]}` WHERE {where}")
            if cur.fetchone()[0]:
                collisions.append(f"{tbl} {k}")
    checks.add("every recorded key's row is in the world, once", not missing_rows, ", ".join(missing_rows[:10]))
    checks.add("no key collides with a fork row", not collisions, ", ".join(collisions[:10]))
    files_of = collections.Counter(r[5] for r in recorded)
    checks.add("every recorded row names one of our files", set(files_of) <= set(ours), str(dict(files_of)))

    checks.add("every new row points at things that exist", *references(cur, fork_tables, all_fixes))

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
    report_folder = slices[report_slice][0]
    gaps = {}
    for label, world in (("before", f"{FORK}.tc_"), ("after", f"{DRYRUN}.{STEP}")):
        out = os.path.join(tempfile.mkdtemp(prefix="everlake-dryrun-"), "gaps-" + label)     # not in the data folder
        subprocess.run([sys.executable, os.path.join(HERE, "gap_report.py"), "--world", world, "--out", out, "--sources", args.sources],
                       check=True, stdout=subprocess.DEVNULL)
        with open(os.path.join(out, "everlake-gaps.json")) as handle:
            report = json.load(handle)
        shutil.rmtree(os.path.dirname(out))
        gaps[label] = {}
        for zone, cats in report["zones"].items():
            for cat, items in cats.items():
                for i in items:
                    gaps[label].setdefault(cat, set()).update(gap_keys(cat, i))
        gaps[label + "_totals"] = report["totals"]
        gaps[label + "_counts"] = {c: len(v) for c, v in gaps[label].items()}
    outcomes = collections.defaultdict(dict)
    for _, m in manifests:
        for cat, v in m["outcomes"].items():
            outcomes[cat].update(v)

    def outcome(cat, q):
        """A gap's decision; a per-item gap (npc/item) may be decided for all of an NPC's items as npc/*."""
        got = outcomes.get(cat, {})
        return got.get(q) or (got.get(q.split("/")[0] + "/*", "") if cat in PER_ITEM else "")
    slice_categories = [c for _, m in manifests for c in m["outcomes"]]
    slice_categories = list(dict.fromkeys(slice_categories))
    closed, left, unexplained, new = {}, {}, [], []
    for cat in gaps["before_totals"]:
        b, a = gaps["before"].get(cat, set()), gaps["after"].get(cat, set())
        # a quest may move from "no giver" to "other givers" when only some of the vote's givers could be added, and a
        # drop from "no loot table" to "loot short" when its NPC got a table with other drops
        moved = {q for q in a - b if outcome(cat, q).split(":")[0] in ("review", "held back")}
        if a - b - moved:
            new.append(f"{cat}: {sorted(a - b - moved)[:10]}")
        if cat in slice_categories:
            closed[cat] = len(b - a)
            left[cat] = collections.Counter()
            for q in sorted(a):
                why = outcome(cat, q)
                kind = why.split(":")[0]
                if kind in ("review", "held back", "kept"):
                    left[cat][kind] += 1
                else:
                    unexplained.append(f"{cat} {q} ({why or 'no decision'})")
            for q in sorted(b - a):
                why = outcome(cat, q)
                moved_to = re.match(r"moved to (\w+): ", why)
                if moved_to:            # e.g. a drop of an NPC that got a loot table, still short: now "loot short"
                    if q not in gaps["after"].get(moved_to.group(1), set()):
                        unexplained.append(f"{cat} {q} said to move to {moved_to.group(1)}, but isn't there")
                elif not why.startswith(("added", "corrected")):
                    unexplained.append(f"{cat} {q} closed without a decision ({why or None})")
    checks.add("the gap report: each gap of the slices' categories is closed, or on the review or held-back list", not unexplained,
               "; ".join(unexplained[:20]))
    checks.add("the gap report: no category gains an item", not new, "; ".join(new[:10]))

    # the fork changes our rows between two runs of our files (rule 5: the updater runs them again later)
    for _, m in manifests:
        SIMULATIONS.get(m["slice"], lambda *a: None)(cur, conn, m, ours, mapping, checks)

    if args.drop:
        drop_prefix(cur, STEP)
        drop_prefix(cur, SCRATCH)
    conn.commit()
    result = {"slices": list(slices), "report": report_slice,
              "made": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "files": [f for _, m in manifests for f in m["files"]], "world": manifests[-1][1]["world"], "checks": checks.items,
              "ok": checks.ok, "scratch_run": not args.skip_scratch, "timings_s": timings, "tables_changed": per_table,
              "recorded": dict(collections.Counter(r[0] for r in recorded)), "categories": slice_categories,
              "gaps_before": gaps["before_counts"], "gaps_after": gaps["after_counts"], "closed": closed,
              "left": {c: dict(v) for c, v in left.items()}}
    with open(os.path.join(report_folder, "dry-run.json"), "w") as handle:
        json.dump(result, handle, indent=1, sort_keys=True)
    with open(os.path.join(report_folder, "dry-run.md"), "w") as handle:
        handle.write(report_md(result, [m for _, m in manifests]))
    print(f"wrote {os.path.join(report_folder, 'dry-run.md')}: {'all checks pass' if checks.ok else 'CHECKS FAILED'}")
    sys.exit(0 if checks.ok else 1)


def diff_rows(cur, full, name, key, unique, cols):
    """The keys (padded to 4) of rows added, removed and changed in the stepped world against the fork's. A key of a
    table without a unique key counts as changed when the rows under it differ in any way (one more, one less, one
    different)."""
    on = " AND ".join(f"t.`{k}` = s.`{k}`" for k in key)
    keys = ", ".join(f"s.`{k}`" for k in key)
    cur.execute(f"SELECT DISTINCT {keys} FROM `{STEP}{name}` s WHERE NOT EXISTS (SELECT 1 FROM `{FORK}`.`{full}` t WHERE {on})")
    added = {pad(r) for r in cur.fetchall()}
    cur.execute(f"SELECT DISTINCT {keys.replace('s.', 't.')} FROM `{FORK}`.`{full}` t WHERE NOT EXISTS (SELECT 1 FROM `{STEP}{name}` s WHERE {on})")
    removed = {pad(r) for r in cur.fetchall()}
    if unique:
        cur.execute(f"SELECT {keys} FROM `{STEP}{name}` s JOIN `{FORK}`.`{full}` t ON {on} WHERE {row_sql(cols, 's')} <> {row_sql(cols, 't')}")
        return added, removed, {pad(r) for r in cur.fetchall()}
    bare = ", ".join(f"`{k}`" for k in key)

    def groups(table):
        cur.execute(f"SELECT {bare}, COUNT(*), SUM(CAST(CONV(SUBSTRING({row_sql(cols)}, 1, 15), 16, 10) AS UNSIGNED)) "
                    f"FROM {table} GROUP BY {bare}")
        return {pad(r[:len(key)]): (int(r[-2]), int(r[-1])) for r in cur.fetchall()}
    a, b = groups(f"`{STEP}{name}`"), groups(f"`{FORK}`.`{full}`")
    return added, removed, {k for k in set(a) & set(b) if a[k] != b[k]}


def references(cur, fork_tables, fixes):
    """(ok, detail): every recorded row's references, and every corrected row, are in the stepped world."""
    broken = []
    for tbl, refs in REFERENCES.items():
        for col, target, tkey in refs:
            pk = primary_key(cur, FORK, fork_tables[tbl])
            on = " AND ".join(f"r.`k{n + 1}` = w.`{k}`" for n, k in enumerate(pk))
            cur.execute(f"SELECT w.`{col}` FROM `{STEP}{isql.IMPORT_ROWS}` r JOIN `{STEP}{tbl}` w ON {on} "
                        f"WHERE r.tbl = %s AND NOT EXISTS (SELECT 1 FROM `{STEP}{target}` x WHERE x.`{tkey}` = w.`{col}`)", (tbl,))
            broken += [f"{tbl}.{col} {r[0]} (no {target})" for r in cur.fetchall()]
    for f in fixes:                     # a corrected row must still be there
        if f["kind"] == "update":
            where = " AND ".join(f"`{k}` = {int(v)}" for k, v in f["key"].items())
            cur.execute(f"SELECT COUNT(*) FROM `{STEP}{f['table']}` WHERE {where}")
            if not cur.fetchone()[0]:
                broken.append(f"fix {f['fix']}: {f['table']} {f['key']} missing")
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
    # loot: items in Forever's client item list, reference lists that exist, and every table some creature's loot
    loot = "creature_loot_template"
    rec = (f"`{STEP}{isql.IMPORT_ROWS}` r JOIN `{STEP}{loot}` w ON r.k1 = w.Entry AND r.k2 = w.ItemType AND r.k3 = w.Item "
           f"WHERE r.tbl = '{loot}'")
    cur.execute(f"SELECT w.Entry, w.Item FROM {rec} AND w.ItemType = 0 AND NOT EXISTS (SELECT 1 FROM `{FORK}`.src_forever_db x "
                "WHERE x.tbl = 'item' AND x.id = w.Item)")
    broken += [f"loot {e}: item {i} unknown to Forever's client data" for e, i in cur.fetchall()]
    cur.execute(f"SELECT w.Entry, w.Item FROM {rec} AND w.ItemType = 1 AND NOT EXISTS (SELECT 1 FROM `{STEP}reference_loot_template` x "
                "WHERE x.Entry = w.Item)")
    broken += [f"loot {e}: reference list {i} missing" for e, i in cur.fetchall()]
    cur.execute(f"SELECT w.Entry, w.ItemType, w.Item FROM {rec} AND w.ItemType NOT IN (0, 1)")
    broken += [f"loot {e}: ItemType {t} for {i} (only items and reference lists are imported)" for e, t, i in cur.fetchall()]
    cur.execute(f"SELECT DISTINCT w.Entry FROM {rec} AND NOT EXISTS (SELECT 1 FROM `{STEP}creature_template_difficulty` d "
                "WHERE d.LootID = w.Entry)")
    broken += [f"loot table {e} is no creature's" for (e,) in cur.fetchall()]
    # trainer spells: the spell and what it needs known first are in Forever's client spell tables (item-history's, a
    # reference used only for this check), and the list is some creature's; vendor items: in the client's item list
    rec = (f"`{STEP}{isql.IMPORT_ROWS}` r JOIN `{STEP}trainer_spell` w ON r.k1 = w.TrainerId AND r.k2 = w.SpellId "
           "WHERE r.tbl = 'trainer_spell'")
    for col in ("SpellId", "ReqAbility1", "ReqAbility2", "ReqAbility3"):
        cur.execute(f"SELECT w.TrainerId, w.`{col}` FROM {rec} AND w.`{col}` <> 0 AND NOT EXISTS (SELECT 1 FROM "
                    f"`{FORK}`.src_item_history x WHERE x.tbl = 'spells' AND x.id = w.`{col}`)")
        broken += [f"trainer list {t}: {col} {i} unknown to Forever's client spell tables" for t, i in cur.fetchall()]
    cur.execute(f"SELECT DISTINCT w.TrainerId FROM {rec} AND NOT EXISTS (SELECT 1 FROM `{STEP}creature_trainer` c WHERE c.TrainerID = w.TrainerId)")
    broken += [f"trainer list {t} is no creature's" for (t,) in cur.fetchall()]
    # new templates: models in Forever's client (wago.tools' display tables of the pinned build), and each has a spawn
    cur.execute(f"SELECT w.CreatureID, w.CreatureDisplayID FROM `{STEP}{isql.IMPORT_ROWS}` r JOIN `{STEP}creature_template_model` w "
                f"ON r.k1 = w.CreatureID AND r.k2 = w.Idx WHERE r.tbl = 'creature_template_model' AND NOT EXISTS (SELECT 1 FROM "
                f"`{FORK}`.src_wago x WHERE x.tbl = 'CreatureDisplayInfo' AND x.id = w.CreatureDisplayID)")
    broken += [f"creature {e}: model {i} not in Forever's client" for e, i in cur.fetchall()]
    cur.execute(f"SELECT w.entry, w.displayId FROM `{STEP}{isql.IMPORT_ROWS}` r JOIN `{STEP}gameobject_template` w ON r.k1 = w.entry "
                f"WHERE r.tbl = 'gameobject_template' AND w.displayId <> 0 AND NOT EXISTS (SELECT 1 FROM `{FORK}`.src_wago x "
                "WHERE x.tbl = 'GameObjectDisplayInfo' AND x.id = w.displayId)")
    broken += [f"object {e}: model {i} not in Forever's client" for e, i in cur.fetchall()]
    for tbl, spawn in (("creature_template", "creature"), ("gameobject_template", "gameobject")):
        cur.execute(f"SELECT r.k1 FROM `{STEP}{isql.IMPORT_ROWS}` r WHERE r.tbl = %s AND NOT EXISTS (SELECT 1 FROM "
                    f"`{STEP}{spawn}` c WHERE c.id = r.k1)", (tbl,))
        broken += [f"{tbl} {e}: added with no spawn" for (e,) in cur.fetchall()]
    # chest loot: items in the client's item list, and the table is a chest's
    loot = "gameobject_loot_template"
    rec = (f"`{STEP}{isql.IMPORT_ROWS}` r JOIN `{STEP}{loot}` w ON r.k1 = w.Entry AND r.k2 = w.ItemType AND r.k3 = w.Item "
           f"WHERE r.tbl = '{loot}'")
    cur.execute(f"SELECT w.Entry, w.Item FROM {rec} AND (w.ItemType <> 0 OR NOT EXISTS (SELECT 1 FROM `{FORK}`.src_forever_db x "
                "WHERE x.tbl = 'item' AND x.id = w.Item))")
    broken += [f"chest loot {e}: item {i} unknown to Forever's client data" for e, i in cur.fetchall()]
    cur.execute(f"SELECT DISTINCT w.Entry FROM {rec} AND NOT EXISTS (SELECT 1 FROM `{STEP}gameobject_template` g WHERE g.type = 3 "
                "AND g.Data1 = w.Entry)")
    broken += [f"chest loot table {e} is no chest's" for (e,) in cur.fetchall()]
    cur.execute(f"SELECT w.entry, w.item FROM `{STEP}{isql.IMPORT_ROWS}` r JOIN `{STEP}npc_vendor` w ON r.k1 = w.entry AND r.k2 = w.item "
                f"AND r.k3 = w.ExtendedCost AND r.k4 = w.type WHERE r.tbl = 'npc_vendor' AND (w.type <> 1 OR w.item <= 0 OR NOT EXISTS "
                f"(SELECT 1 FROM `{FORK}`.src_forever_db x WHERE x.tbl = 'item' AND x.id = w.item))")
    broken += [f"vendor {e}: item {i} unknown to Forever's client data" for e, i in cur.fetchall()]
    return not broken, "; ".join(broken[:20])


def run_file(cur, conn, text, mapping):
    for statement in custom_sql.statements(text):
        sql, _, problems = custom_sql.retarget(statement, mapping)
        if problems:
            raise SystemExit(f"{problems}")
        cur.execute(sql)
    conn.commit()


def simulate_slice1(cur, conn, manifest, ours, mapping, checks):
    """Change the stepped world as a later fork file might, run slice 1's files again, and check they leave the fork's
    rows alone. Runs last: the stepped world is changed afterwards (the scratch world is not)."""
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


def simulate_slice2(cur, conn, manifest, ours, mapping, checks):
    """Slice 2 (loot): the fork removes a drop we added, or gives a creature we linked a table to its own loot table."""
    by_kind = {f["kind"]: f["name"] for f in manifest["files"]}
    imp, fixes = by_kind.get("import"), by_kind.get("corrections")
    loot = "creature_loot_template"
    # 1. a fork file rewrites a loot table we added a drop to, without that drop: a re-run must not add it back
    cur.execute(f"SELECT k1, k2, k3 FROM `{STEP}{isql.IMPORT_ROWS}` WHERE file = %s AND tbl = %s AND k1 < %s ORDER BY k1, k3 LIMIT 1",
                (imp, loot, manifest.get("new_loot_base", 900_000_000)))
    row = cur.fetchone()
    if row:
        entry, item_type, item = row
        cur.execute(f"DELETE FROM `{STEP}{loot}` WHERE Entry = %s AND ItemType = %s AND Item = %s", (entry, item_type, item))
        conn.commit()
        run_file(cur, conn, ours[imp].decode("utf-8"), mapping)
        cur.execute(f"SELECT COUNT(*) FROM `{STEP}{loot}` WHERE Entry = %s AND ItemType = %s AND Item = %s", (entry, item_type, item))
        checks.add(f"after the fork drops item {item} from loot table {entry} (ours), a re-run doesn't add it back",
                   cur.fetchone()[0] == 0)
    # 2. the fork gives a creature we linked a new table to its own loot table: the correction must not act again
    fix = next((f for f in manifest["fixes"] if f["kind"] == "update"), None)
    if fix and fixes:
        npc = fix["key"]["Entry"]
        cur.execute(f"UPDATE `{STEP}creature_template_difficulty` SET LootID = %s, VerifiedBuild = 70900 WHERE Entry = %s AND DifficultyID = 0",
                    (npc, npc))
        conn.commit()
        run_file(cur, conn, ours[fixes].decode("utf-8"), mapping)
        run_file(cur, conn, ours[imp].decode("utf-8"), mapping)
        cur.execute(f"SELECT LootID FROM `{STEP}creature_template_difficulty` WHERE Entry = %s AND DifficultyID = 0", (npc,))
        checks.add(f"after the fork links creature {npc}'s own loot table, a re-run of slice 2 leaves it", cur.fetchone()[0] == npc)
    if not row and not fix:
        checks.add("slice 2: nothing to simulate (no rows)", True)


def simulate_slice3(cur, conn, manifest, ours, mapping, checks):
    """Slice 3 (trainers and vendors): the fork removes a trainer spell we added, or lists a vendor item we added at its
    own price (another ExtendedCost) in its place."""
    imp = next(f["name"] for f in manifest["files"] if f["kind"] == "import")
    cur.execute(f"SELECT k1, k2 FROM `{STEP}{isql.IMPORT_ROWS}` WHERE file = %s AND tbl = 'trainer_spell' ORDER BY k1, k2 LIMIT 1", (imp,))
    ts = cur.fetchone()
    if ts:
        cur.execute(f"DELETE FROM `{STEP}trainer_spell` WHERE TrainerId = %s AND SpellId = %s", ts)
        conn.commit()
        run_file(cur, conn, ours[imp].decode("utf-8"), mapping)
        cur.execute(f"SELECT COUNT(*) FROM `{STEP}trainer_spell` WHERE TrainerId = %s AND SpellId = %s", ts)
        checks.add(f"after the fork drops spell {ts[1]} from trainer list {ts[0]} (ours), a re-run doesn't add it back", cur.fetchone()[0] == 0)
    cur.execute(f"SELECT k1, k2, k3, k4 FROM `{STEP}{isql.IMPORT_ROWS}` WHERE file = %s AND tbl = 'npc_vendor' ORDER BY k1, k2 LIMIT 1", (imp,))
    nv = cur.fetchone()
    if nv:
        entry, item, ext, typ = nv
        cur.execute(f"DELETE FROM `{STEP}npc_vendor` WHERE entry = %s AND item = %s AND ExtendedCost = %s AND type = %s", nv)
        # as on a realm where the fork's row came first: nothing of ours recorded, so only the "another price" guard stops it
        cur.execute(f"DELETE FROM `{STEP}{isql.IMPORT_ROWS}` WHERE tbl = 'npc_vendor' AND k1 = %s AND k2 = %s AND k3 = %s AND k4 = %s", nv)
        cur.execute(f"INSERT INTO `{STEP}npc_vendor` (entry, slot, item, ExtendedCost, type, VerifiedBuild) VALUES (%s, 0, %s, 4242, %s, 70900)",
                    (entry, item, typ))
        conn.commit()
        run_file(cur, conn, ours[imp].decode("utf-8"), mapping)
        cur.execute(f"SELECT ExtendedCost FROM `{STEP}npc_vendor` WHERE entry = %s AND item = %s AND type = %s", (entry, item, typ))
        checks.add(f"where the fork lists vendor {entry}'s item {item} at its own price, our file adds nothing next to it",
                   [r[0] for r in cur.fetchall()] == [4242])
    if not ts and not nv:
        checks.add("slice 3: nothing to simulate (no rows)", True)


def simulate_slice4(cur, conn, manifest, ours, mapping, checks):
    """Slice 4 (spawns): the fork removes a spawn we added, or (on a realm where it came first) spawns the same NPC close to
    one of our points."""
    imp = next(f["name"] for f in manifest["files"] if f["kind"] == "import")
    cur.execute(f"SELECT k1 FROM `{STEP}{isql.IMPORT_ROWS}` WHERE file = %s AND tbl = 'creature' ORDER BY k1 LIMIT 2", (imp,))
    got = [r[0] for r in cur.fetchall()]
    if len(got) < 2:
        checks.add("slice 4: nothing to simulate (fewer than two spawns)", True)
        return
    gone, near = got
    cur.execute(f"DELETE FROM `{STEP}creature` WHERE guid = %s", (gone,))
    cur.execute(f"SELECT id, map, position_x, position_y, position_z FROM `{STEP}creature` WHERE guid = %s", (near,))
    i, m, x, y, z = cur.fetchone()
    cur.execute(f"DELETE FROM `{STEP}creature` WHERE guid = %s", (near,))
    cur.execute(f"DELETE FROM `{STEP}{isql.IMPORT_ROWS}` WHERE tbl = 'creature' AND k1 = %s", (near,))
    cur.execute(f"SELECT MAX(guid) + 1 FROM `{STEP}creature` WHERE guid < 900000000")
    fork_guid = cur.fetchone()[0]
    cur.execute(f"INSERT INTO `{STEP}creature` (guid, id, map, position_x, position_y, position_z, VerifiedBuild) VALUES (%s, %s, %s, %s, %s, %s, 70900)",
                (fork_guid, i, m, x + 10, y, z))
    conn.commit()
    run_file(cur, conn, ours[imp].decode("utf-8"), mapping)
    cur.execute(f"SELECT COUNT(*) FROM `{STEP}creature` WHERE guid IN (%s, %s)", (gone, near))
    checks.add(f"after the fork removes spawn {gone} (ours), and where it spawned NPC {i} 10 yards from our point first, "
               "a re-run adds neither", cur.fetchone()[0] == 0)


def simulate_slice5(cur, conn, manifest, ours, mapping, checks):
    """Slice 5 (new NPCs and objects): the fork takes one of our NPCs over (its own sniffed template under our entry, our
    record still there), and on a realm where the fork added one of our objects first (its own template, nothing of
    ours recorded): a run of our file adds nothing of ours next to them. A vendor and a chest with loot when there is one."""
    imp = next(f["name"] for f in manifest["files"] if f["kind"] == "import")
    for tbl, spawn, deps in (("creature_template", "creature", [("creature_template_difficulty", "Entry"), ("creature_template_model", "CreatureID"),
                                                                ("creature_classic_level", "entry"), ("npc_vendor", "entry")]),
                             ("gameobject_template", "gameobject", [("gameobject_questitem", "GameObjectEntry")])):
        richer = ("EXISTS (SELECT 1 FROM `{0}npc_vendor` v WHERE v.entry = r.k1)" if spawn == "creature" else
                  "EXISTS (SELECT 1 FROM `{0}gameobject_template` g JOIN `{0}gameobject_loot_template` l ON l.Entry = g.Data1 "
                  "WHERE g.entry = r.k1 AND g.type = 3)").format(STEP)
        cur.execute(f"SELECT r.k1 FROM `{STEP}{isql.IMPORT_ROWS}` r WHERE r.file = %s AND r.tbl = %s ORDER BY {richer} DESC, r.k1 LIMIT 1",
                    (imp, tbl))
        got = cur.fetchone()
        if not got:
            checks.add(f"slice 5: no {tbl} rows to simulate", True)
            continue
        entry = got[0]
        # the realm before our file ran: the fork's own template there, none of our rows or records for it
        cur.execute(f"SELECT guid FROM `{STEP}{spawn}` WHERE id = %s", (entry,))
        guids = [r[0] for r in cur.fetchall()]
        cur.execute(f"DELETE FROM `{STEP}{spawn}` WHERE id = %s", (entry,))
        for g in guids:
            cur.execute(f"DELETE FROM `{STEP}{isql.IMPORT_ROWS}` WHERE tbl = %s AND k1 = %s", (spawn, g))
        for dep, col in deps:
            cur.execute(f"DELETE FROM `{STEP}{dep}` WHERE `{col}` = %s", (entry,))
            cur.execute(f"DELETE FROM `{STEP}{isql.IMPORT_ROWS}` WHERE tbl = %s AND k1 = %s", (dep, entry))
        loot = None
        if tbl == "gameobject_template":
            cur.execute(f"SELECT Data1 FROM `{STEP}{tbl}` WHERE entry = %s AND type = 3 AND Data1 <> 0", (entry,))
            got = cur.fetchone()
            if got:
                loot = got[0]
                cur.execute(f"DELETE FROM `{STEP}gameobject_loot_template` WHERE Entry = %s", (loot,))
                cur.execute(f"DELETE FROM `{STEP}{isql.IMPORT_ROWS}` WHERE tbl = 'gameobject_loot_template' AND k1 = %s", (loot,))
        if spawn == "gameobject":          # the fork came first: nothing of ours recorded; else a takeover keeps our record
            cur.execute(f"DELETE FROM `{STEP}{isql.IMPORT_ROWS}` WHERE tbl = %s AND k1 = %s", (tbl, entry))
        cur.execute(f"UPDATE `{STEP}{tbl}` SET name = 'Fork copy', VerifiedBuild = 70900 WHERE entry = %s", (entry,))
        conn.commit()
        run_file(cur, conn, ours[imp].decode("utf-8"), mapping)
        left = []
        for t, col, v in [(spawn, "id", entry)] + [(d, c, entry) for d, c in deps] + ([("gameobject_loot_template", "Entry", loot)] if loot else []):
            cur.execute(f"SELECT COUNT(*) FROM `{STEP}{t}` WHERE `{col}` = %s", (v,))
            if cur.fetchone()[0]:
                left.append(t)
        cur.execute(f"SELECT name FROM `{STEP}{tbl}` WHERE entry = %s", (entry,))
        name = cur.fetchone()[0]
        how = "added" if spawn == "gameobject" else "took over"
        checks.add(f"where the fork {how} {tbl} {entry} first, a run of our file adds nothing next to it and leaves it",
                   not left and name == "Fork copy", f"added: {left}; name {name!r}")


SIMULATIONS = {"slice1": simulate_slice1, "slice2": simulate_slice2, "slice3": simulate_slice3, "slice4": simulate_slice4,
               "slice5": simulate_slice5}


def report_md(r, manifests):
    out = [f"# Everlake world import: dry run of {', '.join(r['slices'])}", "",
           f"Made {r['made']} by tools/forever-data/import_dryrun.py against the fork world {r['world']}, with every "
           f"file of every slice. Result: **{'every check passes' if r['ok'] else 'a check FAILED'}**.", "",
           "## Files", ""]
    out += [f"- `{f['name']}` ({f['kind']}, SHA1 {f['sha1'][:12]})" for f in r["files"]]
    out += ["", "## What the files do", "", "| Slice | | Rows |", "|---|---|---|"]
    for m in manifests:
        s = m["slice"]
        out += [f"| {s} | add `{t}` | {len(v)} |" for t, v in sorted(m["adds"].items())]
        rel = [f for f in m["fixes"] if f["kind"] == "relations"]
        if rel:
            out.append(f"| {s} | corrections: other givers or enders | {len(rel)} quests: {sum(len(f['add']) for f in rel)} rows added, "
                       f"{sum(len(f['delete']) for f in rel)} fork rows removed |")
        upd = collections.Counter(f["table"] for f in m["fixes"] if f["kind"] == "update")
        out += [f"| {s} | corrections: `{t}` rows changed | {n} |" for t, n in sorted(upd.items())]
        basis = collections.Counter(r.get("basis") for rs in m["adds"].values() for r in rs if r.get("basis"))
        out += [f"| {s} | ... of them with their chance from {b} | {n} |" for b, n in sorted(basis.items())]
        out += [f"| {s} | review list (not in the files) | {len(m['review'])} |", f"| {s} | held back | {len(m['held_back'])} |"]
    out.append("")
    for m in manifests:
        if "objective_flags" in m:
            out += [f"{m['slice']} objective rows: " + (f"written with Flags,Flags2 = {m['objective_flags']}" if m["objective_flags"]
                                                        else "none written: no public source records their Flags (see held back)") + ".", ""]
        if "classic_only" in m:
            out += [f"{m['slice']}: drops only Classic data shows (forever-db's drop rows, which are pfQuest/VMaNGOS and CMaNGOS) are "
                    + ("added with their Classic chance; each such row's note in `everlake_import_rows` and the file's comment says "
                       "`classic forever-db N% (pfQuest/CMaNGOS)`, so a later Forever recording can replace it"
                       if m["classic_only"] == "add" else "held back")
                    + f". EG Link's chance needs {m['min_kills']} recorded kills; rows with an EG Link chance say `eg-link drops/kills`.", ""]
    out += ["## Runs", ""]
    out.append(f"- Stepped (the fork world as deployed, then all our files): {r['timings_s'].get('stepped', '?')} s.")
    out.append("- From scratch (the world release, then every fork file and ours in name order): "
               + (f"{r['timings_s'].get('scratch', '?')} s." if r["scratch_run"] else "skipped (--skip-scratch)."))
    out += ["", "## Checks", ""]
    out += [f"- {'pass' if c['ok'] else '**FAIL**'}: {c['check']}" + (f" ({c['detail']})" if c["detail"] and not c["ok"] else "")
            for c in r["checks"]]
    out += ["", "Tables changed against the fork world (keys): " +
            ", ".join(f"`{t}` +{v['added']} -{v['removed']} ~{v['changed']}" for t, v in sorted(r["tables_changed"].items())), ""]
    out += ["## Gap report, before and after", "", "Loot, trainer-spell and vendor-item gaps count items of an NPC (npc and item); the rest count quests or NPCs.", "",
            "| Gap | Before | After | Closed | Left: review | Left: held back | Left: kept |", "|---|---|---|---|---|---|---|"]
    for cat in r["categories"]:
        left = r["left"].get(cat, {})
        out.append(f"| {cat} | {r['gaps_before'].get(cat, 0)} | {r['gaps_after'].get(cat, 0)} | {r['closed'].get(cat, 0)} | "
                   f"{left.get('review', 0)} | {left.get('held back', 0)} | {left.get('kept', 0)} |")
    others = [c for c in r["gaps_before"] if c not in r["categories"] and r["gaps_before"][c] != r["gaps_after"].get(c)]
    out += ["", "Other categories: " + ("unchanged." if not others else "changed: " + ", ".join(
        f"{c} {r['gaps_before'][c]} -> {r['gaps_after'].get(c)}" for c in others)), ""]
    for m in manifests:
        held = collections.Counter(h.get("reason") or h["why"] for h in m["held_back"])
        out += [f"## {m['slice']}: held back, by reason", "", f"Full list: slices/{m['slice']}/held-back.md.", ""]
        out += [f"- {n} x {why}" for why, n in held.most_common()]
        out += ["", f"## {m['slice']}: review list", "", f"Full list: slices/{m['slice']}/review.md.", ""]
        review = collections.Counter(i["category"] for i in m["review"])
        out += [f"- {cat}: {n}" for cat, n in sorted(review.items())] + [""]
    return "\n".join(out).rstrip() + "\n"


if __name__ == "__main__":
    main()
