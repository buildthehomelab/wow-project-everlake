#!/bin/bash
# ForeverTracker's database and MySQL user (docker-compose.tracker.yml, service tracker-init; runs on every start of
# the tracker app, safe to repeat). MySQL's root over the app network.
#
# The user "tracker" gets exactly these rights, every start (anything granted by hand is taken away again):
#   forever_tracker                       everything (the tracker's own ft_* tables)
#   world, hotfixes                       read only: the live realms' data is never written by the tracker
#   auth: realmlist, battlenet_accounts,  read only: the client build, and game master logins to the Forge
#         account, account_access
#   TRACKER_WORLD_DB, TRACKER_HOTFIXES_DB read and write when they are not the live ones (default world_ptr and
#                                         hotfixes_ptr): the Forge applies its fixes there, on the PTR
#
# MYSQL_HOST, MYSQL_ROOT_PASSWORD, TRACKER_DB_PASSWORD: required. TRACKER_WORLD_DB, TRACKER_HOTFIXES_DB: optional.
set -euo pipefail

: "${MYSQL_HOST:?}" "${MYSQL_ROOT_PASSWORD:?set MYSQL_ROOT_PASSWORD in .env}" "${TRACKER_DB_PASSWORD:?set TRACKER_DB_PASSWORD in .env}"
WORLD_DB="${TRACKER_WORLD_DB:-world_ptr}"
HOTFIXES_DB="${TRACKER_HOTFIXES_DB:-hotfixes_ptr}"
for name in "$WORLD_DB" "$HOTFIXES_DB"; do
    [[ "$name" =~ ^[A-Za-z0-9_]+$ ]] || { echo "[tracker] ERROR: database name '$name': letters, digits and _ only"; exit 1; }
done
case "$TRACKER_DB_PASSWORD" in *"'"*|*'"'*|*'\'*) echo "[tracker] ERROR: TRACKER_DB_PASSWORD: no quotes or backslashes"; exit 1 ;; esac

root_sql() { MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -h"$MYSQL_HOST" -uroot "$@"; }
for _ in $(seq 60); do root_sql -e 'SELECT 1' >/dev/null 2>&1 && break; sleep 5; done
db_exists() { [ "$(root_sql -N -e "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = '$1'")" = 1 ]; }

# Forge writes: only to databases that are not the live realms'
writes=""
for name in "$WORLD_DB" "$HOTFIXES_DB"; do
    case "$name" in
        world|hotfixes) echo "[tracker] $name is a live database: read only, the Forge cannot apply fixes to it" ;;
        *)
            db_exists "$name" || echo "[tracker] WARNING: $name does not exist yet (start the everlake-ptr app first): the analysis fails until it does"
            writes+="GRANT SELECT, INSERT, UPDATE, DELETE ON \`$name\`.* TO 'tracker'@'%';"$'\n'
            ;;
    esac
done
# SELECT on the live world and hotfixes lets TRACKER_WORLD_DB=world (a read-only report of live) work as it is
root_sql <<SQL
CREATE DATABASE IF NOT EXISTS forever_tracker DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'tracker'@'%' IDENTIFIED WITH mysql_native_password BY '$TRACKER_DB_PASSWORD';
ALTER USER 'tracker'@'%' IDENTIFIED WITH mysql_native_password BY '$TRACKER_DB_PASSWORD';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'tracker'@'%';
GRANT ALL PRIVILEGES ON forever_tracker.* TO 'tracker'@'%';
GRANT SELECT ON world.* TO 'tracker'@'%';
GRANT SELECT ON hotfixes.* TO 'tracker'@'%';
GRANT SELECT ON auth.realmlist TO 'tracker'@'%';
GRANT SELECT ON auth.battlenet_accounts TO 'tracker'@'%';
GRANT SELECT ON auth.account TO 'tracker'@'%';
GRANT SELECT ON auth.account_access TO 'tracker'@'%';
$writes
FLUSH PRIVILEGES;
SQL
echo "[tracker] user tracker: reads world, hotfixes and auth; analysis on $WORLD_DB + $HOTFIXES_DB"
root_sql -N -e "SHOW GRANTS FOR 'tracker'@'%'" | sed 's/^/[tracker]   /'
