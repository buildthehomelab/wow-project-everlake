-- Test 1 (docs/era-data.md): let the 8 Forever races create a Death Knight (class 6) and a Monk (class 10).
-- The world database is retail TDB, where a Death Knight needs ActiveExpansionLevel 2 (WotLK) and a Monk 4 (MoP).
-- A Forever session's active expansion is 0 (Expansion = 0 in worldserver.conf), so both are lowered to 0 for the
-- races the Forever client offers. Which ruleset may create which class is our own rule (per realm), not this table.
-- The client and server rows for the classes themselves are the hotfixes in
-- 2026_11_07_01_hotfixes_test1_classes.sql. Start positions, action bars and the rest are TDB's own rows, which the
-- core skipped until now ("Wrong class 6 in `playercreateinfo`") because class 6 and 10 weren't in ChrClasses.
-- Undo: the UPDATEs at the end of this comment.
--   UPDATE `class_expansion_requirement` SET `ActiveExpansionLevel` = 2 WHERE `ClassID` = 6 AND `RaceID` BETWEEN 1 AND 8;
--   UPDATE `class_expansion_requirement` SET `ActiveExpansionLevel` = 4 WHERE `ClassID` = 10 AND `RaceID` BETWEEN 1 AND 8;

UPDATE `class_expansion_requirement` SET `ActiveExpansionLevel` = 0, `AccountExpansionLevel` = 0
WHERE `ClassID` IN (6, 10) AND `RaceID` BETWEEN 1 AND 8;
