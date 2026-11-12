#!/bin/bash
# The PTR's databases and realm row (docker-compose.ptr.yml). The live realms keep running.
# The PTR app runs "init" by itself before its worldserver starts (service ptr-init, MYSQL_HOST set: MySQL over the
# app network). By hand on the host it uses the running MySQL container instead (docker exec).
#
#   scripts/ptr-setup.sh init      dbs, realm, cards, then gms (what the PTR app runs on every start; safe to repeat)
#   scripts/ptr-setup.sh dbs       world_ptr and hotfixes_ptr as copies of realm 1's world and hotfixes, and the empty
#                                  characters_ptr and playerbot_ptr (worldserver fills them on the PTR's first start).
#                                  A database that exists is left as it is.
#   scripts/ptr-setup.sh refresh   world_ptr and hotfixes_ptr copied from realm 1 again (stop the PTR first): the PTR
#                                  then starts from live's world, and its own updates apply on top when it starts.
#   scripts/ptr-setup.sh realm     realm row 73 becomes "PTR": port 8097, content set 140 (the 4th ruleset card), GM
#                                  accounts only, address and build copied from realm 1. Undo: UPDATE auth.realmlist SET
#                                  name = 'Forever Hardcore', flag = 3, port = 8085, allowedSecurityLevel = 0 WHERE id = 73;
#   scripts/ptr-setup.sh cards     realm names match the ruleset cards (71 "Classic"; 72 "Retail", listed but offline: no
#                                  worldserver yet, so its card is greyed out) and the cards' names, text and order
#                                  (sql/everlake/2026_11_12_00_hotfixes_ruleset_cards.sql) go into every realm's hotfix
#                                  database. Realm 70's name is REALM_NAME in .env (bnetserver writes it on each start).
#                                  Each worldserver shows the new cards after its next restart.
#                                  Undo for realm 72: UPDATE auth.realmlist SET name = 'Forever RP', flag = 3,
#                                  contentSetId = 0, allowedSecurityLevel = 0 WHERE id = 72;
#   scripts/ptr-setup.sh gms       the game accounts of the Battle.net emails in PTR_GM_EMAILS (comma-separated, .env)
#                                  become GM level 3 on ALL realms (account_access RealmID -1). The PTR is GM only, and
#                                  the login server counts only rank stored for all realms when it hands out a ruleset
#                                  card's realm (LOGIN_SEL_BNET_ACCOUNT_INFO: aa.RealmID = -1): a GM of realm 70 alone
#                                  gets "no realms available" on the PTR's card. Empty PTR_GM_EMAILS: nothing changes.
#                                  Undo for one account: DELETE FROM auth.account_access WHERE AccountID = <id> AND RealmID = -1;
#   scripts/ptr-setup.sh status    the PTR's databases, its realm row, and the accounts that may enter it
#
# MYSQL_HOST + MYSQL_ROOT_PASSWORD: connect over the network (inside the PTR app).
# MYSQL_CONTAINER: otherwise, the MySQL container (default: the one of the compose project ix-everlake, else everlake).
# DB_USER: the TrinityCore user (default: DB_USER from .env, else trinity).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HERE/../.env"
if [ -z "${DB_USER:-}" ] && [ -f "$ENV_FILE" ]; then
    DB_USER="$(sed -nE 's/^DB_USER=(.*)$/\1/p' "$ENV_FILE" | tail -1)"
fi
DB_USER="${DB_USER:-trinity}"

DUMP_OPTS=(--single-transaction --skip-lock-tables --no-tablespaces --routines --triggers --set-gtid-purged=OFF)
if [ -n "${MYSQL_HOST:-}" ]; then
    : "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD must be set with MYSQL_HOST}"
    WHERE="MySQL at $MYSQL_HOST"
    root_sql() { MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -h"$MYSQL_HOST" -uroot "$@"; }
    root_dump() { MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -h"$MYSQL_HOST" -uroot "${DUMP_OPTS[@]}" "$1"; }
    ptr_running() { return 1; }   # inside the PTR app, init runs before its worldserver
else
    find_mysql() {
        local p c
        for p in ix-everlake everlake; do
            c="$(docker ps --filter "label=com.docker.compose.project=$p" --filter label=com.docker.compose.service=mysql --format '{{.Names}}' | head -1)"
            [ -n "$c" ] && { echo "$c"; return; }
        done
    }
    MYSQL_CONTAINER="${MYSQL_CONTAINER:-$(find_mysql)}"
    [ -n "$MYSQL_CONTAINER" ] || { echo "[ptr] ERROR: no running Everlake MySQL container (set MYSQL_CONTAINER)"; exit 1; }
    WHERE="MySQL container $MYSQL_CONTAINER"
    root_sql() { docker exec -i "$MYSQL_CONTAINER" sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$@" 2>&1 | { grep -v "Using a password" || true; }' sh "$@"; }
    root_dump() { docker exec "$MYSQL_CONTAINER" sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" "$@" "$0" 2>/dev/null' "$1" "${DUMP_OPTS[@]}"; }
    ptr_running() { docker ps --filter label=com.docker.compose.service=worldserver-ptr --format '{{.Names}}' | grep -q .; }
fi
db_exists() { root_sql -N -e "SHOW DATABASES LIKE '$1'" | grep -qx "$1"; }
create_db() {
    root_sql -e "CREATE DATABASE IF NOT EXISTS \`$1\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                 GRANT ALL PRIVILEGES ON \`$1\`.* TO '${DB_USER}'@'%'; FLUSH PRIVILEGES;"
}
copy_db() {  # copy_db <from> <to>: <to> must not exist
    create_db "$2"
    echo "[ptr] copying $1 into $2 (a few minutes)..."
    root_dump "$1" | root_sql "$2"
    echo "[ptr] $2: $(root_sql -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '$2'") tables"
}
echo "[ptr] $WHERE, TrinityCore user: $DB_USER"
case "${1:-}" in
    init)
        bash "$0" dbs
        bash "$0" realm
        bash "$0" cards
        bash "$0" gms
        ;;
    gms)
        IFS=',' read -r -a emails <<< "${PTR_GM_EMAILS:-}"
        for email in "${emails[@]}"; do
            email="$(echo "$email" | tr -d '[:space:]')"
            [ -n "$email" ] || continue
            if ! [[ "$email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]]; then
                echo "[ptr] PTR_GM_EMAILS: '$email' is not an email address: skipped"; continue
            fi
            found="$(root_sql -N -e "SELECT COUNT(*) FROM auth.account a JOIN auth.battlenet_accounts b ON b.id = a.battlenet_account WHERE b.email = '$email'")"
            if [ "$found" = 0 ]; then echo "[ptr] PTR_GM_EMAILS: no game account for $email: skipped"; continue; fi
            root_sql auth -e "INSERT INTO account_access (AccountID, SecurityLevel, RealmID, Comment)
                SELECT a.id, 3, -1, 'PTR_GM_EMAILS (scripts/ptr-setup.sh)' FROM account a
                JOIN battlenet_accounts b ON b.id = a.battlenet_account WHERE b.email = '$email'
                ON DUPLICATE KEY UPDATE SecurityLevel = GREATEST(SecurityLevel, 3);"
            echo "[ptr] $email: $found game account(s) are GM level 3 on all realms (the PTR included)"
        done
        ;;
    dbs)
        for pair in world:world_ptr hotfixes:hotfixes_ptr; do
            if db_exists "${pair#*:}"; then echo "[ptr] ${pair#*:} exists already: left as it is (refresh copies it again)"; continue; fi
            copy_db "${pair%%:*}" "${pair#*:}"
        done
        # worldserver fills an empty characters database itself; one with tables but no `updates` table is a first fill
        # that broke off, and every later start aborts on it ("database structure is not up to date"): start it again.
        # Only the PTR's own characters database, never a live one.
        if db_exists characters_ptr \
           && [ "$(root_sql -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'characters_ptr'")" != 0 ] \
           && [ "$(root_sql -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'characters_ptr' AND table_name = 'updates'")" = 0 ]; then
            echo "[ptr] characters_ptr has tables but no updates table (a first fill that broke off): emptied, worldserver fills it again"
            root_sql -e "DROP DATABASE characters_ptr;"
        fi
        for db in characters_ptr playerbot_ptr; do
            if db_exists "$db"; then echo "[ptr] $db exists already: left as it is"; continue; fi
            create_db "$db"; echo "[ptr] $db created (empty: the PTR's worldserver fills it on its first start)"
        done
        ;;
    refresh)
        ptr_running && { echo "[ptr] ERROR: the PTR's worldserver is running: stop the PTR app first"; exit 1; }
        for pair in world:world_ptr hotfixes:hotfixes_ptr; do
            root_sql -e "DROP DATABASE IF EXISTS \`${pair#*:}\`;"
            copy_db "${pair%%:*}" "${pair#*:}"
        done
        ;;
    realm)
        root_sql auth -e "UPDATE realmlist AS p JOIN realmlist AS r1 ON r1.id = 70
            SET p.name = 'PTR', p.address = r1.address, p.localAddress = r1.localAddress,
                p.localSubnetMask = r1.localSubnetMask, p.port = 8097, p.icon = r1.icon, p.flag = 2,
                p.timezone = r1.timezone, p.allowedSecurityLevel = 3, p.gamebuild = r1.gamebuild,
                p.Region = r1.Region, p.Battlegroup = r1.Battlegroup, p.contentSetId = 140
            WHERE p.id = 73;"
        bash "$0" status
        ;;
    cards)
        cards_sql="$HERE/../sql/everlake/2026_11_12_00_hotfixes_ruleset_cards.sql"
        [ -f "$cards_sql" ] || cards_sql="/ptr/sql/2026_11_12_00_hotfixes_ruleset_cards.sql"   # inside the PTR app
        [ -f "$cards_sql" ] || { echo "[ptr] ERROR: 2026_11_12_00_hotfixes_ruleset_cards.sql not found"; exit 1; }
        root_sql auth -e "UPDATE realmlist SET name = 'Classic' WHERE id = 71;
            UPDATE realmlist AS r JOIN realmlist AS r1 ON r1.id = 70
            SET r.name = 'Retail', r.address = r1.address, r.localAddress = r1.localAddress,
                r.localSubnetMask = r1.localSubnetMask, r.port = 8098, r.icon = r1.icon, r.flag = 2,
                r.timezone = r1.timezone, r.allowedSecurityLevel = 3, r.gamebuild = r1.gamebuild,
                r.Region = r1.Region, r.Battlegroup = r1.Battlegroup, r.contentSetId = 136
            WHERE r.id = 72;"
        for db in hotfixes hotfixes2 hotfixes_ptr; do
            if ! db_exists "$db"; then echo "[ptr] $db does not exist: no cards there"; continue; fi
            root_sql "$db" < "$cards_sql"
            echo "[ptr] $db: ruleset cards Forever, Classic, Retail, PTR (push 9580001)"
        done
        ;;
    status)
        root_sql -e "SELECT id, name, port, flag, allowedSecurityLevel, contentSetId, gamebuild FROM auth.realmlist WHERE id IN (70, 71, 72, 73);"
        root_sql -e "SELECT table_schema AS db, COUNT(*) AS tables FROM information_schema.tables
                     WHERE table_schema IN ('world_ptr', 'hotfixes_ptr', 'characters_ptr', 'playerbot_ptr') GROUP BY table_schema;"
        echo "[ptr] accounts that may enter the PTR (GM level 3 on all realms or on realm 73):"
        root_sql -e "SELECT a.id, a.username, aa.SecurityLevel, aa.RealmID FROM auth.account_access aa
                     JOIN auth.account a ON a.id = aa.AccountID WHERE aa.SecurityLevel >= 3 AND aa.RealmID IN (-1, 73);"
        ;;
    *)
        sed -n '2,20p' "$0"; exit 1 ;;
esac
