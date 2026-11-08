#!/usr/bin/env python3
"""Writes the hotfixes SQL that gives Everlake every TACT key live WoW Forever sends and the core lacks.

    python3 -I tact_keys.py --cache DBCache.bin --core-repo ~/Code/Wow/wow-trinitycore-everlake --core-ref <TC_COMMIT> \
        --push 9590000 --out sql/everlake/<date>_NN_hotfixes_live_tact_keys.sql

A TACT key unlocks client data Blizzard ships encrypted (records and files of newer content). The client only reads that
data once a server has sent the key as a TactKey hotfix, so a key the core lacks leaves those records unreadable.

The keys come from live Forever's hotfix cache (see dbcache.py for the public mirror). The core's keys are every
`tact_key` row in any SQL file of --core-ref (a superset of what its hotfixes database holds). The output has:
  - keys live sends that the core has no row for, and
  - keys whose bytes differ from live (live wins; listed in the file's header).
Each goes in as a tact_key row plus a hotfix_data row in push --push, so clients get it. Re-runnable.
"""
import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbcache  # noqa: E402

TACT_ROWS = re.compile(r"(?:INSERT|REPLACE)\s+INTO\s+`?tact_key`?[^;]*?VALUES(.*?);", re.S | re.I)
ROW = re.compile(r"\(\s*(\d+)\s*,((?:\s*\d+\s*,){16})\s*-?\d+\s*\)")


def core_keys_from_sql(texts):
    """{key id: 16 bytes} from the tact_key rows in these SQL texts; a later file wins, as when they are applied."""
    keys = {}
    for text in texts:
        for block in TACT_ROWS.finditer(text):
            for m in ROW.finditer(block.group(1)):
                values = [int(x) for x in m.group(2).split(",") if x.strip()]
                keys[int(m.group(1))] = bytes(values)
    return keys


def core_sql_texts(repo, ref):
    def git(*args):
        return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True,
                              errors="replace").stdout
    paths = sorted(p for p in git("grep", "-l", "-i", "tact_key", ref, "--", "sql").split() if p.endswith(".sql"))
    # git grep prints <ref>:<path>
    return [git("show", p) for p in paths]


def live_keys(records):
    """{key id: 16 bytes} for every valid TactKey record live sends."""
    out = {}
    for rid, r in dbcache.latest(records, dbcache.TABLE_TACT_KEY).items():
        if r.status == dbcache.STATUS_VALID and len(r.data) == 16:
            out[rid] = r.data
    return out


def plan(live, core):
    missing = sorted(k for k in live if k not in core)
    differ = sorted(k for k in live if k in core and core[k] != live[k])
    return missing, differ


def render(live, missing, differ, push, build, cache_name, core_ref):
    ids = missing + differ
    if not ids:
        return None
    if len(ids) > 99:
        raise ValueError(f"{len(ids)} keys: UniqueId is push * 100 + n, so one push holds 99; split it over two pushes")
    keys = ",".join(str(i) for i in ids)
    lines = [
        f"-- Every TACT key live WoW Forever sends that the core ({core_ref[:10]}) lacks or holds with other bytes:",
        f"-- {len(missing)} missing, {len(differ)} different. A key unlocks client data Blizzard ships encrypted; the client",
        "-- reads that data only after a server sends the key as a TactKey hotfix.",
        f"-- Source: live Forever hotfix cache {cache_name}, build {build} (public mirror, see",
        "-- tools/live-hotfixes/dbcache.py). Made with tools/live-hotfixes/tact_keys.py. Re-runnable.",
        f"-- Hotfix push {push}.",
    ]
    if differ:
        lines.append("-- Different from the core (live wins): " + ", ".join(map(str, differ)) + ".")
    lines += [
        f"-- Undo: DELETE FROM `hotfix_data` WHERE `Id` = {push}; and the tact_key rows below (the core's own come back",
        "-- when its files are applied again).",
        "",
        f"DELETE FROM `tact_key` WHERE `ID` IN ({keys});",
        "INSERT INTO `tact_key` (`ID`,`Key1`,`Key2`,`Key3`,`Key4`,`Key5`,`Key6`,`Key7`,`Key8`,`Key9`,`Key10`,`Key11`,"
        "`Key12`,`Key13`,`Key14`,`Key15`,`Key16`,`VerifiedBuild`) VALUES",
        ",\n".join(f"({i},{','.join(str(b) for b in live[i])},{build})" for i in ids) + ";",
        "",
        f"DELETE FROM `hotfix_data` WHERE `Id` = {push};",
        "INSERT INTO `hotfix_data` (`Id`,`UniqueId`,`TableHash`,`RecordId`,`Status`,`VerifiedBuild`) VALUES",
        ",\n".join(f"({push},{push * 100 + n},{dbcache.TABLE_TACT_KEY},{i},1,{build})"
                   for n, i in enumerate(ids, 1)) + ";",
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", required=True, help="DBCache.bin of live Forever")
    ap.add_argument("--core-repo", required=True, help="a clone of the core (TrinityCore fork)")
    ap.add_argument("--core-ref", required=True, help="the commit Everlake builds (Dockerfile TC_COMMIT)")
    ap.add_argument("--push", type=int, required=True, help="hotfix push id for these rows")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.push * 100 + 99 > 0xFFFFFFFF:
        sys.exit("--push too large for the UniqueId scheme (push * 100 + n)")
    build, records = dbcache.read(a.cache)
    live = live_keys(records)
    core = core_keys_from_sql(core_sql_texts(a.core_repo, a.core_ref))
    missing, differ = plan(live, core)
    print(f"live build {build}: {len(live)} keys; core {a.core_ref[:10]}: {len(core)} keys; "
          f"{len(missing)} missing, {len(differ)} different")
    if differ:
        print("different:", " ".join(map(str, differ)))
    sql = render(live, missing, differ, a.push, build, os.path.basename(a.cache), a.core_ref)
    if sql is None:
        print("nothing to write: the core has every live key")
        return
    with open(a.out, "w") as f:
        f.write(sql)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
