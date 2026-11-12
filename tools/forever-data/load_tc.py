#!/usr/bin/env python3
"""Loads the TrinityCore `forever` branch's full world database into acore_forever as tc_<table> tables.

    load_tc.py                          load the pinned release (tc-release) if it changed since the last load
    load_tc.py --force                  load it again (--sources DIR: default $FOREVER_SOURCES or data/forever-sources)

The release is a mysqldump of the whole TrinityCore world (TrinityCore's own schema, the world Everlake starts from). Tables keep their
TrinityCore layout under a tc_ prefix. Locale tables and armory_
tables (the fork's website) are left out; the updates table is kept as tc_updates, the list of update files the
release already holds, so the fork's later sql/custom files can be told apart. Connection as load_sources.py.

Then the fork's sql/updates and sql/custom world files (pinned as tc-forever) are run on top, in name order, by the same
rules as the fork's own updater at worldserver start (custom_sql.UpdatePlan: new files applied, changed files applied
again except world baselines, later custom files applied again after one is), so tc_* is the world Everlake runs. Their table names are pointed at
the new tables statement by statement (custom_sql.py); a name the rewrite misses fails loudly, because no unprefixed
tables exist here. Each applied file is added to tc_updates. A file that fails stops the run.

Tables are loaded as tc_<table>__new and swapped in together with one RENAME, so a failed run leaves the old world.
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import custom_sql  # noqa: E402
from load_sources import SOURCES, connect  # noqa: E402

SKIP = re.compile(r"(_locale$|^armory_|^updates_include$)")   # updates kept: which sql/custom files the release holds
IDENT = re.compile(r"^(DROP TABLE IF EXISTS|CREATE TABLE|INSERT INTO) `(\w+)`")


def statements(stream):
    """mysqldump output -> (table, sql) for DROP/CREATE/INSERT of each table, other lines dropped."""
    buf, table = [], None
    for raw in stream:
        line = raw.decode("utf-8")
        if not buf:
            m = IDENT.match(line)
            if not m:
                continue
            table = m.group(2)
        buf.append(line)
        if line.rstrip().endswith(";"):
            sql = "".join(buf)
            buf = []
            yield table, sql


def load_release(conn, cur, archive, target):
    """Run the release's world dump into tables named target(table). Returns ({table: insert statements}, skipped tables)."""
    listing = subprocess.run(["7zz", "l", "-ba", archive], check=True, capture_output=True, text=True).stdout
    world = next(line.split()[-1] for line in listing.splitlines() if "_world_" in line and line.endswith(".sql"))
    proc = subprocess.Popen(["7zz", "e", "-so", archive, world], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    counts, skipped = {}, set()
    for table, sql in statements(proc.stdout):
        if SKIP.search(table):
            skipped.add(table)
            continue
        sql = IDENT.sub(lambda m: f"{m.group(1)} `{target(m.group(2))}`", sql, count=1)
        cur.execute(sql)
        if sql.startswith("INSERT"):
            counts[table] = counts.get(table, 0) + 1
            if sum(counts.values()) % 200 == 0:
                conn.commit()
        elif sql.startswith("CREATE"):
            counts.setdefault(table, 0)
    conn.commit()
    if proc.wait() != 0:
        raise SystemExit("7zz failed reading " + world + "; the old tables are untouched")
    return counts, skipped


def read_update_files(sources, custom_pin):
    """({file name: bytes}, {file name: path}) of the fork's sql/updates/world and sql/custom/world files."""
    raw, paths = {}, {}
    for sub in ("updates", "custom"):
        root = os.path.join(sources, custom_pin["folder"], "sql", sub, "world")
        for dirpath, _, names in os.walk(root):
            for f in names:
                if f.endswith(".sql"):
                    if f in raw:            # the fork's updater stops on this too
                        raise SystemExit(f"update file {f} is in two update folders; the old tables are untouched")
                    with open(os.path.join(dirpath, f), "rb") as handle:
                        raw[f] = handle.read()
                    paths[f] = os.path.relpath(os.path.join(dirpath, f), os.path.join(sources, custom_pin["folder"]))
    return raw, paths


def apply_update_files(conn, cur, raw, paths, mapping, skipped_tables, held, state):
    """Apply update files as the fork's updater does (custom_sql.UpdatePlan), every table name pointed through `mapping`
    (which must hold "updates", the list the updater keeps). Statements on tables in `skipped_tables` only (locale,
    website) are left out. A file that fails or names a table outside `mapping` stops the run (SystemExit) with nothing
    of that file committed. Returns what happened to each file."""
    texts = {f: b.decode("utf-8") for f, b in raw.items()}
    updates = mapping["updates"]
    plan, applied = custom_sql.UpdatePlan(held, raw), []
    for name in sorted(raw):
        mode, why = plan.step(name, paths[name], raw[name])
        normalized = custom_sql.file_hashes(raw[name])[0]
        if mode == "skip":
            continue
        if mode == "rename":
            cur.execute(f"UPDATE `{updates}` SET name = %s WHERE name = %s", (name, why))
            applied.append({"file": name, "mode": "renamed from " + why})
            continue
        if mode == "rehash":
            cur.execute(f"UPDATE `{updates}` SET hash = %s WHERE name = %s", (normalized, name))
            applied.append({"file": name, "mode": "rehashed" + (f" ({why})" if why else "")})
            continue
        done, dropped = 0, 0
        for statement in custom_sql.statements(texts[name]):
            sql, uses_skipped, problems = custom_sql.retarget(statement, mapping, skipped_tables)
            if custom_sql.drops_missing_only(statement, problems, mapping):
                dropped += 1            # DROP TABLE IF EXISTS of tables this world never had: a no-op
                continue
            if problems:
                conn.rollback()
                raise SystemExit(f"update file {name}: {', '.join(sorted(problems))} not allowed here (only the world's own "
                                 f"tables); nothing run, the old tables are untouched.\n{statement[:400]}")
            if uses_skipped:
                if custom_sql.insert_target(statement) not in skipped_tables and any(f"`{v}`" in sql for v in mapping.values()):
                    conn.rollback()     # it would also change a loaded table: leaving it out would lose that
                    raise SystemExit(f"update file {name} joins a table that isn't loaded (locale) with one that is; "
                                     f"the old tables are untouched.\n{statement[:400]}")
                dropped += 1            # only locale or website tables, which are not loaded here
                continue
            source = custom_sql.prepared_source(sql)
            if source is not None:      # PREPARE x FROM @v: check the statement it would run, now that it is known
                if re.fullmatch(r"@\w+", source.strip()):
                    cur.execute(f"SELECT {source.strip()}")
                elif re.fullmatch(r"'(?:[^'\\]|\\.|'')*'", source.strip(), re.S):
                    cur.execute("SELECT " + source.strip())
                else:
                    conn.rollback()
                    raise SystemExit(f"update file {name}: PREPARE from something other than a variable or a string; "
                                     f"the old tables are untouched.\n{statement[:400]}")
                value = cur.fetchone()[0]
                value = value.decode("utf-8", "replace") if isinstance(value, (bytes, bytearray)) else value
                bad = custom_sql.check_prepared(value, set(mapping.values()))
                if bad:
                    conn.rollback()
                    raise SystemExit(f"update file {name} prepares a statement that is not allowed ({', '.join(sorted(bad))}); "
                                     f"the old tables are untouched.\n{str(value)[:400]}")
            try:
                cur.execute(sql)
            except Exception as error:  # noqa: BLE001 - stop: the world must equal Everlake's or not change
                conn.rollback()
                raise SystemExit(f"update file {name} failed ({error}); the old tables are untouched.\n{sql[:400]}")
            done += 1
        conn.commit()
        plan.applied(name, paths[name])
        cur.execute(f"INSERT INTO `{updates}` (name, hash, state, timestamp, speed) VALUES (%s, %s, %s, UTC_TIMESTAMP(), 0) "
                    "ON DUPLICATE KEY UPDATE hash = VALUES(hash)", (name, normalized, held.get(name, ("", state))[1]))
        applied.append({"file": name, "mode": "applied" + (f" ({why})" if why else ""), "statements": done, "left_out": dropped})
    conn.commit()
    return applied


def updates_state(cur, updates):
    """The state new update rows get: CUSTOM where the updates table knows it, else RELEASED (older dumps)."""
    cur.execute("SELECT column_type FROM information_schema.columns WHERE table_schema = DATABASE() "
                "AND table_name = %s AND column_name = 'state'", (updates,))
    return "CUSTOM" if "'CUSTOM'" in (cur.fetchone() or ("",))[0] else "RELEASED"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sources", default=SOURCES)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    with open(os.path.join(args.sources, "manifest.json")) as handle:
        current = json.load(handle)["current"]
    pin, custom_pin = current["tc-release"], current.get("tc-forever")
    has_updates = bool(custom_pin) and any(os.path.isdir(os.path.join(args.sources, custom_pin["folder"], "sql", sub, "world"))
                                           for sub in ("updates", "custom"))
    custom_pin = custom_pin if has_updates else None
    label = pin["label"] + ("+updates@" + custom_pin["label"][:10] if custom_pin else "")
    folder = os.path.join(args.sources, pin["folder"])
    archive = next(os.path.join(folder, f) for f in pin["files"] if f.endswith(".7z"))
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT label FROM src_pins WHERE source = 'tc-release'")
        row = cur.fetchone()
    if row and row[0] == label and not args.force:
        print(f"tc-release: already loaded at {label}")
        return
    started = time.time()
    with conn.cursor() as cur:
        cur.execute("SET SESSION foreign_key_checks = 0, unique_checks = 0")
        # a failed run leaves its half-built tables behind: start clean (the live tc_* tables are never touched here)
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() "
                    "AND (table_name LIKE 'tc\\_%\\_\\_new' OR table_name LIKE 'tc\\_%\\_\\_old')")
        for (stale,) in cur.fetchall():
            cur.execute(f"DROP TABLE IF EXISTS `{stale}`")
        counts, skipped = load_release(conn, cur, archive, lambda t: f"tc_{t}__new")
        dump_tables = set(counts)
        applied = []
        if custom_pin:
            state = updates_state(cur, "tc_updates__new")
            cur.execute("SELECT name, hash, state FROM `tc_updates__new`")
            held = {r[0]: (r[1] or "", r[2]) for r in cur.fetchall()}
            # the fork's updater (custom_sql.UpdatePlan): every file of sql/updates/world and sql/custom/world, in name order
            raw, paths = read_update_files(args.sources, custom_pin)
            created = {t: tmp for t, tmp in custom_sql.created_tables(b.decode("utf-8") for b in raw.values()).items()
                       if not SKIP.search(t)}
            mapping = {t: f"tc_{t}__new" for t in set(counts) | {t for t, temporary in created.items() if not temporary}}
            mapping.update({t: f"tc_{t}__tmp" for t, temporary in created.items() if temporary})
            skipped_tables = {t for t in skipped if t != "updates_include"}
            applied = apply_update_files(conn, cur, raw, paths, mapping, skipped_tables, held, state)
            for t, temporary in created.items():
                if not temporary and t not in counts:
                    counts[t] = 0       # a table the custom files make joins the swap
            conn.commit()
        # every table at once: readers see either the old TrinityCore world or the new one, never half of each
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name LIKE 'tc\\_%'")
        existing = {r[0] for r in cur.fetchall()}
        # the tables the new world has: the dump's plus those the update files made, less those they dropped again. A
        # table of the release itself must still be there, else the swap would mix the old one with the new world.
        release_tables = set(dump_tables)
        gone = sorted(t for t in release_tables if f"tc_{t}__new" not in existing)
        if gone:
            raise SystemExit(f"the update files dropped or renamed release tables ({', '.join(gone)}); the old tc_ tables are untouched")
        counts = {t: n for t, n in counts.items() if f"tc_{t}__new" in existing}
        renames = []
        for table in sorted(counts):
            final = f"tc_{table}"
            if final in existing:
                cur.execute(f"DROP TABLE IF EXISTS `{final}__old`")
                renames += [f"`{final}` TO `{final}__old`"]
            renames += [f"`{final}__new` TO `{final}`"]
        cur.execute("RENAME TABLE " + ", ".join(renames))
        for table in sorted(counts):
            cur.execute(f"DROP TABLE IF EXISTS `tc_{table}__old`")
        cur.execute("""REPLACE INTO src_pins (source, label, folder, licence, loaded_at, row_count, tables_json)
                       VALUES ('tc-release', %s, %s, %s, UTC_TIMESTAMP(), %s, %s)""",
                    (label, pin["folder"], pin.get("licence"), len(counts),
                     json.dumps({"tables": sorted(counts), "skipped": sorted(skipped), "custom_applied": applied})))
        conn.commit()
    kinds = collections.Counter(a["mode"].split(" (")[0] for a in applied)
    print(f"tc-release: {len(counts)} tables as tc_*, {len(skipped)} skipped; update files: "
          + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) +
          f" ({sum(a.get('left_out', 0) for a in applied)} statements on unloaded tables left out), {time.time() - started:.0f} s ({label})")
    for a in applied:
        print(f"  {a['file']}: {a['mode']}")


if __name__ == "__main__":
    main()
