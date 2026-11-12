#!/usr/bin/env bash
# Diagnostic only: detach the custom terrain map while activation is disabled.
set -euo pipefail
mode=${1:-check}
case "$mode" in check|detach|restore) ;; *) echo "usage: $0 check|detach|restore" >&2; exit 2;; esac
mysql_container=ix-everlake-mysql-1
world_container=ix-everlake-realm2-worldserver2-1
mysql_root() {
    docker exec -i "$mysql_container" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot "$@"' sh "$@"
}
fail() { echo "$*" >&2; exit 1; }
guard() {
    local schemas
    schemas=$(docker exec "$world_container" sh -c 'printf "%s\n%s\n%s\n" "$TC_REALM_ID" "${TC_WORLD_DATABASE_INFO##*;}" "${TC_HOTFIX_DATABASE_INFO##*;}"')
    [[ $schemas == $'71\nworld_classic\nhotfixes_classic' ]] || fail "Expected realm 71 and isolated Classic schemas"
    [[ $(mysql_root -N -e 'SELECT COUNT(*) FROM auth.realmlist WHERE id=71 AND port=8095 AND contentSetId=138') == 1 ]] || fail "Unexpected realm registration"
    [[ $(mysql_root -N -e "SELECT COUNT(*) FROM hotfixes_classic.map WHERE ID=9000 AND Directory='ClassicAzeroth' AND ParentMapID IN (0,-1) AND WdtFileDataID=40011612 AND VerifiedBuild=70790") == 1 ]] || fail "Unexpected Classic map registration"
    [[ $(mysql_root -N -e 'SELECT COUNT(*) FROM hotfixes_classic.hotfix_data WHERE TableHash=3179597154 AND RecordId=9000 AND Status=1 AND VerifiedBuild=70790') == 1 ]] || fail "Expected one advertised Classic map hotfix"
    [[ $(mysql_root -N -e 'SELECT COUNT(*) FROM world_classic.terrain_swap_defaults WHERE TerrainSwapMap=9000') == 0 ]] || fail "Disable Classic terrain activation before this diagnostic"
}
guard
mysql_root -t -e 'SELECT ID,Directory,ParentMapID,WdtFileDataID,Flags1,VerifiedBuild FROM hotfixes_classic.map WHERE ID=9000; SELECT Id,UniqueId,Status FROM hotfixes_classic.hotfix_data WHERE TableHash=3179597154 AND RecordId=9000;'
[[ $mode != check ]] || exit 0
parent=$(mysql_root -N -e 'SELECT ParentMapID FROM hotfixes_classic.map WHERE ID=9000 AND VerifiedBuild=70790')
if [[ $mode == detach ]]; then
    [[ $parent == 0 ]] || fail "Already detached; no changes made"
    target=-1
else
    [[ $parent == -1 ]] || fail "Already attached; no changes made"
    target=0
fi
# Refuse uint32 overflow rather than wrap the client cache revision.
ids=$(mysql_root -N -e 'SELECT MAX(Id),MAX(UniqueId) FROM hotfixes_classic.hotfix_data')
read -r push unique <<< "$ids"
[[ $push =~ ^[0-9]+$ && $unique =~ ^[0-9]+$ ]] || fail "Invalid hotfix revision"
(( push < 4294967295 && unique < 4294967295 )) || fail "Hotfix revision exhausted"
backup=$(mktemp -d "${TMPDIR:-/tmp}/everlake-classic-parent.XXXXXXXX")
chmod 700 "$backup"
docker exec "$mysql_container" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --no-tablespaces --no-create-info --skip-add-locks hotfixes_classic map --where="ID=9000 AND VerifiedBuild=70790"' > "$backup/map.before.sql"
[[ -s $backup/map.before.sql ]] || fail "Empty map backup"
printf 'Map backup: %s\n' "$backup"
docker stop --time 120 "$world_container" >/dev/null
trap 'docker start "$world_container" >/dev/null' EXIT
# The stopped Classic server cannot race its own hotfix update. Strict SQL mode
# rejects overflow if another administrator changes revisions during this test.
mysql_root hotfixes_classic <<SQL
SET SESSION sql_mode='STRICT_ALL_TABLES';
START TRANSACTION;
SET @next_push = (SELECT MAX(Id) + 1 FROM hotfix_data);
SET @next_unique = (SELECT MAX(UniqueId) + 1 FROM hotfix_data);
UPDATE map SET ParentMapID=$target WHERE ID=9000 AND VerifiedBuild=70790;
UPDATE hotfix_data SET Id=@next_push, UniqueId=@next_unique
WHERE TableHash=3179597154 AND RecordId=9000 AND Status=1 AND VerifiedBuild=70790;
COMMIT;
SQL
printf '%s complete; Classic is restarting. Terrain activation remains disabled. This is not a release fix.\n' "$mode"
