-- Undead Skin Color in the creator and at the barber, with Blizzard's China skin colours (docs/china-undead.md).
-- Forever's Undead Skin Color options (58 male, 63 female) have Flags 16, every other playable race's have 80
-- (16 + 64): the missing 64 hides the option. This sends both with 80. The six China skin colours of each sex
-- (male 6425-6430, female 6371-6376: textures skin00_12-17_hd, flesh painted over the bones, same swatches as
-- colours 0-5) need requirement 4976/4977 (OverrideArchive 1 = China setting only); they get the normal colours'
-- requirement (61 male, 66 female). Every other field is as in the Forever build 1.60.1.70790.
-- Hotfix push 9570004. Re-runnable. Restart the worldserver afterwards.
-- Undo: DELETE FROM `hotfix_data` WHERE `Id` = 9570004; then the two row DELETEs below.

DELETE FROM `hotfix_data` WHERE `Id` = 9570004;
DELETE FROM `chr_customization_option` WHERE `ID` IN (58, 63);
DELETE FROM `chr_customization_choice` WHERE `ID` IN (6425, 6426, 6427, 6428, 6429, 6430, 6371, 6372, 6373, 6374, 6375, 6376);

INSERT INTO `chr_customization_option` (`Name`, `ID`, `SecondaryID`, `Flags`, `ChrModelID`, `SortIndex`,
  `ChrCustomizationCategoryID`, `OptionType`, `BarberShopCostModifier`, `ChrCustomizationID`, `ChrCustomizationReqID`,
  `UiOrderIndex`, `AddedInPatch`, `VerifiedBuild`) VALUES
('Skin Color', 58, 58, 80, 9, 1, 74, 0, 0, 1, 0, 0, 90001, 70790), -- male
('Skin Color', 63, 63, 80, 10, 1, 74, 0, 0, 1, 0, 0, 90001, 70790); -- female

INSERT INTO `chr_customization_choice` (`Name`, `ID`, `ChrCustomizationOptionID`, `ChrCustomizationReqID`,
  `ChrCustomizationVisReqID`, `SortOrder`, `UiOrderIndex`, `Flags`, `AddedInPatch`, `SoundKitID`, `SwatchColor1`, `SwatchColor2`,
  `VerifiedBuild`) VALUES
('', 6425, 58, 61, 0, 12, 40, 0, 90001, 0, -5919879, 0, 70790), -- male China colour 12
('', 6426, 58, 61, 0, 13, 41, 0, 90001, 0, -7426696, 0, 70790), -- male China colour 13
('', 6427, 58, 61, 0, 14, 42, 0, 90001, 0, -8344675, 0, 70790), -- male China colour 14
('', 6428, 58, 61, 0, 15, 43, 0, 90001, 0, -7757397, 0, 70790), -- male China colour 15
('', 6429, 58, 61, 0, 16, 44, 0, 90001, 0, -7500875, 0, 70790), -- male China colour 16
('', 6430, 58, 61, 0, 17, 45, 0, 90001, 0, -6711632, 0, 70790), -- male China colour 17
('', 6371, 63, 66, 0, 12, 31, 0, 90001, 0, -6965871, 0, 70790), -- female China colour 12
('', 6372, 63, 66, 0, 13, 32, 0, 90001, 0, -6700414, 0, 70790), -- female China colour 13
('', 6373, 63, 66, 0, 14, 36, 0, 90001, 0, -5010007, 0, 70790), -- female China colour 14
('', 6374, 63, 66, 0, 15, 34, 0, 90001, 0, -6643397, 0, 70790), -- female China colour 15
('', 6375, 63, 66, 0, 16, 35, 0, 90001, 0, -9456760, 0, 70790), -- female China colour 16
('', 6376, 63, 66, 0, 17, 33, 0, 90001, 0, -8538777, 0, 70790); -- female China colour 17

-- Send them to the client: ChrCustomizationOption 0x2FB7905B, ChrCustomizationChoice 0x681D0F3D
INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES
(9570004, 957000401, 800559195, 58, 1, 70790),
(9570004, 957000402, 800559195, 63, 1, 70790),
(9570004, 957000403, 1746734909, 6425, 1, 70790),
(9570004, 957000404, 1746734909, 6426, 1, 70790),
(9570004, 957000405, 1746734909, 6427, 1, 70790),
(9570004, 957000406, 1746734909, 6428, 1, 70790),
(9570004, 957000407, 1746734909, 6429, 1, 70790),
(9570004, 957000408, 1746734909, 6430, 1, 70790),
(9570004, 957000409, 1746734909, 6371, 1, 70790),
(9570004, 957000410, 1746734909, 6372, 1, 70790),
(9570004, 957000411, 1746734909, 6373, 1, 70790),
(9570004, 957000412, 1746734909, 6374, 1, 70790),
(9570004, 957000413, 1746734909, 6375, 1, 70790),
(9570004, 957000414, 1746734909, 6376, 1, 70790);
