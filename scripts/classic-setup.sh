#!/usr/bin/env bash
# Provision Classic schemas in the shared TrueNAS MySQL container.
set -euo pipefail
sql_dir="$(cd "$(dirname "$0")/../sql/classic" && pwd)"
mysql_container=ix-everlake-mysql-1
if [[ $(docker inspect --format '{{.State.Running}}' "$mysql_container") != true ]]; then
    echo "Expected running MySQL container $mysql_container" >&2
    exit 1
fi
db_user=$(docker exec "$mysql_container" sh -c 'printf "%s" "${DB_USER:-trinity}"')
[[ $db_user =~ ^[a-zA-Z0-9_]+$ ]] || { echo "Invalid DB_USER" >&2; exit 1; }

mysql_root() {
    docker exec -i "$mysql_container" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot "$@"' sh "$@"
}

dump() {
    docker exec -i "$mysql_container" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --no-tablespaces "$@"' sh "$@"
}

roleplay=$(mysql_root -N -e 'SELECT COUNT(*) FROM auth.realmlist WHERE id=71 AND port=8095 AND contentSetId=138')
[[ $roleplay == 1 ]] || { echo "Expected the existing Roleplay test realm on ID 71 and port 8095" >&2; exit 1; }
sources=$(mysql_root -N -e "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name IN ('world','hotfixes2','characters2')")
[[ $sources == 3 ]] || { echo "Missing existing Roleplay schemas" >&2; exit 1; }
existing=$(mysql_root -N -e "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name IN ('world_classic','hotfixes_classic')")
[[ $existing == 0 ]] || { echo "Classic schemas already exist. Inspect them before provisioning." >&2; exit 1; }

for mapping in world:world hotfixes2:hotfixes; do
    source=${mapping%:*}
    kind=${mapping#*:}
    target="${kind}_classic"
    mysql_root -e "CREATE DATABASE $target CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL ON $target.* TO '$db_user'@'%';"
    dump "$source" | mysql_root "$target"
    mysql_root "$target" < "$sql_dir/$kind.sql"
done
