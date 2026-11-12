-- Classic hotfix database only. Map 9000 supplies terrain for Eastern Kingdoms (map 0).
START TRANSACTION;

INSERT INTO `map` (
  `ID`, `Directory`, `MapName`, `MapDescription0`, `MapDescription1`,
  `PvpShortDescription`, `PvpLongDescription`, `MapType`, `InstanceType`,
  `ExpansionID`, `LoadingScreenID`, `TimeOfDayOverride`, `ParentMapID`,
  `CosmeticParentMapID`, `MinimapIconScale`, `CorpseMapID`, `WdtFileDataID`, `VerifiedBuild`
) VALUES (9000, 'ClassicAzeroth', 'Eastern Kingdoms (Classic)', '', '', '', '',
          1, 0, 0, 3, -1, 0, -1, 1, -1, 40011612, 70790);

INSERT INTO `map_difficulty` (`Message`, `ID`, `DifficultyID`, `MapID`, `VerifiedBuild`)
VALUES ('', 909000, 0, 9000, 70790);

INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`)
VALUES (9690000, 969000001, 3179597154, 9000, 1, 70790),
       (9690000, 969000002, 2456155917, 909000, 1, 70790);

COMMIT;
