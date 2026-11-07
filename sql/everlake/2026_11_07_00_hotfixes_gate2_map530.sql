-- Gate 2, experiment 2: map 530 (Outland/Quel'Thalas) for the Forever client, as hotfixes.
-- The Forever client (1.60.1.70790) has no map 530. This adds the Map row (modelled on Forever's own Kalimdor row,
-- with the TBC Anniversary 2.5.6.70577 WDT, FileDataID 828395), a MapDifficulty row, and the AreaTable rows of the
-- Sunstrider Isle tiles (expansion01_42-44_11-13) from TBC Anniversary, with sound and music IDs left at 0.
-- The terrain itself comes from tools/tact (docs/custom-files.md, experiment 2). Re-runnable; the DELETEs undo it.

DELETE FROM `hotfix_data` WHERE `Id` = 9530000;
DELETE FROM `map` WHERE `ID` = 530;
DELETE FROM `map_difficulty` WHERE `ID` = 900530;
DELETE FROM `area_table` WHERE `ID` IN (3430, 3431, 3432, 3455, 3482, 3531, 3532, 3533, 3534);

INSERT INTO `map` (`ID`, `Directory`, `MapName`, `MapDescription0`, `MapDescription1`, `PvpShortDescription`, `PvpLongDescription`,
  `CorpseX`, `CorpseY`, `MapType`, `InstanceType`, `ExpansionID`, `AreaTableID`, `LoadingScreenID`, `TimeOfDayOverride`, `ParentMapID`,
  `CosmeticParentMapID`, `TimeOffset`, `MinimapIconScale`, `CorpseMapID`, `MaxPlayers`, `WindSettingsID`, `ZmpFileDataID`, `WdtFileDataID`,
  `OceanLiquidTypeID`, `NavigationMaxDistance`, `PreloadFileDataID`, `Flags1`, `Flags2`, `Flags3`, `VerifiedBuild`) VALUES
(530, 'Expansion01', 'Outland', '', '', '', '', 0, 0, 1, 0, 1, 0, 3, -1, -1, -1, 0, 1, -1, 0, 136, 0, 828395, 1250, 0, 0,
 159399517, 135528464, 2277510, 70790);

INSERT INTO `map_difficulty` (`Message`, `ID`, `DifficultyID`, `LockID`, `ResetInterval`, `MaxPlayers`, `ItemContext`, `ItemContextPickerID`,
  `Flags`, `ContentTuningID`, `WorldStateExpressionID`, `MapID`, `VerifiedBuild`) VALUES
('', 900530, 0, 0, 0, 0, 0, 0, 0, 0, 0, 530, 70790);

INSERT INTO `area_table` (`ID`, `ZoneName`, `AreaName`, `ContinentID`, `ParentAreaID`, `AreaBit`, `SoundProviderPref`,
  `SoundProviderPrefUnderwater`, `AmbienceID`, `UwAmbience`, `ZoneMusic`, `UwZoneMusic`, `ExplorationLevel`, `IntroSound`, `UwIntroSound`,
  `FactionGroupMask`, `AmbientMultiplier`, `MountFlags`, `PvpCombatWorldStateID`, `WildBattlePetLevelMin`, `WildBattlePetLevelMax`,
  `WindSettingsID`, `ContentTuningID`, `Flags1`, `Flags2`, `LiquidTypeID1`, `LiquidTypeID2`, `LiquidTypeID3`, `LiquidTypeID4`, `VerifiedBuild`) VALUES
(3430, 'EversongWoods', 'Eversong Woods', 530, 0, 1581, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0.60000002384, 0, -1, 0, 0, 0, 0, 64, 256, 0, 0, 0, 0, 70790),
(3431, 'SunstriderIsle', 'Sunstrider Isle', 530, 3430, 1582, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.60000002384, 0, -1, 0, 0, 0, 0, 1074790464, 256, 0, 0, 0, 0, 70790),
(3432, 'ShrineofDath''Remar', 'Shrine of Dath''Remar', 530, 3430, 1583, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.60000002384, 0, -1, 0, 0, 0, 0, 1073741888, 256, 0, 0, 0, 0, 70790),
(3455, 'TheNorthSea', 'The North Sea', 530, 0, 1084, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0.60000002384, 0, -1, 0, 0, 0, 0, 64, 256, 0, 0, 0, 0, 70790),
(3482, 'TheDeadScar', 'The Dead Scar', 530, 3430, 1107, 0, 0, 0, 0, 0, 0, 5, 0, 0, 0, 0.60000002384, 0, -1, 0, 0, 0, 0, 1073741888, 256, 0, 0, 0, 0, 70790),
(3531, 'SkulkingRow', 'Skulking Row', 530, 3430, 1155, 0, 0, 0, 0, 0, 0, 5, 0, 0, 0, 0.60000002384, 0, -1, 0, 0, 0, 0, 1073741888, 256, 0, 0, 0, 0, 70790),
(3532, 'DawningLane', 'Dawning Lane', 530, 3430, 1156, 0, 0, 0, 0, 0, 0, 5, 0, 0, 0, 0.60000002384, 0, -1, 0, 0, 0, 0, 1073741888, 256, 0, 0, 0, 0, 70790),
(3533, 'RuinsofSilvermoon', 'Ruins of Silvermoon', 530, 3430, 1066, 0, 0, 0, 0, 0, 0, 5, 0, 0, 0, 0.60000002384, 0, -1, 0, 0, 0, 0, 1073741888, 256, 0, 0, 0, 0, 70790),
(3534, 'Feth''sWay', 'Feth''s Way', 530, 3430, 1067, 0, 0, 0, 0, 0, 0, 5, 0, 0, 0, 0.60000002384, 0, -1, 0, 0, 0, 0, 1073741888, 256, 0, 0, 0, 0, 70790);

-- Send them to the client: Map 0xBD84CD62, MapDifficulty 0x9265F70D, AreaTable 0x7253EB43 (table hashes from the client's DB2 headers)
INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES
(9530000, 953000001, 3179597154, 530, 1, 70790),
(9530000, 953000002, 2456155917, 900530, 1, 70790),
(9530000, 953000010, 1918102339, 3430, 1, 70790),
(9530000, 953000011, 1918102339, 3431, 1, 70790),
(9530000, 953000012, 1918102339, 3432, 1, 70790),
(9530000, 953000013, 1918102339, 3455, 1, 70790),
(9530000, 953000014, 1918102339, 3482, 1, 70790),
(9530000, 953000015, 1918102339, 3531, 1, 70790),
(9530000, 953000016, 1918102339, 3532, 1, 70790),
(9530000, 953000017, 1918102339, 3533, 1, 70790),
(9530000, 953000018, 1918102339, 3534, 1, 70790);
