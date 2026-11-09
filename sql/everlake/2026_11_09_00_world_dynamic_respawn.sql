-- Dynamic respawns: quest targets and gathering nodes come back faster in a crowded zone (Respawn.DynamicMode = 1,
-- docker/entrypoint.sh). The core scales only spawns in a spawn group with the dynamic-rate flag (0x08): the Forever
-- world data has the two system groups for them, 2 "Dynamic Scaling (Quest objectives)" and 4 "Dynamic Scaling
-- (Gathering nodes)", but no members. This puts them in:
--   group 4: every herb and ore node (chest gameobjects whose lock needs Herbalism or Mining)
--   group 2: creatures a quest asks to kill or that drop a quest item, and gameobjects a quest asks to use or that hold
--            a quest item, with a respawn of 30 minutes or less (the core's documented default; rares stay as they are)
-- Respawn time = normal x min(1, Respawn.DynamicRateCreature / players in the zone), never under the Minimum. Bots
-- count as players in the zone.
--
-- A spawn can be in one group only: spawns already in a group (dungeon bosses, events) are left alone. Safe to run
-- again: realm 2 shares this world database but its image may lack this file, and the updater may forget it.
--
-- Herb and ore lock ids: Forever's Lock table (wago.tools/db2/Lock?product=wowf, 1.60.1), locks with a skill key of
-- lock type 2 (Herbalism) or 3 (Mining).

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
