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
#   TRACKER_BUILD_DB (ft_world_build)     read only, while the world build is on (below): what a replay found
#
# The world build (docs/forever-tracker.md, "The world build") has a user of its own, "tracker_build", made only when
# TRACKER_BUILD_DB_PASSWORD is set. Every start first takes all its rights away and locks it, then gives back:
#   TRACKER_BUILD_DB (ft_world_build)     everything: the scratch database "tracker.py world replay" drops and rebuilds
#   every other database                  nothing, not even reading: the replay runs hundreds of update files, and this
#                                         user is what keeps them inside the scratch database
# Without the password, or with a scratch name this script refuses (said as an ERROR; the website still starts), the
# user stays locked with no rights, and "tracker" gets no read right from the world build. A role given to
# tracker_build by hand is not taken away: the replay refuses such a user.
#
# MYSQL_HOST, MYSQL_ROOT_PASSWORD, TRACKER_DB_PASSWORD: required. TRACKER_WORLD_DB, TRACKER_HOTFIXES_DB,
# TRACKER_BUILD_DB, TRACKER_BUILD_DB_PASSWORD: optional.
set -euo pipefail

: "${MYSQL_HOST:?}" "${MYSQL_ROOT_PASSWORD:?set MYSQL_ROOT_PASSWORD in .env}" "${TRACKER_DB_PASSWORD:?set TRACKER_DB_PASSWORD in .env}"
WORLD_DB="${TRACKER_WORLD_DB:-world_ptr}"
HOTFIXES_DB="${TRACKER_HOTFIXES_DB:-hotfixes_ptr}"
for name in "$WORLD_DB" "$HOTFIXES_DB"; do
    [[ "$name" =~ ^[A-Za-z0-9_]+$ ]] || { echo "[tracker] ERROR: database name '$name': letters, digits and _ only"; exit 1; }
done
case "$TRACKER_DB_PASSWORD" in *"'"*|*'"'*|*'\'*) echo "[tracker] ERROR: TRACKER_DB_PASSWORD: no quotes or backslashes"; exit 1 ;; esac
BUILD_DB="${TRACKER_BUILD_DB:-ft_world_build}"
BUILD_PASSWORD="${TRACKER_BUILD_DB_PASSWORD:-}"

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
# The world build's user. First, before anything below can stop this script: no rights, and locked.
build_user_exists() { [ "$(root_sql -N -e "SELECT COUNT(*) FROM mysql.user WHERE user = 'tracker_build' AND host = '%'")" = 1 ]; }
if build_user_exists; then
    root_sql -e "REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'tracker_build'@'%'; ALTER USER 'tracker_build'@'%' ACCOUNT LOCK;"
fi
# Then every right on the scratch database and none anywhere else. The replay drops and creates that database itself,
# so it is not created here. A problem with the build's settings switches the build off and is said; it never stops
# the website.
build="" build_problem=""
if [ -n "$BUILD_PASSWORD" ]; then
    # ft_ first: no realm, login or tracker database is named so, so the scratch name can never be one of them
    if ! [[ "$BUILD_DB" =~ ^ft_[A-Za-z0-9_]+$ ]]; then
        build_problem="TRACKER_BUILD_DB '$BUILD_DB': a name that starts with ft_ (letters, digits and _ only)"
    elif [ "$BUILD_DB" = "$WORLD_DB" ] || [ "$BUILD_DB" = "$HOTFIXES_DB" ]; then
        build_problem="TRACKER_BUILD_DB '$BUILD_DB' is a database the analysis reads: choose a name of its own"
    else
        case "$BUILD_PASSWORD" in *"'"*|*'"'*|*'\'*) build_problem="TRACKER_BUILD_DB_PASSWORD: no quotes or backslashes" ;; esac
    fi
    if [ -z "$build_problem" ]; then
        # never a database that holds something else: tables that a replay did not make (ft_replay_files is its mark)
        read -r table_count replay_mark <<<"$(root_sql -N -e "SELECT COUNT(*), COALESCE(SUM(table_name = 'ft_replay_files'), 0) FROM information_schema.tables WHERE table_schema = '$BUILD_DB'")"
        if [ "$table_count" != 0 ] && [ "$replay_mark" = 0 ]; then
            build_problem="TRACKER_BUILD_DB '$BUILD_DB' exists and holds $table_count tables that no replay made: choose a name of its own"
        fi
    fi
    if [ -z "$build_problem" ]; then
        # in a grant, _ in a database name stands for any character: escaped, so the grant covers this one name only.
        # The website's user may read what a replay found there, and write nothing: only tracker_build writes it.
        build="CREATE USER IF NOT EXISTS 'tracker_build'@'%' IDENTIFIED WITH mysql_native_password BY '$BUILD_PASSWORD';
ALTER USER 'tracker_build'@'%' IDENTIFIED WITH mysql_native_password BY '$BUILD_PASSWORD' ACCOUNT UNLOCK;
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'tracker_build'@'%';
GRANT ALL PRIVILEGES ON \`${BUILD_DB//_/\\_}\`.* TO 'tracker_build'@'%';
GRANT SELECT ON \`${BUILD_DB//_/\\_}\`.* TO 'tracker'@'%';"
    fi
fi
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
$build
FLUSH PRIVILEGES;
SQL
reads="world, hotfixes and auth"
[ -z "$build" ] || reads="world, hotfixes, auth and the world build's $BUILD_DB"
echo "[tracker] user tracker: reads $reads; analysis on $WORLD_DB + $HOTFIXES_DB"
root_sql -N -e "SHOW GRANTS FOR 'tracker'@'%'" | sed 's/^/[tracker]   /'
if [ -n "$build" ]; then
    echo "[tracker] user tracker_build: the world build's scratch database $BUILD_DB, nothing else"
    root_sql -N -e "SHOW GRANTS FOR 'tracker_build'@'%'" | sed 's/^/[tracker]   /'
    # The replay notes each row change with triggers. A server that writes a binary log lets only an administrator
    # create them, unless told otherwise. A server-wide setting: said here, never changed here.
    read -r log_bin trust <<<"$(root_sql -N -e 'SELECT @@log_bin, @@log_bin_trust_function_creators')"
    if [ "$log_bin" = 1 ] && [ "$trust" = 0 ]; then
        echo "[tracker] NOTE: this MySQL server writes a binary log, so tracker_build cannot create the replay's triggers."
        echo "[tracker]   An administrator runs, once:  SET GLOBAL log_bin_trust_function_creators = 1;"
        echo "[tracker]   and keeps it over restarts with --log-bin-trust-function-creators=1 (or --skip-log-bin, as docker-compose.yml starts MySQL)"
    fi
elif [ -n "$build_problem" ]; then
    echo "[tracker] ERROR: $build_problem. The world build is off until this is set right"
else
    echo "[tracker] no TRACKER_BUILD_DB_PASSWORD: the world build is off"
fi
if [ -z "$build" ] && build_user_exists; then echo "[tracker] user tracker_build: locked, no rights"; fi
