#!/bin/bash
# The PTR's databases and realm row (docker-compose.ptr.yml). Uses the running MySQL container of the Everlake app;
# the live realms keep running.
#
#   scripts/ptr-setup.sh dbs       world_ptr and hotfixes_ptr as copies of realm 1's world and hotfixes, and the empty
#                                  characters_ptr and playerbot_ptr (worldserver fills them on the PTR's first start).
#                                  A database that exists is left as it is.
#   scripts/ptr-setup.sh refresh   world_ptr and hotfixes_ptr copied from realm 1 again (stop the PTR first): the PTR
#                                  then starts from live's world, and its own updates apply on top when it starts.
#   scripts/ptr-setup.sh realm     realm row 73 becomes "Everlake PTR": port 8097, the Hardcore card (140), GM accounts
#                                  only, address and build copied from realm 1. Undo: UPDATE auth.realmlist SET
#                                  name = 'Forever Hardcore', flag = 3, port = 8085, allowedSecurityLevel = 0 WHERE id = 73;
#   scripts/ptr-setup.sh status    the PTR's databases, its realm row, and the accounts that may enter it
#
# MYSQL_CONTAINER: the MySQL container (default: the one of the compose project ix-everlake, else everlake).
# DB_USER: the TrinityCore user (default: DB_USER from .env, else trinity).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HERE/../.env"
if [ -z "${DB_USER:-}" ] && [ -f "$ENV_FILE" ]; then
    DB_USER="$(sed -nE 's/^DB_USER=(.*)$/\1/p' "$ENV_FILE" | tail -1)"
fi
DB_USER="${DB_USER:-trinity}"

find_mysql() {
    local p c
    for p in ix-everlake everlake; do
        c="$(docker ps --filter "label=com.docker.compose.project=$p" --filter label=com.docker.compose.service=mysql --format '{{.Names}}' | head -1)"
        [ -n "$c" ] && { echo "$c"; return; }
    done
}
MYSQL_CONTAINER="${MYSQL_CONTAINER:-$(find_mysql)}"
[ -n "$MYSQL_CONTAINER" ] || { echo "[ptr] ERROR: no running Everlake MySQL container (set MYSQL_CONTAINER)"; exit 1; }

root_sql() { docker exec -i "$MYSQL_CONTAINER" sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$@" 2>&1 | { grep -v "Using a password" || true; }' sh "$@"; }
root_dump() { docker exec "$MYSQL_CONTAINER" sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --skip-lock-tables --no-tablespaces --routines --triggers "$1" 2>/dev/null' sh "$1"; }
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
ptr_running() { docker ps --filter label=com.docker.compose.service=worldserver-ptr --format '{{.Names}}' | grep -q .; }

echo "[ptr] MySQL container: $MYSQL_CONTAINER, TrinityCore user: $DB_USER"
case "${1:-}" in
    dbs)
        for pair in world:world_ptr hotfixes:hotfixes_ptr; do
            if db_exists "${pair#*:}"; then echo "[ptr] ${pair#*:} exists already: left as it is (refresh copies it again)"; continue; fi
            copy_db "${pair%%:*}" "${pair#*:}"
        done
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
            SET p.name = 'Everlake PTR', p.address = r1.address, p.localAddress = r1.localAddress,
                p.localSubnetMask = r1.localSubnetMask, p.port = 8097, p.icon = r1.icon, p.flag = 2,
                p.timezone = r1.timezone, p.allowedSecurityLevel = 3, p.gamebuild = r1.gamebuild,
                p.Region = r1.Region, p.Battlegroup = r1.Battlegroup, p.contentSetId = 140
            WHERE p.id = 73;"
        "$0" status
        ;;
    status)
        root_sql -e "SELECT id, name, port, flag, allowedSecurityLevel, contentSetId, gamebuild FROM auth.realmlist WHERE id IN (70, 71, 73);"
        root_sql -e "SELECT table_schema AS db, COUNT(*) AS tables FROM information_schema.tables
                     WHERE table_schema IN ('world_ptr', 'hotfixes_ptr', 'characters_ptr', 'playerbot_ptr') GROUP BY table_schema;"
        echo "[ptr] accounts that may enter the PTR (GM level 3 on all realms or on realm 73):"
        root_sql -e "SELECT a.id, a.username, aa.SecurityLevel, aa.RealmID FROM auth.account_access aa
                     JOIN auth.account a ON a.id = aa.AccountID WHERE aa.SecurityLevel >= 3 AND aa.RealmID IN (-1, 73);"
        ;;
    *)
        sed -n '2,20p' "$0"; exit 1 ;;
esac
