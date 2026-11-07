#!/usr/bin/env python3
"""Switches on retail UI files that Forever's client ships but excludes (Test 1, docs/era-data.md).

Blizzard_UnitFrame.toc (FileDataID 8286112) serves every game flavour. Forever's flavour is "camelot", and the lines
for the Death Knight rune frame and the Monk Chi bar say [ExcludeLoadGameType camelot]. This script takes the
original toc (from the pinned build, so Blizzard's file is never kept in this repo) and drops that exclusion for the
listed files. The result goes into a patched build with tools/tact/patch.py as 8286112=<output>.

    python3 tools/tact/tact.py --cache ~/retail-cache-wowf 8286112 -o /tmp/unitframe.orig
    python3 tools/era/ui_unlock.py /tmp/unitframe.orig /tmp/blizzard_unitframe.toc
"""
import sys

UNLOCK = [b"[Family]\\RuneFrame.", b"[Family]\\MonkHarmonyBar."]
EXCLUDE = b" [ExcludeLoadGameType camelot]"


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src = open(sys.argv[1], "rb").read()
    lines = src.split(b"\r\n")
    changed = 0
    for i, line in enumerate(lines):
        if any(line.startswith(u) for u in UNLOCK) and EXCLUDE in line:
            lines[i] = line.replace(EXCLUDE, b"")
            changed += 1
    if changed != 4:
        raise SystemExit("expected 4 lines to change, found %d: has the toc changed?" % changed)
    open(sys.argv[2], "wb").write(b"\r\n".join(lines))
    print("%d lines switched on for camelot" % changed)


if __name__ == "__main__":
    main()
