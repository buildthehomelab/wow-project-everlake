#!/usr/bin/env bash
# Isolate terrain activation from world-entry failure. Never a release configuration.
set -euo pipefail
mode=${1:-check}
case "$mode" in check|disable|restore) ;; *) echo "usage: $0 check|disable|restore [backup-directory]" >&2; exit 2;; esac
here=$(cd "$(dirname "$0")" && pwd)
bash "$here/classic-entry-test.sh" check
mysql_container=ix-everlake-mysql-1
world_container=ix-everlake-realm2-worldserver2-1
mysql_root() { docker exec -i "$mysql_container" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot "$@"' sh "$@"; }
fail() { echo "$*" >&2; exit 1; }
count=$(mysql_root -N -e 'SELECT COUNT(*) FROM world_classic.terrain_swap_defaults WHERE MapId=0 AND TerrainSwapMap=9000')
[[ $mode != check ]] || { echo "Classic terrain activation rows: $count"; exit 0; }
if [[ $mode == disable ]]; then
    [[ $count == 1 ]] || fail "Expected exactly one Classic terrain activation row"
    backup=$(mktemp -d "${TMPDIR:-/tmp}/everlake-classic-terrain.XXXXXXXX")
    chmod 700 "$backup"
    mysql_root -N -e 'SELECT HEX(COALESCE(Comment,"")) FROM world_classic.terrain_swap_defaults WHERE MapId=0 AND TerrainSwapMap=9000' > "$backup/comment.hex"
    echo "Restore directory: $backup"
    sql='DELETE FROM terrain_swap_defaults WHERE MapId=0 AND TerrainSwapMap=9000;'
else
    [[ $count == 0 ]] || fail "Classic terrain activation already exists; no changes made"
    backup=${2:?supply the restore directory printed by disable}
    comment=$(cat "$backup/comment.hex")
    [[ $comment =~ ^[0-9A-Fa-f]*$ ]] || fail "Invalid saved comment"
    sql="INSERT INTO terrain_swap_defaults (MapId,TerrainSwapMap,Comment) VALUES (0,9000,CONVERT(UNHEX('$comment') USING utf8mb4));"
fi
docker stop --time 120 "$world_container" >/dev/null
trap 'docker start "$world_container" >/dev/null' EXIT
mysql_root world_classic -e "START TRANSACTION; $sql COMMIT;"
echo "$mode complete; Roleplay is restarting. Reconnect the client for the next test."
