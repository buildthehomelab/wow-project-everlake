-- Dynamic respawns, run once more for the core pin b5c98f7ad4 (core fork PR #47, Karrz's 37 commits after 0.1.35). Its
-- live captures add 82 spawns after the rule last ran (2026_11_13_00): 81 gameobjects (Shadowglen: 47 starter herbs,
-- 4 quest objects, 1 Battered Chest; Zephras Isle: 29 herb and copper nodes) and 1 creature (a Windshaper Novice Seer,
-- Zephras Isle). A realm that already ran 2026_11_13_00 puts them into the dynamic spawn groups 2 (quest objectives)
-- and 4 (gathering nodes) only if the rule runs again. On this pin the fork's updater happens to run 2026_11_13_00
-- again (the pin changes the earlier custom file 2026_11_11_10, and the updater then applies every later custom file
-- again), but only where its record of applied files is whole. This file is new to every realm, so it runs after the
-- pin's files either way.
-- The statements are the ones of 2026_11_13_00, unchanged: 1. remove rows of groups 2 and 4 whose spawn is gone (the pin
-- deletes none, so this finds nothing; kept so the two files stay the same). 2. Run the rule of 2026_11_09_00 (see that
-- file for why each spawn qualifies). Safe to run again; named after the core's newest custom world files
-- (2026_11_12_*) and after 2026_11_13_00, so it runs last and changes nothing when that file has just run.

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
