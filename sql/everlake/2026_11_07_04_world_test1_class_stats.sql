-- Test 1 (docs/era-data.md): base stats for Death Knight (class 6) and Monk (class 10) on the Forever (vanilla) realm.
-- TDB ships retail-scale rows for them (a level 8 Death Knight had 497 stamina, 0 spirit, 0 base health: 4,800 health
-- under the core's vanilla 10-health-per-stamina rule). Until they get their own tables, the Death Knight takes the
-- Warrior's rows and the Monk the Rogue's.
-- Health regeneration is separate: Player::OCTRegenHPPerSpirit has no case for either class and returns 0 (core work).
-- Undo: restore the two classes' rows from TDB's player_classlevelstats.
DELETE FROM `player_classlevelstats` WHERE `class` IN (6, 10);
INSERT INTO `player_classlevelstats` (`class`, `level`, `str`, `agi`, `sta`, `inte`, `spi`, `basehp`, `basemana`)
SELECT 6, `level`, `str`, `agi`, `sta`, `inte`, `spi`, `basehp`, `basemana` FROM `player_classlevelstats` WHERE `class` = 1;
INSERT INTO `player_classlevelstats` (`class`, `level`, `str`, `agi`, `sta`, `inte`, `spi`, `basehp`, `basemana`)
SELECT 10, `level`, `str`, `agi`, `sta`, `inte`, `spi`, `basehp`, `basemana` FROM `player_classlevelstats` WHERE `class` = 4;
