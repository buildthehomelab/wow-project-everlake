#!/usr/bin/env bash
# Controlled, unreleased Map 9000 rendering-format experiment. See docs/classic-entry-test.md.
set -euo pipefail
mode=${1:-check}
case "$mode" in check|apply|rollback) ;; *) echo "usage: $0 check|apply|rollback [backup-directory]" >&2; exit 2;; esac
mysql_container=ix-everlake-mysql-1
world_container=ix-everlake-realm2-worldserver2-1
mysql_root() {
    docker exec -i "$mysql_container" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot "$@"' sh "$@"
}
fail() { echo "$*" >&2; exit 1; }
# Only print schema names, never connection strings or passwords.
schemas=$(docker exec "$world_container" sh -c 'printf "%s\n%s\n%s\n" "$TC_REALM_ID" "${TC_WORLD_DATABASE_INFO##*;}" "${TC_HOTFIX_DATABASE_INFO##*;}"')
[[ $schemas == $'71\nworld_classic\nhotfixes_classic' ]] || fail "Roleplay is not configured for realm 71 and the isolated Classic schemas. No changes made."
[[ $(mysql_root -N -e 'SELECT COUNT(*) FROM auth.realmlist WHERE id=71 AND port=8095 AND contentSetId=138') == 1 ]] || fail "Unexpected Roleplay realm registration"
[[ $(mysql_root -N -e 'SELECT COUNT(*) FROM hotfixes_classic.map WHERE ID=9000 AND ParentMapID=0 AND WdtFileDataID=40011612 AND VerifiedBuild=70790') == 1 ]] || fail "Unexpected Classic map registration"
[[ $(mysql_root -N -e 'SELECT COUNT(*) FROM hotfixes_classic.hotfix_data WHERE TableHash=3179597154 AND RecordId=9000 AND Status=1 AND VerifiedBuild=70790') == 1 ]] || fail "Expected one advertised Classic map hotfix"
mysql_root -t -e 'SELECT ID,Directory,ParentMapID,WdtFileDataID,Flags1,Flags2,Flags3,VerifiedBuild FROM hotfixes_classic.map WHERE ID=9000; SELECT Id,UniqueId,Status FROM hotfixes_classic.hotfix_data WHERE TableHash=3179597154 AND RecordId=9000; SELECT MapId,TerrainSwapMap FROM world_classic.terrain_swap_defaults WHERE MapId=0;'
[[ $mode != check ]] || exit 0
if [[ $mode == apply ]]; then
    flags=$(mysql_root -N -e 'SELECT Flags1 FROM hotfixes_classic.map WHERE ID=9000 AND VerifiedBuild=70790')
    [[ $flags =~ ^[0-9]+$ ]] || fail "Invalid flags"
    (( (flags & 1536) != 1536 )) || fail "Split-file flags are already set; no changes made"
    backup=$(mktemp -d "${TMPDIR:-/tmp}/everlake-classic-entry.XXXXXXXX")
    chmod 700 "$backup"
    printf '%s\n' "$flags" > "$backup/flags1.before"
    docker exec "$mysql_container" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --no-tablespaces --no-create-info --skip-add-locks hotfixes_classic map --where="ID=9000 AND VerifiedBuild=70790"' > "$backup/map.before.sql"
    [[ -s $backup/map.before.sql ]] || fail "Map backup is empty"
    printf 'Backup and rollback directory: %s\n' "$backup"
    flags=$((flags | 1536))
else
    backup=${2:?supply the backup directory printed by apply}
    flags=$(cat "$backup/flags1.before")
    [[ $flags =~ ^[0-9]+$ ]] || fail "Invalid saved flags"
fi
# Do not update a database while its worldserver is serving players.
docker stop --time 120 "$world_container" >/dev/null
# Always bring the same container back, including after an SQL failure.
trap 'docker start "$world_container" >/dev/null' EXIT
# A fresh push and unique ID invalidate the client cache for both apply and rollback.
mysql_root hotfixes_classic <<SQL
START TRANSACTION;
SET @next_push = (SELECT MAX(Id) + 1 FROM hotfix_data);
SET @next_unique = (SELECT MAX(UniqueId) + 1 FROM hotfix_data);
UPDATE map SET Flags1=$flags WHERE ID=9000 AND VerifiedBuild=70790;
UPDATE hotfix_data SET Id=@next_push, UniqueId=@next_unique
WHERE TableHash=3179597154 AND RecordId=9000 AND Status=1 AND VerifiedBuild=70790;
COMMIT;
SQL
printf '%s complete. Roleplay is restarting. This is a candidate test, not a verified fix.\n' "$mode"
