#!/bin/bash
# Scratch test only: realm 2's characters database and the bots' database (used when the image has PlayerbotV2).
set -e
mysql --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL
CREATE DATABASE IF NOT EXISTS characters2 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS playerbot   DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON characters2.* TO '${DB_USER}'@'%';
GRANT ALL PRIVILEGES ON playerbot.*   TO '${DB_USER}'@'%';
FLUSH PRIVILEGES;
SQL
