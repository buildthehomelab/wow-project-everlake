#!/usr/bin/env python3
"""Loads the pinned DatabaseForever world (EmuForever's own database) into acore_forever as dbf_<table> tables.

    load_dbf.py              load the pinned copy if it changed since the last load
    load_dbf.py --force      load it again (--sources DIR: default $FOREVER_SOURCES or data/forever-sources)

DatabaseForever is the world database of EmuForever, a separate Forever server emulator. It started from the same fork
world as tc_*, cut down to Forever's content, with rows of its own added: about 4,400 Forever NPCs (1,400 of them
spawned, 15,700 spawns), loot, vendors and trainers. Its added spawns sit on a grid of map coordinates (0.1% steps, like
map pins), all facing 0 with a 120 s respawn, so they are placed from map pins, not recorded in the game.

Tables keep their own layout under a dbf_ prefix. It is TrinityCore's, but older in places: creature_template still
holds lootid and the levels, and there is no creature_template_difficulty. Each pinned file
is one table (DROP, CREATE, INSERT). Everything is loaded as dbf_<table>__new and swapped in with one RENAME, so a
failed run leaves the old copy. The repository states no licence: it is a reference to compare with, and its rows are
not copied into anything published. Connection as load_sources.py.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from load_sources import SOURCES, connect, files_digest  # noqa: E402
from load_tc import IDENT, statements  # noqa: E402

NAME = "databaseforever"
PREFIX = "dbf_"


def load(conn, cur, folder, files):
    """Run every pinned table file into dbf_<table>__new. Returns {table: insert statements}."""
    counts = {}
    for rel in sorted(files):
        expected = os.path.basename(rel)[:-4]
        with open(os.path.join(folder, rel), "rb") as handle:
            for table, sql in statements(handle):
                if table != expected:
                    raise SystemExit(f"{rel} writes table {table}, not {expected}; the old dbf_ tables are untouched")
                sql = IDENT.sub(lambda m: f"{m.group(1)} `{PREFIX}{m.group(2)}__new`", sql, count=1)
                cur.execute(sql)
                if sql.startswith("INSERT"):
                    counts[table] = counts.get(table, 0) + 1
                elif sql.startswith("CREATE"):
                    counts.setdefault(table, 0)
        conn.commit()
        if expected not in counts:
            raise SystemExit(f"{rel} holds no CREATE TABLE for {expected}; the old dbf_ tables are untouched")
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sources", default=SOURCES)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    with open(os.path.join(args.sources, "manifest.json")) as handle:
        pin = json.load(handle)["current"].get(NAME)
    if not pin:
        raise SystemExit(f"{NAME} is not pinned yet: pin_sources.py --only {NAME}")
    files = [p for p in pin["files"] if p.endswith(".sql")]
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() "
                    "AND table_name = 'src_pins' AND column_name = 'files_digest'")
        if not cur.fetchone()[0]:
            raise SystemExit("src_pins is missing or old: run load_sources.py once first")
        cur.execute("SELECT label, files_digest FROM src_pins WHERE source = %s", (NAME,))
        row = cur.fetchone()
    # the same commit with another set of kept files (a changed keep rule) is a new pin too
    if row and tuple(row) == (pin["label"], files_digest(pin)) and not args.force:
        print(f"{NAME}: already loaded at {pin['label'][:10]}")
        return
    started = time.time()
    with conn.cursor() as cur:
        cur.execute("SET SESSION foreign_key_checks = 0, unique_checks = 0")
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() "
                    "AND (table_name LIKE 'dbf\\_%\\_\\_new' OR table_name LIKE 'dbf\\_%\\_\\_old')")
        for (stale,) in cur.fetchall():
            cur.execute(f"DROP TABLE IF EXISTS `{stale}`")
        counts = load(conn, cur, os.path.join(args.sources, pin["folder"]), files)
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name LIKE 'dbf\\_%'")
        existing = {r[0] for r in cur.fetchall()}
        renames = []
        for table in sorted(counts):
            final = PREFIX + table
            if final in existing:
                renames.append(f"`{final}` TO `{final}__old`")
            renames.append(f"`{final}__new` TO `{final}`")
        # a table the new pin no longer has goes too, so dbf_* is exactly one pin
        dropped = sorted(t for t in existing if not t.endswith(("__new", "__old")) and t[len(PREFIX):] not in counts)
        cur.execute("RENAME TABLE " + ", ".join(renames))
        for table in sorted(counts):
            cur.execute(f"DROP TABLE IF EXISTS `{PREFIX}{table}__old`")
        for table in dropped:
            cur.execute(f"DROP TABLE IF EXISTS `{table}`")
        cur.execute("""REPLACE INTO src_pins (source, label, folder, licence, loaded_at, row_count, tables_json, files_digest)
                       VALUES (%s, %s, %s, %s, UTC_TIMESTAMP(), %s, %s, %s)""",
                    (NAME, pin["label"], pin["folder"], pin.get("licence"), len(counts),
                     json.dumps({"tables": sorted(counts), "dropped": dropped}), files_digest(pin)))
        conn.commit()
    print(f"{NAME}: {len(counts)} tables as {PREFIX}*, {time.time() - started:.0f} s ({pin['label'][:10]})")


if __name__ == "__main__":
    main()
