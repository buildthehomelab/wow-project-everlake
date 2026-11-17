-- Dynamic respawns for every open-world mob in Eastern Kingdoms and Kalimdor, the way Evermore (AzerothCore) does it.
-- Until now only quest targets and herb/ore nodes scaled (2026_11_09_00 and its reruns), so a crowded zone still
-- emptied of the mobs no quest names: grinding spots, skinning and cloth farms, and the packs around quest targets.
--
-- AzerothCore has no list of spawns: it scales every spawn outside instances except quest givers, world bosses and
-- rares. TrinityCore scales only spawns in a group with the dynamic-rate flag (0x08), so this puts AzerothCore's rule
-- into group 2 as data:
--   creatures: map 0 or 1, respawn 30 minutes or less, not a quest giver (npcflag or quest starter/ender), not rare,
--              rare elite or obsolete/boss Classification (2, 3, 4), not a boss mob (TypeFlags 0x04, what the core's isWorldBoss reads)
--   objects:   map 0 or 1, respawn 30 minutes or less, chests (type 3) and fishing pools (type 25)
-- Rates and floors are unchanged (RESPAWN_* in .env): nothing changes up to 40 players in a zone, bots included.
--
-- A spawn can be in one group only: spawns already in a group (quest targets, nodes, dungeon bosses, events) are left
-- alone. Safe to run again. A later rerun of the quest rule after new world data should run this file's rule too.

-- group 2: open-world creatures
INSERT IGNORE INTO `spawn_group` (`groupId`, `spawnType`, `spawnId`)
SELECT 2, 0, c.`guid`
FROM `creature` c
JOIN `creature_template` t ON t.`entry` = c.`id`
WHERE c.`map` IN (0, 1)
  AND c.`spawntimesecs` > 0 AND c.`spawntimesecs` <= 1800
  AND (COALESCE(c.`npcflag`, t.`npcflag`) & 2) = 0
  AND t.`Classification` NOT IN (2, 3, 4)
  AND NOT EXISTS (SELECT 1 FROM `creature_template_difficulty` d
                  WHERE d.`Entry` = c.`id` AND (d.`TypeFlags` & 4) <> 0)
  AND NOT EXISTS (SELECT 1 FROM `creature_queststarter` q WHERE q.`id` = c.`id`)
  AND NOT EXISTS (SELECT 1 FROM `creature_questender` q WHERE q.`id` = c.`id`)
  AND NOT EXISTS (SELECT 1 FROM `spawn_group` s WHERE s.`spawnType` = 0 AND s.`spawnId` = c.`guid`);

-- group 2: open-world chests and fishing pools
INSERT IGNORE INTO `spawn_group` (`groupId`, `spawnType`, `spawnId`)
SELECT 2, 1, g.`guid`
FROM `gameobject` g
JOIN `gameobject_template` t ON t.`entry` = g.`id`
WHERE g.`map` IN (0, 1)
  AND g.`spawntimesecs` > 0 AND g.`spawntimesecs` <= 1800
  AND t.`type` IN (3, 25)
  AND NOT EXISTS (SELECT 1 FROM `spawn_group` s WHERE s.`spawnType` = 1 AND s.`spawnId` = g.`guid`);
