#!/bin/bash
# The bots' shared database (Playerbot.SharedDatabase, `playerbot`). Safe to run again.
# - On a new MySQL volume, MySQL runs it once by itself (after 01-trinity.sh), over its socket.
# - On an existing volume, the bots-init service (docker-compose.yml) runs it before every worldserver start, over the
#   network (MYSQL_HOST set): the live realm gets its bot database without anyone running docker on the host.
# worldserver then loads the schema and static data on its next start (docker/entrypoint.sh).
set -euo pipefail
: "${DB_USER:?DB_USER must be set}"
if [ -n "${MYSQL_HOST:-}" ]; then
    run() { MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -h"$MYSQL_HOST" -uroot; }
else
    run() { mysql --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD"; }
fi
run <<SQL
CREATE DATABASE IF NOT EXISTS playerbot DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON playerbot.* TO '${DB_USER}'@'%';
FLUSH PRIVILEGES;
SQL
echo "[bots-init] database playerbot ready for ${DB_USER}"
