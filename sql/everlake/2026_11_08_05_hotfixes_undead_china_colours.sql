-- Undead China skin colours without the China setting (docs/china-undead.md).
-- Blizzard pairs Undead skin colours with Skin Type (ChrCustomizationReqChoice): the six normal colours need Bony
-- (requirements 61 male, 66 female), the six China colours need Fresh (4976 male, 4977 female). The China colours'
-- requirements, and Fresh's own (4975), also have OverrideArchive 1: only with the client's China setting on. So in a
-- normal client a China colour is shown, then dropped when the creator checks again; a normal colour takes its place,
-- and that one needs Bony, so Skin Type falls back to Bony. These three requirement rows are sent with OverrideArchive
-- -1 (any setting); the Fresh pairing stays. Every other field is as in the Forever build 1.60.1.70790.
-- It also removes 2026_11_08_04 (push 9570004, never applied on the server: it would have made the China colours need
-- Bony). Hotfix push 9570005. Re-runnable. Restart the worldserver afterwards.
-- Undo: DELETE FROM `hotfix_data` WHERE `Id` = 9570005; DELETE FROM `chr_customization_req` WHERE `ID` IN (4975, 4976, 4977);

DELETE FROM `hotfix_data` WHERE `Id` IN (9570004, 9570005);
DELETE FROM `chr_customization_option` WHERE `ID` IN (58, 63);
DELETE FROM `chr_customization_choice` WHERE `ID` IN (6425, 6426, 6427, 6428, 6429, 6430, 6371, 6372, 6373, 6374, 6375, 6376);

DELETE FROM `chr_customization_req` WHERE `ID` IN (4975, 4976, 4977);
INSERT INTO `chr_customization_req` (`ID`, `ReqSource`, `Flags`, `ClassMask`, `RegionGroupMask`, `AchievementID`, `QuestID`,
  `OverrideArchive`, `ItemModifiedAppearanceID`, `RaceMask1`, `RaceMask2`, `VerifiedBuild`) VALUES
(4975, '', 3, -1, 0, 0, 0, -1, 0, -1, -1, 70790), -- Fresh (both sexes)
(4976, '', 3, -1, 0, 0, 0, -1, 0, -1, -1, 70790), -- China skin colours, male
(4977, '', 3, -1, 0, 0, 0, -1, 0, -1, -1, 70790); -- China skin colours, female

-- Send them to the client: ChrCustomizationReq 0x61431A65
INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES
(9570005, 957000501, 1631787621, 4975, 1, 70790),
(9570005, 957000502, 1631787621, 4976, 1, 70790),
(9570005, 957000503, 1631787621, 4977, 1, 70790);
