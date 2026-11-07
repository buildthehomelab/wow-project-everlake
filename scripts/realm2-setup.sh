#!/bin/bash
# Realm 2 ("Everlake Retail Test", realm id 71) beside realm 1 ("Everlake", realm id 70) on the same login server.
# Gate 5 tests 4 to 6 in docs/era-data.md: one Forever client switching between two realms that send different
# client data. Run it from the checkout that holds .env and the running containers (it uses `docker compose exec`).
#
#   scripts/realm2-setup.sh dbs        characters2 and hotfixes2 as copies of realm 1's databases (realm 1 may run)
#   scripts/realm2-setup.sh realm2     realm 2's data: the Test 1 class kit, its markers, its characters, realm row 71
#   scripts/realm2-setup.sh realm1     realm 1 without the class kit, with its own markers, Death Knights and Monks
#                                      moved out. Stop realm 1's worldserver first (lock protocol) and start it after.
#
# Then: docker compose -f docker-compose.yml -f docker-compose.realm2.yml up -d worldserver2
#
# What each realm sends (hotfixes) after this:
#   realm 1 (database hotfixes):  Forever's own rows, gate 2's map 530 (9530000-9530003), markers 9550000-9550001
#   realm 2 (database hotfixes2): the same, minus nothing, plus the Test 1 class kit (9540010-9540030) and its own
#                                 markers 9550000 (same push and record as realm 1, other text) and 9560001
# Characters: realm 2 (characters2) keeps the Death Knights and Monks of player accounts; realm 1 keeps everything
# else. Moved characters are soft-deleted the core's way (restore: .character deleted restore <name>).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SQL="$HERE/../sql/everlake"
KIT=("$SQL/2026_11_07_01_hotfixes_test1_classes.sql" "$SQL/2026_11_07_03_hotfixes_test1_talent_tree.sql"
     "$SQL/2026_11_07_05_hotfixes_test1_visuals.sql")

root_sql() { docker compose exec -T mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$@" 2>&1 | { grep -v "Using a password" || true; }' sh "$@"; }
root_dump() { docker compose exec -T mysql sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --skip-lock-tables --no-tablespaces "$1" 2>/dev/null' sh "$1"; }

# Player accounts are the ones whose Battle.net account is not a bot's
PLAYER_ACCOUNTS="SELECT a.id FROM auth.account a JOIN auth.battlenet_accounts b ON b.id = a.battlenet_account
                 WHERE b.email NOT LIKE '%@PLAYERBOT-V2.LOCAL'"
# The core's own soft delete (CHAR_UPD_DELETE_INFO): name and account kept in deleteInfos_*, restorable
soft_delete() {
    echo "UPDATE $1.characters SET deleteInfos_Name = name, deleteInfos_Account = account, deleteDate = UNIX_TIMESTAMP(),
          name = NULL, account = 0 WHERE account <> 0 AND $2;"
}
count_chars() {
    echo "DELETE FROM auth.realmcharacters WHERE realmid = $2;
          INSERT INTO auth.realmcharacters (realmid, acctid, numchars)
              SELECT $2, a.id, (SELECT COUNT(*) FROM $1.characters c WHERE c.account = a.id) FROM auth.account a;"
}

case "${1:-}" in
    dbs)
        for db in characters2 hotfixes2; do
            if root_sql -N -e "SHOW DATABASES LIKE '$db'" | grep -q "$db"; then
                echo "[realm2] $db exists already: left as it is (drop it by hand to copy it again)"; continue
            fi
            root_sql -e "CREATE DATABASE $db DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                         GRANT ALL PRIVILEGES ON $db.* TO '${DB_USER:-trinity}'@'%'; FLUSH PRIVILEGES;"
            echo "[realm2] copying ${db%2} into $db..."
            root_dump "${db%2}" | root_sql "$db"
            echo "[realm2] $db: $(root_sql -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '$db'") tables"
        done
        ;;
    realm2)
        for f in "${KIT[@]}" "$SQL/2026_11_07_07_hotfixes2_realm2_markers.sql"; do
            echo "[realm2] hotfixes2 <- $(basename "$f")"; root_sql hotfixes2 < "$f"
        done
        echo "[realm2] characters2: only the Death Knights and Monks of player accounts stay"
        root_sql -e "$(soft_delete characters2 "NOT (class IN (6, 10) AND account IN ($PLAYER_ACCOUNTS))")
                     $(count_chars characters2 71)"
        echo "[realm2] auth <- 2026_11_07_06_auth_realm2.sql"; root_sql auth < "$SQL/2026_11_07_06_auth_realm2.sql"
        root_sql -t -e "SELECT guid, account, name, class, level FROM characters2.characters WHERE account <> 0;
                        SELECT id, name, address, port, flag, contentSetId FROM auth.realmlist WHERE id IN (70, 71);"
        ;;
    realm1)
        if docker compose ps --status running --services 2>/dev/null | grep -qx worldserver; then
            echo "[realm1] stop realm 1's worldserver first (lock protocol)"; exit 1
        fi
        echo "[realm1] hotfixes: the Test 1 class kit's DELETEs (the kit files undo themselves)"
        cat "${KIT[@]}" | grep -E '^DELETE ' | root_sql hotfixes
        echo "[realm1] hotfixes <- 2026_11_07_08_hotfixes_realm1_markers.sql"
        root_sql hotfixes < "$SQL/2026_11_07_08_hotfixes_realm1_markers.sql"
        echo "[realm1] characters: Death Knights and Monks of player accounts move to realm 2"
        root_sql -e "$(soft_delete characters "class IN (6, 10) AND account IN ($PLAYER_ACCOUNTS)")
                     $(count_chars characters 70)"
        root_sql -t -e "SELECT COUNT(*) AS kit_rows_left FROM hotfixes.hotfix_data WHERE Id BETWEEN 9540000 AND 9549999;
                        SELECT guid, deleteInfos_Name, class FROM characters.characters WHERE account = 0 AND class IN (6, 10);"
        ;;
    *)
        sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 1
        ;;
esac
