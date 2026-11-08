#!/bin/bash
# Generates bnetserver.conf / worldserver.conf from the .dist files on every start
# (same keys as contrib/linux/configure_server.sh), then starts the requested server.
#
# Usage: entrypoint.sh worldserver|bnetserver|<any command>
set -euo pipefail

ROOT=/opt/trinitycore
ETC="$ROOT/etc"
CERTS="$ROOT/certs"
OVERRIDES="$ROOT/overrides"

: "${DB_HOST:=mysql}"
: "${DB_PORT:=3306}"
: "${DB_USER:=trinity}"
: "${DB_PASSWORD:?DB_PASSWORD must be set}"
: "${PUBLIC_ADDRESS:=127.0.0.1}"
: "${REALM_LOCAL_ADDRESS:=127.0.0.1}"
: "${REALM_LOCAL_SUBNET_MASK:=255.255.255.0}"
: "${REALM_NAME:=Forever}"
: "${REALM_ID:=70}"
# The core's auth update 2026_11_07_00 moves the realms to 70862 (Battle.net's 2026-11-07 update, same game data).
# Clients still on 70790 (a frozen test copy, a player who hasn't updated) keep seeing and joining them: bnetserver
# and every worldserver accept these builds too (Realm.AlsoAcceptBuilds, comma-separated).
ALSO_ACCEPT_BUILDS="70790"
# Realm 1's world port. 8085 by default; another one when the host already runs a server on 8085 (e.g. beside Evermore)
: "${WORLD_PORT:=8085}"
: "${LOGIN_HOSTNAME:=trinity.actual.battle.net}"
# The login server's certificate chain and key, in $CERTS: scripts/gen-certs.sh's by default, or a real certificate
# for LOGIN_HOSTNAME (e.g. Let's Encrypt's fullchain.pem and privkey.pem, see docs/client-connection.md)
: "${CERT_FILE:=forever.cert.pem}"
: "${KEY_FILE:=forever.key.pem}"

# setkey <file> <key> <value>: replaces "key = ..." or appends it when the .dist has no such line
# (awk + ENVIRON, so passwords containing & \ | / are written verbatim)
setkey() {
    local file="$1" tmp
    tmp="$(mktemp)"
    K="$2" V="$3" awk '
        BEGIN { k = ENVIRON["K"]; v = ENVIRON["V"]; found = 0 }
        index($0, k) == 1 && substr($0, length(k) + 1) ~ /^[ \t]*=/ { print k " = " v; found = 1; next }
        { print }
        END { if (!found) { print ""; print k " = " v } }
    ' "$file" > "$tmp"
    cat "$tmp" > "$file"
    rm -f "$tmp"
}

# apply_overrides <conf> <name>: "Key = Value" lines from overrides/<name>.conf win over everything
apply_overrides() {
    local file="$1" src="$OVERRIDES/$2.conf" line key value
    [ -f "$src" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%%$'\r'}"
        [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
        key="$(echo "${line%%=*}" | xargs)"
        value="$(echo "${line#*=}" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
        setkey "$file" "$key" "$value"
    done < "$src"
    echo "[entrypoint] applied overrides from $src"
}

db_info() { echo "\"${DB_HOST};${DB_PORT};${DB_USER};${DB_PASSWORD};$1\""; }

mysql_q() {
    MYSQL_PWD="$DB_PASSWORD" mysql -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" -N -B -e "$1"
}

wait_for_mysql() {
    echo "[entrypoint] waiting for MySQL at ${DB_HOST}:${DB_PORT}..."
    until mysql_q "SELECT 1" >/dev/null 2>&1; do sleep 2; done
}

# DBC.Locale: DBC_LOCALE if set, else the first language folder found in data/dbc (the client's language)
dbc_locale() {
    local name="${DBC_LOCALE:-}" i
    local -a names=(enUS koKR frFR deDE zhCN zhTW esES esMX ruRU none ptBR itIT)
    if [ -z "$name" ]; then
        if [ -d "$ROOT/data/dbc/enUS" ]; then
            name=enUS
        else
            name="$(ls "$ROOT/data/dbc" 2>/dev/null | head -n1)"
        fi
    fi
    for i in "${!names[@]}"; do
        [ "${names[$i]}" = "$name" ] && { echo "$i"; return; }
    done
    echo 0
}

configure_worldserver() {
    local f="$ETC/worldserver.conf"
    cp "$ETC/worldserver.conf.dist" "$f"
    setkey "$f" LoginDatabaseInfo     "$(db_info auth)"
    setkey "$f" WorldDatabaseInfo     "$(db_info world)"
    setkey "$f" CharacterDatabaseInfo "$(db_info characters)"
    setkey "$f" HotfixDatabaseInfo    "$(db_info hotfixes)"
    setkey "$f" RealmID 70
    setkey "$f" WorldServerPort "$WORLD_PORT"
    setkey "$f" Expansion 0
    setkey "$f" BindIP '"0.0.0.0"'
    setkey "$f" DataDir "\"$ROOT/data\""
    setkey "$f" LogsDir "\"$ROOT/logs\""
    setkey "$f" SourceDirectory '"/src/TrinityCore"'
    setkey "$f" MySQLExecutable '"/usr/bin/mysql"'
    # no auth key is known for the Forever builds (70790, 70862): the core skips only the digest check
    setkey "$f" Network.SkipBuildAuthKeyCheck 1
    setkey "$f" Network.EnterEncryptedModeRegionGroup 8
    setkey "$f" Realm.CfgContentSetID 137
    setkey "$f" Realm.SuperDistrictID 2
    setkey "$f" Updates.EnableDatabases 15
    setkey "$f" Updates.AutoSetup 1
    setkey "$f" DBC.Locale "$(dbc_locale)"
    setkey "$f" mmap.enablePathFinding "${MMAP_PATHFINDING:-0}"
    # PACKET_LOG=1: every world packet in logs/World.pkt (diagnostics only, grows quickly; read with scripts/pkt-dump.py)
    if [ "${PACKET_LOG:-0}" = 1 ]; then
        setkey "$f" PacketLogFile '"World.pkt"'
    fi
    # ~1 million harmless DB warnings per start: file only, not console
    setkey "$f" Logger.sql.sql 5,DBErrors
    setkey "$f" Ra.Enable 0
    # SOAP: used by the account website, reachable only on the internal Docker network (port never published)
    if [ "${SOAP_ENABLED:-0}" = 1 ]; then
        setkey "$f" SOAP.Enabled 1
        setkey "$f" SOAP.IP '"0.0.0.0"'
        setkey "$f" SOAP.Port 7878
    else
        setkey "$f" SOAP.Enabled 0
    fi
    # same gameplay settings as the repack
    setkey "$f" Classic.GuildFinder 1
    setkey "$f" Classic.Shop.Enabled 1
    setkey "$f" AccountInstancesPerHour 5
    setkey "$f" PlayerSave.Stats.MinLevel 1
    # At character select a client asks this worldserver for another ruleset's realm (the ruleset picker): it checks the
    # client's build like bnetserver does, so it needs the same extra builds, or a 70790 client finds no realm there.
    setkey "$f" Realm.AlsoAcceptBuilds "\"$ALSO_ACCEPT_BUILDS\""
    apply_overrides "$f" worldserver
    configure_playerbots
}

# Bots (WoW Forever Bots, src/modules/PlayerbotV2): worldserver.conf.d/playerbot.conf from its .dist on every start, then
# overrides/playerbot.conf. The build's own active defaults (zz-forever-bots.conf: world bots, auction house bot, raid
# bots; zz-forever-lfg.conf: dungeon finder fill) stay as installed; overrides/playerbot.conf is read last and wins.
configure_playerbots() {
    local dir="$ETC/worldserver.conf.d"
    [ -f "$dir/playerbot.conf.dist" ] || return 0
    cp "$dir/playerbot.conf.dist" "$dir/playerbot.conf"
    apply_overrides "$dir/playerbot.conf" playerbot
    # worldserver reads worldserver.conf.d in name order, so the zz-* defaults would win over playerbot.conf:
    # put the overrides in a file read after them too
    if [ -f "$OVERRIDES/playerbot.conf" ]; then
        { echo "[worldserver]"; grep -E '^[[:space:]]*[A-Za-z][A-Za-z0-9_.]*[[:space:]]*=' "$OVERRIDES/playerbot.conf"; } > "$dir/zz-9-overrides.conf"
    else
        rm -f "$dir/zz-9-overrides.conf"
    fi
}

# The bots' shared database (`playerbot`, Playerbot.SharedDatabase): docker/mysql-init creates it on a new MySQL
# volume, docker/mysql-init/02-playerbot.sh on an existing one. Its schema and static data (names, templates, dungeon
# routes) are loaded here once, as the TrinityCore user; the module applies its own migrations (sql/playerbot_v2) when
# worldserver starts. Bots also need the navigation meshes (mmaps) and MMAP_PATHFINDING=1, or they stand still.
prepare_playerbot_db() {
    local sql=/src/TrinityCore/sql/playerbot_shared
    [ -f "$sql/playerbot_shared_schema.sql" ] || return 0
    # SHOW DATABASES lists only the databases this user has rights on
    if ! mysql_q "SHOW DATABASES LIKE 'playerbot'" | grep -q playerbot; then
        echo "[entrypoint] ERROR: database 'playerbot' is missing or not granted to ${DB_USER}."
        echo "[entrypoint] Existing MySQL volume: run docker/mysql-init/02-playerbot.sh once (README, Bots)."
        exit 1
    fi
    if [ "$(mysql_q "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='playerbot'")" = "0" ]; then
        echo "[entrypoint] loading the playerbot schema and static data (once)..."
        MYSQL_PWD="$DB_PASSWORD" mysql -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" < "$sql/playerbot_shared_schema.sql"
        MYSQL_PWD="$DB_PASSWORD" mysql -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" playerbot < "$sql/playerbot_shared_data.sql"
        echo "[entrypoint] playerbot database ready"
    fi
    if [ "${MMAP_PATHFINDING:-0}" != 1 ] || [ ! -d "$ROOT/data/mmaps" ]; then
        echo "[entrypoint] WARNING: bots need mmaps in the data folder and MMAP_PATHFINDING=1, or they cannot walk (README, Bots)."
    fi
}

configure_bnetserver() {
    local f="$ETC/bnetserver.conf"
    cp "$ETC/bnetserver.conf.dist" "$f"
    setkey "$f" LoginDatabaseInfo "$(db_info auth)"
    setkey "$f" BindIP '"0.0.0.0"'
    setkey "$f" LoginREST.ExternalAddress "$LOGIN_HOSTNAME"
    setkey "$f" LoginREST.LocalAddress "$LOGIN_HOSTNAME"
    setkey "$f" CertificatesFile "\"$CERTS/$CERT_FILE\""
    setkey "$f" PrivateKeyFile "\"$CERTS/$KEY_FILE\""
    setkey "$f" LogsDir "\"$ROOT/logs\""
    setkey "$f" Realm.CfgContentSetID 137
    setkey "$f" Realm.SuperDistrictID 2
    setkey "$f" Realm.AlsoAcceptBuilds "\"$ALSO_ACCEPT_BUILDS\""
    apply_overrides "$f" bnetserver
}

check_data() {
    local missing=0 d
    for d in dbc maps vmaps; do
        [ -d "$ROOT/data/$d" ] || { echo "[entrypoint] ERROR: $ROOT/data/$d is missing"; missing=1; }
    done
    [ -f "$ROOT/data/vmaps/GameObjectModels.dtree" ] || { echo "[entrypoint] ERROR: vmaps/GameObjectModels.dtree is missing"; missing=1; }
    if [ "$missing" = 1 ]; then
        echo "[entrypoint] Extract dbc, gt, maps, vmaps (cameras) from the client and put them in ./data (see README)."
        exit 1
    fi
}

check_certs() {
    if [ ! -f "$CERTS/$CERT_FILE" ] || [ ! -f "$CERTS/$KEY_FILE" ]; then
        echo "[entrypoint] ERROR: $CERTS/$CERT_FILE and $KEY_FILE are required (CERTS_DIR, CERT_FILE, KEY_FILE)."
        echo "[entrypoint] Generate them with ./scripts/gen-certs.sh, or use a real certificate (docs/client-connection.md)."
        exit 1
    fi
}

# CLIENT_BUILD (e.g. 70450): accepts a client build newer than the branch supports (experimental).
# Written as the last sql/custom/auth file, so worldserver's updater applies it (and re-applies it when the value
# changes) before the realm list and build list are loaded.
OVERRIDE_SQL=/src/TrinityCore/sql/custom/auth/2099_12_31_99_auth_client_build_override.sql
write_client_build_override() {
    if [ -z "${CLIENT_BUILD:-}" ]; then
        rm -f "$OVERRIDE_SQL"
        return 0
    fi
    if ! [[ "$CLIENT_BUILD" =~ ^[0-9]+$ ]]; then
        echo "[entrypoint] ERROR: CLIENT_BUILD must be a number (e.g. 70450), got '$CLIENT_BUILD'"
        exit 1
    fi
    cat > "$OVERRIDE_SQL" <<SQL
-- Generated by the Docker entrypoint from CLIENT_BUILD (experimental, not from the forever branch)
DELETE FROM \`build_info\` WHERE \`build\`=${CLIENT_BUILD};
INSERT INTO \`build_info\` (\`build\`,\`majorVersion\`,\`minorVersion\`,\`bugfixVersion\`,\`hotfixVersion\`) VALUES
(${CLIENT_BUILD},1,60,1,NULL);
UPDATE \`realmlist\` SET \`gamebuild\`=${CLIENT_BUILD} WHERE \`id\` IN (70,71,72,73);
SQL
    echo "[entrypoint] CLIENT_BUILD=${CLIENT_BUILD}: realm build override written (experimental)"
}

# bnetserver reads auth.build_info only when it starts, and the rows come from sql/custom/auth files that worldserver's
# updater applies (bnetserver runs no updates). Started together, bnetserver could load the build list before e.g. the
# 70862 row exists and turn those clients away until its next restart. So wait until every custom auth file in this
# image is in auth.updates; after AUTH_UPDATES_WAIT seconds (default 600) start anyway and say which are missing.
wait_for_auth_updates() {
    local f have waited=0 limit="${AUTH_UPDATES_WAIT:-600}" list=""
    [[ "$limit" =~ ^[0-9]+$ ]] || { echo "[entrypoint] AUTH_UPDATES_WAIT must be a number of seconds, got '$limit': using 600"; limit=600; }
    local -a names=()
    for f in /src/TrinityCore/sql/custom/auth/*.sql; do
        [ -e "$f" ] || continue
        # the CLIENT_BUILD file is written by worldserver's entrypoint in its own container, never in this one
        [ "$f" = "$OVERRIDE_SQL" ] && continue
        f="$(basename "$f")"
        names+=("$f")
        list="${list:+$list,}'${f//\'/\'\'}'"
    done
    [ "${#names[@]}" -gt 0 ] || return 0
    echo "[entrypoint] waiting for worldserver to apply the ${#names[@]} custom auth updates (the build list)..."
    until [ "$(mysql_q "SELECT COUNT(DISTINCT name) FROM auth.updates WHERE name IN ($list)" 2>/dev/null || echo 0)" = "${#names[@]}" ]; do
        if [ "$waited" -ge "$limit" ]; then
            echo "[entrypoint] WARNING: custom auth updates still missing after ${limit}s, starting anyway:"
            for f in "${names[@]}"; do
                have="$(mysql_q "SELECT COUNT(*) FROM auth.updates WHERE name = '${f//\'/\'\'}'" 2>/dev/null || echo 0)"
                [ "$have" = 0 ] && echo "[entrypoint]   $f"
            done
            echo "[entrypoint] Restart bnetserver once worldserver has applied them, or clients of a new build are refused."
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done
    echo "[entrypoint] custom auth updates applied (${#names[@]})"
}

# The realm row is created by the auth updates that worldserver applies on its first start.
update_realmlist() {
    echo "[entrypoint] waiting for realm ${REALM_ID} in auth.realmlist (worldserver creates it on first start)..."
    until [ "$(mysql_q "SELECT COUNT(*) FROM auth.realmlist WHERE id=${REALM_ID}" 2>/dev/null || echo 0)" = "1" ]; do
        sleep 5
    done
    mysql_q "UPDATE auth.realmlist SET name='${REALM_NAME//\'/\'\'}', address='${PUBLIC_ADDRESS}', \
        localAddress='${REALM_LOCAL_ADDRESS}', localSubnetMask='${REALM_LOCAL_SUBNET_MASK}', port=${WORLD_PORT} \
        WHERE id=${REALM_ID}"
    echo "[entrypoint] realm ${REALM_ID}: address=${PUBLIC_ADDRESS} localAddress=${REALM_LOCAL_ADDRESS} port=${WORLD_PORT}"
}

case "${1:-worldserver}" in
    worldserver)
        shift || true
        configure_worldserver
        write_client_build_override
        check_data
        wait_for_mysql
        prepare_playerbot_db
        exec "$ROOT/bin/worldserver" -c "$ETC/worldserver.conf" "$@"
        ;;
    bnetserver)
        shift || true
        configure_bnetserver
        check_certs
        wait_for_mysql
        update_realmlist
        wait_for_auth_updates
        exec "$ROOT/bin/bnetserver" -c "$ETC/bnetserver.conf" "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
