-- Dynamic respawns, run again after Karrz 0.1.35 (core fork PR #45, pin 8a60671524). The rule in 2026_11_09_00 put spawns
-- into the dynamic spawn groups 2 (quest objectives) and 4 (gathering nodes) once; spawns added or turned into quest
-- targets after it were left out (0.1.35 adds 101: The Drowned City, Krol'dok Stronghold, Riverglades, Zephras Isle),
-- and 0.1.35 deletes 14 spawns that were in group 2 (creatures 46000035 and 46000041, the 12 floating Flintfire crates),
-- which leaves spawn_group rows the worldserver logs and skips.
-- 1. Remove rows of groups 2 and 4 whose spawn is gone. 2. Run the same rule as 2026_11_09_00 (see that file for why each
-- spawn qualifies). Safe to run again; named after Karrz's last 0.1.35 files (2026_11_11_*) so a fresh build runs it
-- after them too.

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
