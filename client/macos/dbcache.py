#!/usr/bin/env python3
"""Lists what the client keeps of the server's hotfixes in its DBCache.bin (read only).

    dbcache.py <DBCache.bin> [push id range ...]      (range: 9550000-9569999; default: our pushes 9530000-9569999)

Prints the file's version and build, how many rows each push holds, and every row of the given ranges with its
table hash, record id, status and the text inside it (a SpellName row shows the spell's name). Used by
everlake-client.sh switch (docs/era-data.md, gate 5 tests 4-6) to see whether the client keeps one cache for all
realms, and which realm's text it holds for a record both realms send.

Entry layouts differ between client versions (with or without a region field), so the layout is taken from the
first entry: the one whose size lands exactly on the next entry's magic.
"""
import collections
import re
import struct
import sys

MAGIC = b"XFTH"
HEADER = 4 + 4 + 4 + 32  # magic, version, build, verification hash
LAYOUTS = {
    # name: (int32 fields after the magic, counting the status byte + 3 pad as one, plus one spare; field indexes)
    # newer clients: region, push, unique id, table hash, record id, size, status (32-byte entry header)
    "region": (8, dict(region=0, push=1, unique=2, table=3, record=4, size=5)),
    # older clients: push, unique id, table hash, record id, size, status (28-byte entry header)
    "plain": (7, dict(push=0, unique=1, table=2, record=3, size=4)),
}
TABLES = {1187407512: "SpellName", 3776013982: "Spell", 666345498: "SpellXSpellVisual"}


def entries(buf, version):
    pos = HEADER
    layout = None
    while pos + 4 <= len(buf):
        if buf[pos:pos + 4] != MAGIC:
            yield ("error", f"no entry magic at offset {pos} (of {len(buf)})")
            return
        if layout is None:
            for name, (n, idx) in LAYOUTS.items():
                for head in (4 + 4 * n, 4 + 4 * (n - 1)):
                    try:
                        size = struct.unpack_from("<i", buf, pos + 4 + 4 * idx["size"])[0]
                    except struct.error:
                        continue
                    end = pos + head + size
                    if 0 <= size < 10_000_000 and (end == len(buf) or buf[end:end + 4] == MAGIC):
                        layout = (name, head, idx)
                        break
                if layout:
                    break
            if layout is None:
                yield ("error", "unknown entry layout")
                return
            yield ("layout", f"entry layout '{layout[0]}', {layout[1]} header bytes")
        name, head, idx = layout
        fields = struct.unpack_from("<" + "i" * ((head - 4) // 4), buf, pos + 4)
        size = fields[idx["size"]]
        status = buf[pos + 4 + 4 * (idx["size"] + 1)]
        data = buf[pos + head:pos + head + size]
        row = {k: fields[i] & 0xFFFFFFFF if k in ("unique", "table") else fields[i] for k, i in idx.items()}
        row["status"] = status
        row["data"] = data
        yield ("row", row)
        pos += head + size


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    buf = open(sys.argv[1], "rb").read()
    ranges = [tuple(map(int, r.split("-"))) for r in sys.argv[2:]] or [(9530000, 9569999)]
    if buf[:4] != MAGIC:
        sys.exit(f"not a DBCache.bin (magic {buf[:4]!r})")
    version, build = struct.unpack_from("<ii", buf, 4)
    print(f"DBCache.bin: {len(buf)} bytes, version {version}, build {build}")
    per_push = collections.Counter()
    listed = []
    total = 0
    for kind, item in entries(buf, version):
        if kind != "row":
            print(f"  {item}")
            continue
        total += 1
        push = item["push"]
        if any(lo <= push <= hi for lo, hi in ranges):
            per_push[push] += 1
            if 9550000 <= push <= 9569999:
                listed.append(item)
    print(f"  {total} rows in all; rows per push in {', '.join(f'{lo}-{hi}' for lo, hi in ranges)}:")
    for push in sorted(per_push):
        print(f"    push {push}: {per_push[push]} rows")
    if not per_push:
        print("    (none)")
    print("  marker rows (pushes 9550000-9569999):")
    for r in listed:
        text = " | ".join(t.decode("utf-8", "replace") for t in re.findall(rb"[\x20-\x7e]{4,}", r["data"]))
        print(f"    push {r['push']} unique {r['unique']} table {TABLES.get(r['table'], r['table'])} record "
              f"{r['record']} status {r['status']} region {r.get('region', '-')}: '{text}'")
    if not listed:
        print("    (none)")


if __name__ == "__main__":
    main()
