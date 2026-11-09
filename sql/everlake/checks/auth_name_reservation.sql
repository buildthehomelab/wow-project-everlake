-- Checks for the name reservation tables (the core's sql/custom/auth/2026_11_07_09 and 2026_11_09_00: one row per full
-- name, name + surname, the surname compared without regard to case). Read only.
-- Run against the login database (auth). Every query should return no rows, except the summary at the end.
-- tools/name-reservation/backfill.py --check also compares them with each realm's characters database.

-- 1. A character row for a full name with no reservation row (a manual edit). Clashes between accounts need each
--    realm's characters database: backfill.py lists them.
SELECT c.`realm_id`, c.`character_guid`, c.`name`, c.`surname`
FROM `name_reservation_character` c
LEFT JOIN `name_reservation` r ON r.`name` = c.`name` AND r.`surname` = c.`surname`
WHERE r.`name` IS NULL;

-- 2. Freed although a character still uses the name
SELECT r.`name`, r.`surname`, r.`battlenet_account`, r.`freed_at`, COUNT(*) AS characters
FROM `name_reservation` r JOIN `name_reservation_character` c ON c.`name` = r.`name` AND c.`surname` = r.`surname`
WHERE r.`freed_at` IS NOT NULL
GROUP BY r.`name`, r.`surname`, r.`battlenet_account`, r.`freed_at`;

-- 3. Held but no character uses it and it was never freed: a create that never finished (session closed during the
--    save) or a delete from outside the core. backfill.py --apply frees them (freed_at = now, grace period starts).
SELECT r.`name`, r.`surname`, r.`battlenet_account`, r.`realm_id`, r.`character_guid`, r.`created`
FROM `name_reservation` r
WHERE r.`freed_at` IS NULL
  AND NOT EXISTS (SELECT 1 FROM `name_reservation_character` c WHERE c.`name` = r.`name` AND c.`surname` = r.`surname`);

-- 4. Owner is not a Battle.net account (deleted account) or is a bot's
SELECT r.`name`, r.`surname`, r.`battlenet_account`, b.`email`
FROM `name_reservation` r
LEFT JOIN `battlenet_accounts` b ON b.`id` = r.`battlenet_account`
WHERE b.`id` IS NULL OR b.`email` LIKE '%@PLAYERBOT-V2.LOCAL';

-- 5. A name not in the core's normalised form (first letter upper case, the rest lower case)
SELECT `name` FROM `name_reservation`
WHERE BINARY `name` <> BINARY CONCAT(UPPER(LEFT(`name`, 1)), LOWER(SUBSTRING(`name`, 2)));

-- Summary
SELECT COUNT(*) AS full_names,
       SUM(`freed_at` IS NULL) AS in_use,
       SUM(`freed_at` IS NOT NULL) AS freed,
       (SELECT COUNT(*) FROM `name_reservation_character`) AS characters
FROM `name_reservation`;
