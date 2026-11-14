-- Reapply the existing dynamic respawn rules after Karrz 0.1.36 (core PR #54).
-- Dated November 14 solely to sort after all November 13 core world files, including
-- 2026_11_13_91. The SQL statements match 2026_11_13_01 and remain replay-safe.

DELETE s FROM `spawn_group` s LEFT JOIN `creature` c ON c.`guid` = s.`spawnId`
WHERE s.`groupId` IN (2, 4) AND s.`spawnType` = 0 AND c.`guid` IS NULL;
DELETE s FROM `spawn_group` s LEFT JOIN `gameobject` g ON g.`guid` = s.`spawnId`
WHERE s.`groupId` IN (2, 4) AND s.`spawnType` = 1 AND g.`guid` IS NULL;

-- group 4: gathering nodes
INSERT IGNORE INTO `spawn_group` (`groupId`, `spawnType`, `spawnId`)
SELECT 4, 1, g.`guid`
FROM `gameobject` g
JOIN `gameobject_template` t ON t.`entry` = g.`id`
WHERE t.`type` = 3
  AND g.`spawntimesecs` > 0
  AND t.`Data0` IN (8, 9, 10, 11, 26, 27, 29, 30, 31, 32, 33, 34, 35, 45, 47, 48, 49, 50, 51, 259, 439, 440, 441, 442,
                    443, 444, 519, 521, 1119, 1120, 1121, 1122, 1123, 1124,
                    18, 19, 20, 21, 22, 25, 38, 39, 40, 41, 42, 379, 380, 399, 400, 719, 939, 1632, 4170)
  AND NOT EXISTS (SELECT 1 FROM `spawn_group` s WHERE s.`spawnType` = 1 AND s.`spawnId` = g.`guid`);

-- group 2: quest creatures (kill objective, or a quest item in their loot)
INSERT IGNORE INTO `spawn_group` (`groupId`, `spawnType`, `spawnId`)
SELECT 2, 0, c.`guid`
FROM `creature` c
WHERE c.`spawntimesecs` > 0 AND c.`spawntimesecs` <= 1800
  AND (c.`id` IN (SELECT o.`ObjectID` FROM `quest_objectives` o WHERE o.`Type` = 0)
       OR EXISTS (SELECT 1
                  FROM `creature_template_difficulty` d
                  JOIN `creature_loot_template` l ON l.`Entry` = d.`LootID` AND l.`ItemType` = 0
                  WHERE d.`Entry` = c.`id` AND d.`LootID` <> 0
                    AND (l.`QuestRequired` = 1
                         OR l.`Item` IN (SELECT o.`ObjectID` FROM `quest_objectives` o WHERE o.`Type` = 1))))
  AND NOT EXISTS (SELECT 1 FROM `spawn_group` s WHERE s.`spawnType` = 0 AND s.`spawnId` = c.`guid`);

-- group 2: quest objects (a quest uses it, or a chest with a quest item in its loot)
INSERT IGNORE INTO `spawn_group` (`groupId`, `spawnType`, `spawnId`)
SELECT 2, 1, g.`guid`
FROM `gameobject` g
JOIN `gameobject_template` t ON t.`entry` = g.`id`
WHERE g.`spawntimesecs` > 0 AND g.`spawntimesecs` <= 1800
  AND (g.`id` IN (SELECT o.`ObjectID` FROM `quest_objectives` o WHERE o.`Type` = 2)
       OR (t.`type` = 3 AND t.`Data1` <> 0 AND EXISTS (
              SELECT 1 FROM `gameobject_loot_template` l
              WHERE l.`Entry` = t.`Data1` AND l.`ItemType` = 0
                AND (l.`QuestRequired` = 1
                     OR l.`Item` IN (SELECT o.`ObjectID` FROM `quest_objectives` o WHERE o.`Type` = 1)))))
  AND NOT EXISTS (SELECT 1 FROM `spawn_group` s WHERE s.`spawnType` = 1 AND s.`spawnId` = g.`guid`);
