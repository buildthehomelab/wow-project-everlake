-- Gate 5, tests 4-6 (docs/era-data.md): realm 2 "Everlake Two" beside realm 1 on the same login server.
-- Row 71 is one of the fork's placeholder realms ("Forever PvP", port 8095); it becomes realm 2, served by the
-- worldserver2 container (docker-compose.realm2.yml: RealmID 71, port 8095, databases characters2 and hotfixes2).
-- Addresses, region and build are copied from realm 1 (row 70), so no address is written here.
-- The Forever client picks a realm with its ruleset cards (RULESET at the top of the character screen): one card per
-- contentSetId (137 Normal, 138 Roleplay, 140 Hardcore), and the login server answers a card with
-- `SELECT id FROM realmlist WHERE contentSetId = ? LIMIT 1`. So every realm needs its own contentSetId: realm 1 keeps
-- Normal (137), realm 2 takes the Roleplay card (138; only the card, the server applies no roleplay rules; Forever's
-- ExpectedStat rows all have ContentSetID 0, so stats don't change). The other two placeholders (72 "Forever RP",
-- 73 "Forever Hardcore") have no worldserver and are hidden from the list with flag 3 (the core lists `flag <> 3`).
-- Undo: UPDATE `realmlist` SET `name` = 'Forever PvP', `icon` = 1, `flag` = 0, `contentSetId` = 136 WHERE `id` = 71;
--       UPDATE `realmlist` SET `flag` = 0 WHERE `id` IN (72, 73); UPDATE `realmlist` SET `contentSetId` = 138 WHERE `id` = 72;
UPDATE `realmlist` AS r2 JOIN `realmlist` AS r1 ON r1.`id` = 70
SET r2.`name` = 'Classic', r2.`address` = r1.`address`, r2.`localAddress` = r1.`localAddress`,
    r2.`localSubnetMask` = r1.`localSubnetMask`, r2.`port` = 8095, r2.`icon` = r1.`icon`, r2.`flag` = 2,
    r2.`timezone` = r1.`timezone`, r2.`allowedSecurityLevel` = 0, r2.`gamebuild` = r1.`gamebuild`,
    r2.`Region` = r1.`Region`, r2.`Battlegroup` = r1.`Battlegroup`, r2.`contentSetId` = 138
WHERE r2.`id` = 71;
UPDATE `realmlist` SET `flag` = 3 WHERE `id` IN (72, 73);
-- the card lookup doesn't skip hidden realms, so "Forever RP" also gives up the Roleplay content set
UPDATE `realmlist` SET `contentSetId` = 0 WHERE `id` = 72;
