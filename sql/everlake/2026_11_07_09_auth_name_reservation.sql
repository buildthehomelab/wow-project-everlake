-- Name reservation across realms (core patch docker/patches/0008-everlake-name-reservation.patch).
-- Login database (auth), shared by every realm's worldserver. The image copies this file to the core's
-- sql/custom/auth, so the core's updater applies it when a worldserver starts (Updates.EnableDatabases includes auth).
-- Without these tables a patched worldserver refuses every new character name (NameReservation.Enable = 0 turns the
-- feature off).
--
-- A character name belongs to one Battle.net account on every realm. A name stays reserved while a character on any
-- realm uses it; when the last one is deleted, freed_at is set and another account may take the name after
-- NameReservation.GracePeriod (worldserver.conf, default 90 days). Bots never reserve.
--
-- Existing characters: run tools/name-reservation/backfill.py once after this file (it reports clashes, it never
-- picks a winner). Checks: sql/everlake/checks/auth_name_reservation.sql.
-- Undo: DROP TABLE `name_reservation_character`, `name_reservation`;

CREATE TABLE IF NOT EXISTS `name_reservation` (
  -- the core's normalised name ("Ora": first letter upper case, the rest lower case), compared byte for byte like
  -- characters.name (utf8mb4_bin)
  `name` varchar(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  -- Forever's surname ("Ora Swiftwind"): the one the character last attached to the name had. Not unique, not
  -- reserved: only the name is.
  `surname` varchar(48) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `battlenet_account` int unsigned NOT NULL,
  -- the realm (realmlist.id) and character (characters.guid there) that took or used the name last
  `realm_id` int unsigned DEFAULT NULL,
  `character_guid` bigint unsigned DEFAULT NULL,
  `created` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- NULL = in use (or a character is being created with it); set when no character on any realm uses it any more
  `freed_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`name`),
  KEY `idx_battlenet_account` (`battlenet_account`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Everlake: character names reserved per Battle.net account across realms';

CREATE TABLE IF NOT EXISTS `name_reservation_character` (
  -- every character on every realm that uses a reserved name now (one toon = one character per realm)
  `realm_id` int unsigned NOT NULL,
  `character_guid` bigint unsigned NOT NULL,
  `name` varchar(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  PRIMARY KEY (`realm_id`, `character_guid`),
  KEY `idx_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Everlake: characters using a reserved name, per realm';
