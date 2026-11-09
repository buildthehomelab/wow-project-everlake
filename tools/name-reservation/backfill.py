#!/usr/bin/env python3
"""Reserves the full names of characters that existed before name reservation, on every realm.

The core (buildthehomelab/wow-trinitycore-everlake, NameReservationMgr) reserves a full name (name + surname, the surname
compared without regard to case or accents) when a character is created or renamed. Characters made before it have no
reservation, so another account could take their full names on another realm. This tool reads every realm's characters
and writes the missing rows to the login database:

    tools/name-reservation/backfill.py                          report only (default): what it would write, and clashes
    tools/name-reservation/backfill.py --apply                  write the rows that have one clear owner
    tools/name-reservation/backfill.py --realm 70=characters --realm 71=characters2

A CLASH is a full name used by characters of more than one Battle.net account (on different realms), or by a character
whose account does not own the full name's existing reservation. Two accounts may both have a "Bob" with different
surnames: that is no clash. Clashes are listed and left alone: nothing picks a
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
MySQL's root user, so it needs Docker access (often sudo). --compose "-p NAME -f FILE" selects another compose
project: a TrueNAS app named everlake is project ix-everlake (sudo python3 tools/name-reservation/backfill.py
--compose "-p ix-everlake"); the scratch test stack is its own. A failed connection stops the tool with mysql's error.
"""
import argparse
import os
import shlex
import subprocess
import unicodedata
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOT_EMAIL_SUFFIX = "@PLAYERBOT-V2.LOCAL"


class MySQL:
    def __init__(self, compose_args):
        # mysql's own exit status comes back (not the password-warning filter's), so a failed connection is an error
        # and never an empty result
        self.base = ["docker", "compose"] + shlex.split(compose_args) + [
            "exec", "-T", "mysql", "sh", "-c",
            'out=$(mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 -N -B "$@" 2>&1); rc=$?; '
            'printf "%s\\n" "$out" | grep -v "Using a password"; exit $rc', "sh"]

    def _fail(self, out, what):
        msg = (out.stdout.strip() + " " + out.stderr.strip()).strip() or f"exit status {out.returncode}"
        sys.exit(f"mysql failed{what}: {msg}\n"
                 "  (MySQL is reached with `docker compose exec mysql` from this folder: run the tool with sudo, and on "
                 "TrueNAS pass the app's project, e.g. --compose \"-p ix-everlake\")")

    def rows(self, sql):
        out = subprocess.run(self.base + ["-e", sql], cwd=HERE, capture_output=True, text=True)
        if out.returncode != 0 or out.stdout.startswith("ERROR"):
            self._fail(out, f" (query: {sql})")
        result = []
        for line in out.stdout.splitlines():
            if not line:
                continue
            if line.startswith("ERROR"):
                self._fail(out, f" (query: {sql})")
            result.append([None if v == "NULL" else v for v in line.split("\t")])
        return result

    def run_script(self, sql):
        out = subprocess.run(self.base, input=sql, cwd=HERE, capture_output=True, text=True)
        if "ERROR" in out.stdout or out.returncode != 0:
            self._fail(out, " while writing")


def q(value):
    """SQL string literal (names are validated by the core; surnames may hold anything)."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def normalise(name):
    """The core's normalizePlayerName: trimmed, first letter upper case, the rest lower case."""
    name = name.strip(" \t ​‌‍‎‏﻿")
    return name[:1].upper() + name[1:].lower()


def surname_key(surname):
    """Surnames compare like their utf8mb4_unicode_ci column: without regard to case or accents, outer blanks trimmed."""
    surname = surname.strip(" \t ​‌‍‎‏﻿")
    folded = unicodedata.normalize("NFKD", surname.casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def full_name(name, surname):
    return f"{name} {surname}" if surname else name


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
        sys.exit(f"{auth}.name_reservation is missing: start a worldserver on the fork's core first (its updater applies sql/custom/auth/2026_11_07_09 and 2026_11_09_00)")

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
    # a reservation is for a full name (name + surname): several characters may share a name
    users = defaultdict(list)       # (name, surname key) -> [(realm, guid, bnet, account, surname, level)]
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
            users[(normalise(name), surname_key(surname))].append((realm_id, int(guid), int(bnet), int(account), surname, int(level)))

    # needs the full-name key (core sql/custom/auth/2026_11_09_00_auth_name_reservation_full_name.sql)
    if not db.rows(f"SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = {q(auth)} AND TABLE_NAME = 'name_reservation_character' AND COLUMN_NAME = 'surname'"):
        sys.exit(f"{auth}.name_reservation_character has no surname: start a worldserver on the new core first (its updater "
                 "applies 2026_11_09_00_auth_name_reservation_full_name.sql)")
    existing = {(name, surname_key(surname)): (int(owner), freed, surname) for name, surname, owner, freed in
                db.rows(f"SELECT name, surname, battlenet_account, freed_at FROM {auth}.name_reservation")}
    attached = {(int(r), int(g)): (n, surname_key(sn)) for r, g, n, sn in
                db.rows(f"SELECT realm_id, character_guid, name, surname FROM {auth}.name_reservation_character")}

    writes, clashes, reserved, kept = [], [], 0, 0
    for key, chars in sorted(users.items()):
        name = key[0]
        owners = {c[2] for c in chars}
        row = existing.get(key)
        if row:
            owners.add(row[0])
        if len(owners) > 1:
            clashes.append((key, chars, row))
            continue
        owner = owners.pop()
        missing = [c for c in chars if attached.get((c[0], c[1])) != key]
        if row and not missing and row[1] is None:
            kept += 1
            continue
        realm_id, guid, _, _, surname, _ = chars[0]
        # an existing row keeps the surname as first written (the same full name, perhaps in other capitals)
        surname = row[2] if row else surname
        writes.append(f"INSERT INTO {auth}.name_reservation (name, surname, battlenet_account, realm_id, character_guid) "
                      f"VALUES ({q(name)}, {q(surname)}, {owner}, {realm_id}, {guid}) "
                      f"ON DUPLICATE KEY UPDATE freed_at = IF(battlenet_account = {owner}, NULL, freed_at);")
        for realm_id, guid, *_ in missing:
            writes.append(f"REPLACE INTO {auth}.name_reservation_character (realm_id, character_guid, name, surname) "
                          f"VALUES ({realm_id}, {guid}, {q(name)}, {q(surname)});")
        reserved += 1

    # character rows whose character is gone from its realm (only for realms this run read)
    live = {(c[0], c[1]) for chars in users.values() for c in chars}
    gone = [(r, g, k) for (r, g), k in attached.items() if r in realms and (r, g) not in live]
    for realm_id, guid, _ in gone:
        writes.append(f"DELETE FROM {auth}.name_reservation_character WHERE realm_id = {realm_id} AND character_guid = {guid};")
    # full names nobody uses that were never freed (unfinished creates, and the full names of the gone characters above);
    # the surname comparison in SQL ignores case like the key does
    gone_keys = {k for _, _, k in gone}
    in_use = set(users)
    stale = [k for k, (_, freed, _) in existing.items() if freed is None and k not in in_use]
    for key in sorted(set(stale) | gone_keys):
        stored_surname = existing[key][2] if key in existing else key[1]
        writes.append(f"UPDATE {auth}.name_reservation r SET r.freed_at = NOW() WHERE r.name = {q(key[0])} AND r.surname = {q(stored_surname)} "
                      f"AND r.freed_at IS NULL AND NOT EXISTS (SELECT 1 FROM {auth}.name_reservation_character c "
                      f"WHERE c.name = r.name AND c.surname = r.surname);")

    print(f"realms read: {', '.join(f'{r} ({s})' for r, s in sorted(realms.items()))}")
    print(f"player full names: {len(users)}; already reserved: {kept}; to reserve: {reserved}; clashes: {len(clashes)}")
    print(f"character rows of characters that are gone: {len(gone)}; never-freed names with no character: {len(stale)}")
    for line in skipped:
        print(f"  skipped: {line}")
    if clashes:
        print("\nCLASHES (left alone; rename all but one by hand, then run again):")
        for key, chars, row in clashes:
            print(f"  {full_name(key[0], chars[0][4])}" + (f"  (reserved by Battle.net account {row[0]}{', freed ' + str(row[1]) if row[1] else ''})" if row else ""))
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
