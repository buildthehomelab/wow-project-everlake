-- Test 1 (docs/era-data.md): stand-in visuals for the retail Death Knight spells. Their own visuals aren't in the
-- Forever build, so the kit sent them without any and the client played a plain melee swing. These rows borrow
-- vanilla visuals the client ships: Death Coil's bolt (47632, the damage spell, carries the projectile) gets the
-- Warlock's Death Coil (64), Death Strike gets Heroic Strike (39), Obliterate gets Mortal Strike (164064), Howling
-- Blast gets Frost Nova (17) and Anti-Magic Shell gets Power Word: Shield (784).
-- Pushes from 9540030 (new pushes, so a client that has the class kit fetches these too).
-- Written by tools/era/hotfix_kit.py; re-runnable: the DELETEs undo it.

DELETE FROM `hotfix_data` WHERE `Id` BETWEEN 9540030 AND 9540030;

DELETE FROM `spell_x_spell_visual` WHERE `ID` IN (954201, 954202, 954203, 954204, 954205);
INSERT INTO `spell_x_spell_visual` (`ID`, `DifficultyID`, `SpellVisualID`, `Probability`, `Flags`, `Priority`, `SpellIconFileID`, `ActiveIconFileID`, `ViewerUnitConditionID`, `ViewerPlayerConditionID`, `CasterUnitConditionID`, `CasterPlayerConditionID`, `SpellID`, `VerifiedBuild`) VALUES
(954201, 0, 64, 1.0, 0, 1, 0, 0, 0, 0, 0, 0, 47632, 70790),
(954202, 0, 39, 1.0, 0, 1, 0, 0, 0, 0, 0, 0, 49998, 70790),
(954203, 0, 164064, 1.0, 0, 1, 0, 0, 0, 0, 0, 0, 49020, 70790),
(954204, 0, 17, 1.0, 0, 1, 0, 0, 0, 0, 0, 0, 49184, 70790),
(954205, 0, 784, 1.0, 0, 1, 0, 0, 0, 0, 0, 0, 48707, 70790);

INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES
(9540030, 954003001, 666345498, 954201, 1, 70790),
(9540030, 954003002, 666345498, 954202, 1, 70790),
(9540030, 954003003, 666345498, 954203, 1, 70790),
(9540030, 954003004, 666345498, 954204, 1, 70790),
(9540030, 954003005, 666345498, 954205, 1, 70790);
