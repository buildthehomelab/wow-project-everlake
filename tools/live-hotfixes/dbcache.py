#!/usr/bin/env python3
"""Reads DBCache.bin, the hotfix cache a WoW client writes (and Blizzard's live Forever copy that is mirrored publicly).

    python3 -I dbcache.py DBCache.bin            summary: build, records, records per table
    python3 -I dbcache.py DBCache.bin --table 0xDF2F53CF [--record N]   one table's records as JSON lines

The public mirror of live Forever's cache, refreshed daily (wowsims/forever, MIT, builds its data from it):
    https://storage.googleapis.com/raidbots-static/wow/forever/enUS/DBCache.bin

Layout (XFTH version 9, https://wowdev.wiki/DBCache.bin), all little-endian:
    header  'XFTH', u32 version, u32 build, 32 bytes hash                         = 44 bytes
    entry   'XFTH', i32 region, i32 push id, u32 unique id, u32 table hash, i32 record id, i32 size,
            u8 status, 3 bytes padding, <size> bytes of record data                = 32 bytes + data
Status: 1 valid, 2 removed, 3 invalid, 4 not public. Push id -1 marks records the client gets with every connection
(the TACT keys, for example).
"""
import argparse
import json
import struct
import sys
from collections import Counter, namedtuple

MAGIC = b"XFTH"
VERSION = 9
HEADER_SIZE = 44
ENTRY_HEAD = struct.Struct("<4siiIIiiB3x")   # 32 bytes

Record = namedtuple("Record", "region push unique table record status data")

TABLE_TACT_KEY = 0xDF2F53CF                  # TactKey.db2: 16 key bytes per record
STATUS_VALID = 1


class CacheError(ValueError):
    pass


def parse(blob):
    """(build, [Record]) in file order. Raises CacheError on anything that isn't a whole XFTH v9 cache."""
    if len(blob) < HEADER_SIZE or blob[:4] != MAGIC:
        raise CacheError("not a hotfix cache (no XFTH header)")
    version, build = struct.unpack_from("<II", blob, 4)
    if version != VERSION:
        raise CacheError(f"XFTH version {version}, this reader knows {VERSION}")
    records, pos = [], HEADER_SIZE
    while pos < len(blob):
        if pos + ENTRY_HEAD.size > len(blob):
            raise CacheError(f"entry header cut off at byte {pos}")
        magic, region, push, unique, table, record, size, status = ENTRY_HEAD.unpack_from(blob, pos)
        if magic != MAGIC:
            raise CacheError(f"entry at byte {pos} has no XFTH mark")
        if size < 0 or pos + ENTRY_HEAD.size + size > len(blob):
            raise CacheError(f"entry at byte {pos} says {size} bytes, past the end of the file")
        start = pos + ENTRY_HEAD.size
        records.append(Record(region, push, unique, table, record, status, blob[start:start + size]))
        pos = start + size
    return build, records


def read(path):
    with open(path, "rb") as f:
        return parse(f.read())


def latest(records, table):
    """{record id: Record} for one table, the newest push winning (push -1 counts as oldest)."""
    out = {}
    for r in records:
        if r.table != table:
            continue
        old = out.get(r.record)
        if old is None or r.push >= old.push:
            out[r.record] = r
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cache")
    ap.add_argument("--table", type=lambda s: int(s, 0), help="table hash, e.g. 0xDF2F53CF")
    ap.add_argument("--record", type=int)
    a = ap.parse_args()
    build, records = read(a.cache)
    if a.table is None:
        print(f"build {build}, {len(records)} records")
        for table, n in Counter(r.table for r in records).most_common():
            print(f"  0x{table:08X} {n}")
        return
    for r in records:
        if r.table == a.table and (a.record is None or r.record == a.record):
            print(json.dumps({"record": r.record, "push": r.push, "unique": r.unique, "status": r.status,
                              "region": r.region, "data": r.data.hex()}))


if __name__ == "__main__":
    try:
        main()
    except CacheError as e:
        sys.exit(f"{sys.argv[1]}: {e}")
