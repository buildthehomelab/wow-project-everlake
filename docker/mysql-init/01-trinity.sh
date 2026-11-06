#!/bin/bash
# Runs once, on the first start of an empty MySQL volume.
# Creates the 4 empty databases (worldserver's auto-setup then fills them without asking)
# and the TrinityCore user.
set -e
mysql --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL
CREATE DATABASE IF NOT EXISTS auth       DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS characters DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS world      DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS hotfixes   DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'%' IDENTIFIED BY '${DB_PASSWORD}';
GRANT ALL PRIVILEGES ON auth.*       TO '${DB_USER}'@'%';
GRANT ALL PRIVILEGES ON characters.* TO '${DB_USER}'@'%';
GRANT ALL PRIVILEGES ON world.*      TO '${DB_USER}'@'%';
GRANT ALL PRIVILEGES ON hotfixes.*   TO '${DB_USER}'@'%';
FLUSH PRIVILEGES;
SQL
