-- Gate 5, tests 4-6 (docs/era-data.md): realm 2 "Everlake Two" beside realm 1 on the same login server.
-- Row 71 is one of the fork's placeholder realms ("Forever PvP", port 8095); it becomes realm 2, served by the
-- worldserver2 container (docker-compose.realm2.yml: RealmID 71, port 8095, databases characters2 and hotfixes2).
-- Addresses, region, build and content set are copied from realm 1 (row 70), so no address is written here.
-- Undo: UPDATE `realmlist` SET `name` = 'Forever PvP', `icon` = 1, `flag` = 0, `contentSetId` = 136 WHERE `id` = 71;
UPDATE `realmlist` AS r2 JOIN `realmlist` AS r1 ON r1.`id` = 70
SET r2.`name` = 'Everlake Two', r2.`address` = r1.`address`, r2.`localAddress` = r1.`localAddress`,
    r2.`localSubnetMask` = r1.`localSubnetMask`, r2.`port` = 8095, r2.`icon` = r1.`icon`, r2.`flag` = 2,
    r2.`timezone` = r1.`timezone`, r2.`allowedSecurityLevel` = 0, r2.`gamebuild` = r1.`gamebuild`,
    r2.`Region` = r1.`Region`, r2.`Battlegroup` = r1.`Battlegroup`, r2.`contentSetId` = r1.`contentSetId`
WHERE r2.`id` = 71;
