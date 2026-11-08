#!/usr/bin/env python3
"""Reserves the names of characters that existed before name reservation, on every realm.

The core patch (docker/patches/0008-everlake-name-reservation.patch) reserves a name when a character is created or
renamed. Characters made before it have no reservation, so another account could take their names on another realm.
This tool reads every realm's characters and writes the missing rows to the login database:

    tools/name-reservation/backfill.py                          report only (default): what it would write, and clashes
    tools/name-reservation/backfill.py --apply                  write the rows that have one clear owner
    tools/name-reservation/backfill.py --realm 70=characters --realm 71=characters2

A CLASH is a name used by characters of more than one Battle.net account (on different realms), or by a character
whose account does not own the name's existing reservation. Clashes are listed and left alone: nothing picks a
winner. Resolve them by hand (a forced rename: `.character rename <name>` on the realm of the character that gives
the name up), then run the tool again.

--apply also tidies up what the core cannot see:
  - a reserved name with no character that was never freed (a create that never finished): freed now
  - a character row in name_reservation_character whose character is gone from its realm (deleted outside the
    core, e.g. by SQL): removed, and the name freed if nothing else uses it
Run it with the worldservers stopped or idle (no character creation while it runs); it is safe to run again.

Bots are skipped: characters of Battle.net accounts named *@PLAYERBOT-V2.LOCAL or of accounts listed in a realm's
playerbot_v2_account table. Bots never reserve names.

Reaching MySQL: by default `docker compose exec -T mysql` from the repo root (like scripts/realm2-setup.sh), as
MySQL's root user. --compose "-p NAME -f FILE" selects another compose project (the scratch test stack).
"""
import argparse
import os
import shlex
import subprocess
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOT_EMAIL_SUFFIX = "@PLAYERBOT-V2.LOCAL"


class MySQL:
    def __init__(self, compose_args):
        self.base = ["docker", "compose"] + shlex.split(compose_args) + [
            "exec", "-T", "mysql", "sh", "-c",
            'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 -N -B "$@" 2>&1 '
            '| grep -v "Using a password"', "sh"]

    def rows(self, sql):
        out = subprocess.run(self.base + ["-e", sql], cwd=HERE, capture_output=True, text=True)
        text = out.stdout
        if out.returncode not in (0, 1) or text.startswith("ERROR"):
            sys.exit(f"mysql failed: {text.strip() or out.stderr.strip()}\n  query: {sql}")
        result = []
        for line in text.splitlines():
            if line.startswith("ERROR"):
                sys.exit(f"mysql failed: {line}\n  query: {sql}")
            result.append([None if v == "NULL" else v for v in line.split("\t")])
        return result

    def run_script(self, sql):
        out = subprocess.run(self.base, input=sql, cwd=HERE, capture_output=True, text=True)
        if "ERROR" in out.stdout or out.returncode not in (0, 1):
            sys.exit(f"mysql failed while writing: {out.stdout.strip()} {out.stderr.strip()}")


def q(value):
    """SQL string literal (names are validated by the core; surnames may hold anything)."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def normalise(name):
    """The core's normalizePlayerName: trimmed, first letter upper case, the rest lower case."""
    name = name.strip(" \t ​‌‍‎‏﻿")
    return name[:1].upper() + name[1:].lower()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--realm", action="append", metavar="ID=DATABASE",
                    help="a realm (realmlist.id) and its characters database; repeat per realm "
                         "(default: 70=characters 71=characters2, those that exist)")
    ap.add_argument("--auth-db", default="auth")
    ap.add_argument("--compose", default="", help='extra "docker compose" arguments, e.g. "-p everlake-names -f x.yml"')
    ap.add_argument("--apply", action="store_true", help="write the reservations (default: report only)")
    args = ap.parse_args()

    db = MySQL(args.compose)
    auth = args.auth_db
    if not db.rows(f"SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = {q(auth)} AND TABLE_NAME = 'name_reservation'"):
        sys.exit(f"{auth}.name_reservation is missing: apply sql/everlake/2026_11_07_09_auth_name_reservation.sql first")

    realms = {}
    for spec in args.realm or ["70=characters", "71=characters2"]:
        realm_id, _, schema = spec.partition("=")
        if not db.rows(f"SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = {q(schema)}"):
            if args.realm:
                sys.exit(f"realm {realm_id}: database {schema} does not exist")
            continue
        realms[int(realm_id)] = schema
    if not realms:
        sys.exit("no realm databases found (use --realm ID=DATABASE)")

    # every player character with a name, on every realm
    users = defaultdict(list)       # name -> [(realm, guid, bnet, account, surname, level)]
    skipped = []
    for realm_id, schema in realms.items():
        has_pool = db.rows(f"SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = {q(schema)} AND TABLE_NAME = 'playerbot_v2_account'")
        pool = f"OR c.account IN (SELECT account_id FROM {schema}.playerbot_v2_account)" if has_pool else ""
        for guid, name, surname, account, bnet, level in db.rows(f"""
                SELECT c.guid, c.name, IFNULL(c.surname, ''), c.account, a.battlenet_account, c.level
                FROM {schema}.characters c
                LEFT JOIN {auth}.account a ON a.id = c.account
                LEFT JOIN {auth}.battlenet_accounts b ON b.id = a.battlenet_account
                WHERE c.name IS NOT NULL AND c.name <> '' AND c.account <> 0
                  AND NOT (IFNULL(b.email, '') LIKE '%{BOT_EMAIL_SUFFIX}' {pool})"""):
            if not bnet:
                skipped.append(f"realm {realm_id} character {name} (guid {guid}, account {account}): no Battle.net account")
                continue
            if any(ch.isdigit() for ch in name):
                skipped.append(f"realm {realm_id} character {name} (guid {guid}): temporary name, renamed at its next login")
                continue
            users[normalise(name)].append((realm_id, int(guid), int(bnet), int(account), surname, int(level)))

    existing = {name: (int(owner), freed) for name, owner, freed in
                db.rows(f"SELECT name, battlenet_account, freed_at FROM {auth}.name_reservation")}
    attached = {(int(r), int(g)): n for r, g, n in
                db.rows(f"SELECT realm_id, character_guid, name FROM {auth}.name_reservation_character")}

    writes, clashes, reserved, kept = [], [], 0, 0
    for name, chars in sorted(users.items()):
        owners = {c[2] for c in chars}
        row = existing.get(name)
        if row:
            owners.add(row[0])
        if len(owners) > 1:
            clashes.append((name, chars, row))
            continue
        owner = owners.pop()
        missing = [c for c in chars if attached.get((c[0], c[1])) != name]
        if row and not missing and row[1] is None:
            kept += 1
            continue
        realm_id, guid, _, _, surname, _ = chars[0]
        writes.append(f"INSERT INTO {auth}.name_reservation (name, surname, battlenet_account, realm_id, character_guid) "
                      f"VALUES ({q(name)}, {q(surname)}, {owner}, {realm_id}, {guid}) "
                      f"ON DUPLICATE KEY UPDATE freed_at = IF(battlenet_account = {owner}, NULL, freed_at);")
        for realm_id, guid, *_ in missing:
            writes.append(f"REPLACE INTO {auth}.name_reservation_character (realm_id, character_guid, name) "
                          f"VALUES ({realm_id}, {guid}, {q(name)});")
        reserved += 1

    # character rows whose character is gone from its realm (only for realms this run read)
    live = {(c[0], c[1]) for chars in users.values() for c in chars}
    gone = [(r, g, n) for (r, g), n in attached.items() if r in realms and (r, g) not in live]
    for realm_id, guid, name in gone:
        writes.append(f"DELETE FROM {auth}.name_reservation_character WHERE realm_id = {realm_id} AND character_guid = {guid};")
    # names nobody uses that were never freed (unfinished creates, and the names of the gone characters above)
    gone_names = {n for _, _, n in gone}
    in_use = set(users)
    stale = [n for n, (_, freed) in existing.items() if freed is None and n not in in_use]
    for name in sorted(set(stale) | gone_names):
        writes.append(f"UPDATE {auth}.name_reservation r SET r.freed_at = NOW() WHERE r.name = {q(name)} AND r.freed_at IS NULL "
                      f"AND NOT EXISTS (SELECT 1 FROM {auth}.name_reservation_character c WHERE c.name = r.name);")

    print(f"realms read: {', '.join(f'{r} ({s})' for r, s in sorted(realms.items()))}")
    print(f"player names: {len(users)}; already reserved: {kept}; to reserve: {reserved}; clashes: {len(clashes)}")
    print(f"character rows of characters that are gone: {len(gone)}; never-freed names with no character: {len(stale)}")
    for line in skipped:
        print(f"  skipped: {line}")
    if clashes:
        print("\nCLASHES (left alone; rename all but one by hand, then run again):")
        for name, chars, row in clashes:
            print(f"  {name}" + (f"  (reserved by Battle.net account {row[0]}{', freed ' + row[1] if row[1] else ''})" if row else ""))
            for realm_id, guid, bnet, account, surname, level in chars:
                print(f"    realm {realm_id}  guid {guid}  level {level}  Battle.net account {bnet} (game account {account})"
                      + (f"  surname {surname}" if surname else ""))

    if not args.apply:
        print(f"\nreport only: {len(writes)} statement(s) would be written; run with --apply to write them")
        return 2 if clashes else 0
    if writes:
        db.run_script("START TRANSACTION;\n" + "\n".join(writes) + "\nCOMMIT;\n")
    print(f"\nwritten: {len(writes)} statement(s)")
    return 2 if clashes else 0


if __name__ == "__main__":
    sys.exit(main())
