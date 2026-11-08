#!/bin/bash
# The bots' shared database (Playerbot.SharedDatabase). Runs once on a new MySQL volume, after 01-trinity.sh.
# Existing volume (e.g. a realm that ran before the bots), once:
#   docker compose exec mysql bash /docker-entrypoint-initdb.d/02-playerbot.sh
# worldserver then loads the schema and static data on its next start (docker/entrypoint.sh).
set -e
mysql --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL
CREATE DATABASE IF NOT EXISTS playerbot DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON playerbot.* TO '${DB_USER}'@'%';
FLUSH PRIVILEGES;
SQL
