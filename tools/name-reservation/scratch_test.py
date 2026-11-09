#!/usr/bin/env python3
"""Name reservation scenario on a scratch stack: two realms sharing one login database.

    tools/name-reservation/scratch_test.py              build nothing, start the scratch stack, run, leave it up
    tools/name-reservation/scratch_test.py --down       also remove the stack and its volume afterwards

The stack is tools/name-reservation/scratch/compose.yml (project everlake-names-test): its own MySQL volume and
network, nothing published on the host, so it runs beside the live stack. It needs an image with the patch, tagged
everlake-trinitycore:names-test (NAMES_TEST_IMAGE), and the extracted game data (DATA_DIR, read only).

There is no game client here, so characters are made the ways the console can: `.pdump load` (a dump onto an
account, which goes through the same reservation as character create) and `.character rename` (a GM rename). The
character create/rename opcode handlers call the same NameReservationMgr functions; they are checked in game.

Scenario (NameReservation.GracePeriod = 60 s here, NAMES_TEST_GRACE):
  1. account A takes "Ora" on realm 1
  2. account B is refused "Ora" on realm 2 (dump load gets a temporary name; GM rename is refused)
  3. account A can use "Ora" on realm 2
  4. deleting A's characters frees the name only when the last one goes; B is refused during the grace period, A may
     take it back, B gets it after the grace period
  5. both realms claim the same five names at the same moment: each name ends with exactly one account
  6. bots (when the image has PlayerbotV2): a bot can't be created with a player's name, bot names reserve nothing,
     a player's claim renames an offline bot holding the name, an online one keeps it until the next start, when
     the boot rename runs
  7. back-fill: a clash between two accounts is reported and left alone, a single owner is reserved
"""
import argparse
import os
import pty
import re
import select
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
COMPOSE = ["docker", "compose", "-p", "everlake-names-test", "-f", os.path.join(HERE, "scratch", "compose.yml")]
GRACE = int(os.environ.get("NAMES_TEST_GRACE", "60"))
REALM1, REALM2 = 70, 71
# pdump takes bare file names (PlayerDump.DisallowPaths = 1): they land in the worldserver's working directory
DUMP_DIR = "/opt/trinitycore/bin"

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))
    return ok


def compose(*args, **kw):
    return subprocess.run(COMPOSE + list(args), cwd=REPO, capture_output=True, text=True, **kw)


def sql(query):
    out = compose("exec", "-T", "mysql", "mysql", "-uroot", "-pnames-test-root", "-N", "-B", "-e", query)
    lines = [l for l in out.stdout.splitlines() if l and not l.startswith("mysql: [Warning]")]
    if "ERROR" in out.stderr:
        raise RuntimeError(f"{out.stderr.strip()}\n  query: {query}")
    return [[None if v == "NULL" else v for v in l.split("\t")] for l in lines]


def one(query):
    rows = sql(query)
    return rows[0][0] if rows else None


def read_for(fd, seconds):
    out, end = b"", time.time() + seconds
    while time.time() < end:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
    return out.decode(errors="replace")


def console(service, *commands, wait=3.0):
    """Types commands on a worldserver console (docker attach) and returns everything printed meanwhile."""
    container = compose("ps", "-q", service).stdout.strip()
    if not container:
        raise RuntimeError(f"{service} is not running")
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("docker", ["docker", "attach", "--sig-proxy=false", container])
    read_for(fd, 1.0)
    reply = ""
    for command in commands:
        os.write(fd, command.encode() + b"\r")
        reply += read_for(fd, wait)
    os.write(fd, b"\x10\x11")  # Ctrl+P Ctrl+Q: detach
    read_for(fd, 0.5)
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    return reply.replace("\r", "")


def wait_ready(service, timeout, since=None):
    """since: only log lines after this time (a restart keeps the old "ready" line in the log)"""
    end = time.time() + timeout
    while time.time() < end:
        logs = compose("logs", "--no-color", *(["--since", since] if since else []), service).stdout
        if re.search(r"\(worldserver-daemon\) ready", logs):
            return True
        if re.search(r"Exited|exited with code", compose("ps", "-a", service).stdout):
            print(logs[-3000:])
            return False
        time.sleep(5)
    return False


def reservation(name, surname=""):
    """(owner bnet id, freed?, number of characters using it) or None, for the full name (dump loads have no surname)"""
    row = sql(f"SELECT r.battlenet_account, r.freed_at IS NOT NULL, (SELECT COUNT(*) FROM auth.name_reservation_character c "
              f"WHERE c.name = r.name AND c.surname = r.surname) FROM auth.name_reservation r "
              f"WHERE r.name = '{name}' AND r.surname = '{surname}'")
    return (int(row[0][0]), row[0][1] == "1", int(row[0][2])) if row else None


def char(db, name):
    """(guid, account) of the character with this name on a realm, or None"""
    row = sql(f"SELECT guid, account FROM {db}.characters WHERE name = '{name}'")
    return (int(row[0][0]), int(row[0][1])) if row else None


def load(service, account, name):
    return console(service, f"pdump load tmpl.dump {account} {name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--down", action="store_true", help="remove the scratch stack and its volume at the end")
    ap.parse_args()  # --down is read in __main__, so it also runs after a failure

    print("== starting the scratch stack (first start imports the world database: several minutes)")
    compose("up", "-d", "mysql", check=True)
    compose("up", "-d", "worldserver", check=True)
    if not wait_ready("worldserver", 1800):
        sys.exit("realm 1 did not start")
    compose("up", "-d", "worldserver2", check=True)
    if not wait_ready("worldserver2", 900):
        sys.exit("realm 2 did not start")

    print("== tables (applied by the core's updater from sql/custom/auth)")
    check("auth has both name reservation tables",
          one("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = 'auth' AND TABLE_NAME LIKE 'name_reservation%'") == "2")
    sql("DELETE FROM auth.name_reservation_character; DELETE FROM auth.name_reservation;")

    print("== accounts and a template character")
    accounts = {}
    for key in ("a", "b", "t"):
        email = f"{key}@names.test".upper()
        if not one(f"SELECT id FROM auth.battlenet_accounts WHERE email = '{email}'"):
            console("worldserver", f"bnetaccount create {key}@names.test NamesTest1")
        row = sql(f"SELECT b.id, a.id, a.username FROM auth.battlenet_accounts b JOIN auth.account a ON a.battlenet_account = b.id "
                  f"WHERE b.email = '{email}'")
        accounts[key] = {"bnet": int(row[0][0]), "game": int(row[0][1]), "name": row[0][2]}
    A, B, T = accounts["a"], accounts["b"], accounts["t"]
    print(f"  A = Battle.net {A['bnet']} ({A['name']}), B = {B['bnet']} ({B['name']}), template owner T = {T['bnet']}")

    for db in ("characters", "characters2"):
        sql(f"DELETE FROM {db}.characters WHERE account IN ({A['game']}, {B['game']}) OR name = 'Tmpl'")
    sql(f"INSERT INTO characters.characters (guid, account, name, race, class, gender, level, taximask) "
        f"VALUES (990001, {T['game']}, 'Tmpl', 1, 1, 0, 1, '')")
    # the core finds characters by name or guid in its character cache, filled at start: restart realm 1 to load Tmpl
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    compose("restart", "worldserver", check=True)
    if not wait_ready("worldserver", 900, since):
        sys.exit("realm 1 did not come back after the restart")
    reply = console("worldserver", "pdump write tmpl.dump Tmpl")
    if "tmpl.dump" not in subprocess.run(["docker", "exec", compose("ps", "-q", "worldserver").stdout.strip(), "ls", DUMP_DIR],
                                         capture_output=True, text=True).stdout:
        sys.exit(f"pdump write did not write {DUMP_DIR}/tmpl.dump: {reply.strip()[-500:]}")
    # the realm 1 dump, copied to realm 2's container
    src = compose("ps", "-q", "worldserver").stdout.strip()
    dst = compose("ps", "-q", "worldserver2").stdout.strip()
    subprocess.run(["docker", "cp", f"{src}:{DUMP_DIR}/tmpl.dump", "/tmp/everlake-names-test.dump"], check=True, capture_output=True)
    subprocess.run(["docker", "cp", "/tmp/everlake-names-test.dump", f"{dst}:{DUMP_DIR}/tmpl.dump"], check=True, capture_output=True)
    os.remove("/tmp/everlake-names-test.dump")
    check("template dump written", "tmpl.dump" in subprocess.run(["docker", "exec", dst, "ls", DUMP_DIR], capture_output=True, text=True).stdout)

    print("== 1. A takes Ora on realm 1")
    load("worldserver", A["name"], "Ora")
    c = char("characters", "Ora")
    check("realm 1 has Ora on A's account", c and c[1] == A["game"], c)
    check("Ora reserved for A, 1 character, in use", reservation("Ora") == (A["bnet"], False, 1), reservation("Ora"))

    print("== 2. B is refused Ora on realm 2")
    reply = load("worldserver2", B["name"], "Ora")
    check("realm 2 has no Ora", char("characters2", "Ora") is None, reply)
    btemp = one(f"SELECT name FROM characters2.characters WHERE account = {B['game']} AND at_login & 1")
    check("B's dump got a temporary name with a forced rename", btemp and btemp != "Ora", btemp)
    reply = console("worldserver2", f"character rename {btemp} Ora")
    check("GM rename of B's character to Ora is refused", char("characters2", "Ora") is None and "Ora" in reply, reply.strip()[-200:])
    check("reservation unchanged (A, in use, 1 character)", reservation("Ora") == (A["bnet"], False, 1), reservation("Ora"))

    print("== 3. A can use Ora on realm 2")
    load("worldserver2", A["name"], "Ora")
    c = char("characters2", "Ora")
    check("realm 2 has Ora on A's account", c and c[1] == A["game"], c)
    check("Ora: A, in use, 2 characters", reservation("Ora") == (A["bnet"], False, 2), reservation("Ora"))

    print("== 4. delete and the grace period")
    console("worldserver", "character erase Ora")
    check("realm 1 Ora erased", char("characters", "Ora") is None)
    time.sleep(1)
    check("still in use by the realm 2 character (A, 1 character)", reservation("Ora") == (A["bnet"], False, 1), reservation("Ora"))
    console("worldserver2", "character erase Ora")
    time.sleep(1)
    check("last character gone: freed, still A's", reservation("Ora") == (A["bnet"], True, 0), reservation("Ora"))
    freed_at = int(one("SELECT UNIX_TIMESTAMP(freed_at) FROM auth.name_reservation WHERE name = 'Ora'"))
    console("worldserver2", f"character rename {btemp} Ora")
    check("B refused during the grace period", char("characters2", "Ora") is None, reservation("Ora"))
    # the owner takes a freed name back at once
    load("worldserver", A["name"], "Lyra")
    console("worldserver", "character erase Lyra")
    time.sleep(1)
    check("Lyra freed", reservation("Lyra") == (A["bnet"], True, 0), reservation("Lyra"))
    load("worldserver2", A["name"], "Lyra")
    check("A takes Lyra back within the grace period", (char("characters2", "Lyra") or (0, 0))[1] == A["game"]
          and reservation("Lyra") == (A["bnet"], False, 1), reservation("Lyra"))
    wait = freed_at + GRACE + 2 - int(one("SELECT UNIX_TIMESTAMP()"))
    print(f"  waiting {max(wait, 0)} s for the {GRACE} s grace period")
    time.sleep(max(wait, 0))
    console("worldserver2", f"character rename {btemp} Ora")
    c = char("characters2", "Ora")
    check("after the grace period B gets Ora on realm 2", c and c[1] == B["game"], c)
    check("Ora now B's, in use, 1 character", reservation("Ora") == (B["bnet"], False, 1), reservation("Ora"))

    print("== 5. both realms claim the same names at once")
    names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
    threads = [threading.Thread(target=lambda s=s, acc=acc: console(s, *[f"pdump load tmpl.dump {acc} {n}" for n in names], wait=1.5))
               for s, acc in (("worldserver", A["name"]), ("worldserver2", B["name"]))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    time.sleep(1)
    for n in names:
        r = reservation(n)
        c1, c2 = char("characters", n), char("characters2", n)
        winners = {acc for acc in ((c1 or (0, 0))[1], (c2 or (0, 0))[1]) if acc}
        owner_game = A["game"] if r and r[0] == A["bnet"] else B["game"] if r and r[0] == B["bnet"] else None
        check(f"{n}: one owner, only its character has the name", r and r[2] == 1 and winners == {owner_game}, (r, c1, c2))

    print("== 6. bots")
    # PlayerbotV2 keeps its pool accounts in characters.playerbot_v2_account; the core without bots has no such table
    has_bots = one("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = 'characters' "
                   "AND TABLE_NAME = 'playerbot_v2_account'") == "1"
    if not has_bots:
        print("  image has no PlayerbotV2: skipped")
    else:
        reply = console("worldserver", "playerbot create Lyra human warrior 0", wait=5)
        check("a bot can't be created with A's name Lyra", char("characters", "Lyra") is None, reply.strip()[-200:])
        console("worldserver", "playerbot create Mira human warrior 1", wait=5)
        bot = char("characters", "Mira")
        check("bot Mira created on realm 1", bot is not None)
        check("a bot's name reserves nothing", reservation("Mira") is None, reservation("Mira"))
        if bot:
            online = one(f"SELECT online FROM characters.characters WHERE guid = {bot[0]}")
            load("worldserver", A["name"], "Mira")
            c = char("characters", "Mira")
            if online == "0":
                check("A's claim renamed the offline bot and A has Mira", c and c[1] == A["game"], c)
                check("the bot kept its character under a new name",
                      one(f"SELECT name FROM characters.characters WHERE guid = {bot[0]}") not in (None, "Mira"))
            else:
                check("bot online: it keeps Mira for now, A got a temporary name", c and c[1] == bot[1], c)

        # an offline bot gives the name up at once
        console("worldserver", "playerbot create Nova human warrior 1", wait=5)
        nova = char("characters", "Nova")
        check("bot Nova created on realm 1", nova is not None)
        if nova:
            console("worldserver", "playerbot logout Nova", wait=5)
            for _ in range(30):
                if one(f"SELECT online FROM characters.characters WHERE guid = {nova[0]}") == "0":
                    break
                time.sleep(1)
            time.sleep(3)  # the session goes away a moment after the save
            load("worldserver", A["name"], "Nova")
            c = char("characters", "Nova")
            check("A's claim renamed the offline bot Nova and A has Nova", c and c[1] == A["game"], c)
            check("bot Nova kept its character under a new name",
                  one(f"SELECT name FROM characters.characters WHERE guid = {nova[0]}") not in (None, "", "Nova"))
            check("Nova reserved for A", reservation("Nova") == (A["bnet"], False, 1), reservation("Nova"))

        # a bot that still holds a reserved name when the realm starts is renamed at boot
        if bot and one(f"SELECT name FROM characters.characters WHERE guid = {bot[0]}") == "Mira":
            sql(f"INSERT INTO auth.name_reservation (name, battlenet_account) VALUES ('Mira', {B['bnet']})")
            since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            compose("restart", "worldserver", check=True)
            if not wait_ready("worldserver", 900, since):
                sys.exit("realm 1 did not come back after the restart")
            check("boot renamed the bot holding B's Mira",
                  one(f"SELECT name FROM characters.characters WHERE guid = {bot[0]}") not in (None, "", "Mira"))

    print("== 7. back-fill")
    sql(f"INSERT INTO characters.characters (guid, account, name, race, class, gender, level, taximask) VALUES "
        f"(990101, {A['game']}, 'Oldtimer', 1, 1, 0, 10, ''), (990102, {A['game']}, 'Solo', 1, 1, 0, 10, '')")
    sql(f"INSERT INTO characters2.characters (guid, account, name, race, class, gender, level, taximask) VALUES "
        f"(990103, {B['game']}, 'Oldtimer', 1, 1, 0, 20, ''), (990104, {A['game']}, 'Solo', 1, 1, 0, 5, '')")
    backfill = [sys.executable, os.path.join(HERE, "backfill.py"), "--compose",
                f"-p everlake-names-test -f {os.path.join(HERE, 'scratch', 'compose.yml')}",
                "--realm", f"{REALM1}=characters", "--realm", f"{REALM2}=characters2"]
    dry = subprocess.run(backfill, cwd=REPO, capture_output=True, text=True)
    print("  " + dry.stdout.replace("\n", "\n  ").rstrip())
    check("report only: clash listed, exit 2", dry.returncode == 2 and "Oldtimer" in dry.stdout.split("CLASHES")[-1], dry.stderr)
    check("report only wrote nothing", reservation("Solo") is None)
    applied = subprocess.run(backfill + ["--apply"], cwd=REPO, capture_output=True, text=True)
    check("--apply: Solo reserved for A with both characters", reservation("Solo") == (A["bnet"], False, 2), (reservation("Solo"), applied.stdout[-300:], applied.stderr))
    check("--apply: the clash Oldtimer left alone", reservation("Oldtimer") is None, reservation("Oldtimer"))
    again = subprocess.run(backfill, cwd=REPO, capture_output=True, text=True)
    check("second run: nothing more to reserve", "to reserve: 0" in again.stdout, again.stdout)
    sql("DELETE FROM characters.characters WHERE guid IN (990101, 990102); DELETE FROM characters2.characters WHERE guid IN (990103, 990104)")

    print("== check queries")
    with open(os.path.join(REPO, "sql", "everlake", "checks", "auth_name_reservation.sql")) as f:
        out = compose("exec", "-T", "mysql", "mysql", "-uroot", "-pnames-test-root", "auth", input=f.read())
    check("check queries run", out.returncode == 0 and "ERROR" not in out.stderr, out.stderr)

    passed = sum(ok for _, ok in results)
    print(f"\n{passed} of {len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    down = "--down" in sys.argv
    try:
        sys.exit(main())
    finally:
        if down:  # also after a failure, so the next run starts from a new volume
            for service in ("worldserver", "worldserver2"):
                print(f"--- last {service} log lines")
                print(compose("logs", "--no-color", "--tail", "40", service).stdout)
            compose("down", "-v")
