#!/usr/bin/env bash
# Candidate fix: enable Classic terrain while suppressing its unsupported low-detail path.
set -euo pipefail
mode=${1:-check}
case "$mode" in check|apply|rollback) ;; *) echo "usage: $0 check|apply|rollback" >&2; exit 2;; esac
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

}
guard
mysql_root -t -e 'SELECT ID,Directory,ParentMapID,WdtFileDataID,Flags1,VerifiedBuild FROM hotfixes_classic.map WHERE ID=9000; SELECT Id,UniqueId,Status FROM hotfixes_classic.hotfix_data WHERE TableHash=3179597154 AND RecordId=9000;'
[[ $mode != check ]] || exit 0
state=$(mysql_root -N -e 'SELECT ParentMapID,Flags1,(SELECT COUNT(*) FROM world_classic.terrain_swap_defaults WHERE TerrainSwapMap=9000) FROM hotfixes_classic.map WHERE ID=9000 AND VerifiedBuild=70790')
if [[ $mode == apply ]]; then
    [[ $state == $'-1\t1536\t0' ]] || fail "Expected the verified detached baseline: parent -1, flags 1536, activation absent"
    target=0
    flags=2098688 # 0x200000 DisableLowDetailTerrain + 0x600 split object/texture ADTs
    activation="INSERT INTO world_classic.terrain_swap_defaults (MapId,TerrainSwapMap,Comment) VALUES (0,9000,'Classic Eastern Kingdoms terrain - full-detail candidate');"
else
    [[ $state == $'0\t2098688\t1' ]] || fail "Expected the exact full-detail candidate state"
    [[ $(mysql_root -N -e "SELECT COUNT(*) FROM world_classic.terrain_swap_defaults WHERE MapId=0 AND TerrainSwapMap=9000 AND Comment='Classic Eastern Kingdoms terrain - full-detail candidate'") == 1 ]] || fail "Activation was changed outside this test; no changes made"
    target=-1
    flags=1536
    activation='DELETE FROM world_classic.terrain_swap_defaults WHERE MapId=0 AND TerrainSwapMap=9000;'
fi
# Refuse uint32 overflow rather than wrap the client cache revision.
ids=$(mysql_root -N -e 'SELECT MAX(Id),MAX(UniqueId) FROM hotfixes_classic.hotfix_data')
read -r push unique <<< "$ids"
[[ $push =~ ^[0-9]+$ && $unique =~ ^[0-9]+$ ]] || fail "Invalid hotfix revision"
(( push < 4294967295 && unique < 4294967295 )) || fail "Hotfix revision exhausted"
backup=$(mktemp -d "${TMPDIR:-/tmp}/everlake-classic-full-detail.XXXXXXXX")
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
UPDATE map SET ParentMapID=$target, Flags1=$flags WHERE ID=9000 AND VerifiedBuild=70790;
UPDATE hotfix_data SET Id=@next_push, UniqueId=@next_unique
WHERE TableHash=3179597154 AND RecordId=9000 AND Status=1 AND VerifiedBuild=70790;
$activation
COMMIT;
SQL
printf '%s complete; Classic is restarting. Candidate terrain state changed. Live terrain validation is required before release.\n' "$mode"
