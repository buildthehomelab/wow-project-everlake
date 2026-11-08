#!/usr/bin/env python3
"""Loads the TrinityCore `forever` branch's full world database into acore_forever as tc_<table> tables.

    load_tc.py                          load the pinned release (tc-release) if it changed since the last load
    load_tc.py --force                  load it again (--sources DIR: default $FOREVER_SOURCES or data/forever-sources)

The release is a mysqldump of the whole TrinityCore world (TrinityCore's own schema, the world Everlake starts from). Tables keep their
TrinityCore layout under a tc_ prefix. Locale tables and armory_
tables (the fork's website) are left out; the updates table is kept as tc_updates, the list of update files the
release already holds, so the fork's later sql/custom files can be told apart. Connection as load_sources.py.

Tables are loaded as tc_<table>__new and swapped in together with one RENAME, so a failed run leaves the old world.

Not applied yet: the branch's sql/custom files dated after the release (pinned as tc-forever). They are plain SQL on
unprefixed table names, so applying them needs the same tc_ renaming, done statement by statement.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sources", default=SOURCES)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    with open(os.path.join(args.sources, "manifest.json")) as handle:
        pin = json.load(handle)["current"]["tc-release"]
    folder = os.path.join(args.sources, pin["folder"])
    archive = next(os.path.join(folder, f) for f in pin["files"] if f.endswith(".7z"))
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT label FROM src_pins WHERE source = 'tc-release'")
        row = cur.fetchone()
    if row and row[0] == pin["label"] and not args.force:
        print(f"tc-release: already loaded at {pin['label']}")
        return
    listing = subprocess.run(["7zz", "l", "-ba", archive], check=True, capture_output=True, text=True).stdout
    world = next(line.split()[-1] for line in listing.splitlines() if "_world_" in line and line.endswith(".sql"))
    proc = subprocess.Popen(["7zz", "e", "-so", archive, world], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    started, counts, skipped = time.time(), {}, set()
    with conn.cursor() as cur:
        cur.execute("SET SESSION foreign_key_checks = 0, unique_checks = 0")
        for table, sql in statements(proc.stdout):
            if SKIP.search(table):
                skipped.add(table)
                continue
            sql = IDENT.sub(lambda m: f"{m.group(1)} `tc_{m.group(2)}__new`", sql, count=1)
            cur.execute(sql)
            if sql.startswith("INSERT"):
                counts[table] = counts.get(table, 0) + 1
                if sum(counts.values()) % 200 == 0:
                    conn.commit()
            elif sql.startswith("CREATE"):
                counts.setdefault(table, 0)
        conn.commit()
        if proc.wait() != 0:
            raise SystemExit("7zz failed reading " + world + "; the old tc_ tables are untouched")
        # every table at once: readers see either the old TrinityCore world or the new one, never half of each
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name LIKE 'tc\\_%'")
        existing = {r[0] for r in cur.fetchall()}
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
                    (pin["label"], pin["folder"], pin.get("licence"), len(counts), json.dumps({"tables": sorted(counts), "skipped": sorted(skipped)})))
        conn.commit()
    print(f"tc-release: {len(counts)} tables as tc_*, {len(skipped)} skipped, {time.time() - started:.0f} s ({pin['label']})")


if __name__ == "__main__":
    main()
