-- Undead "Skin Type: Fresh" for everyone (docs/china-undead.md, test 4).
-- Blizzard's normal HD Undead models already hold covered-up "Fresh" pieces (geosets 2902, 3002, 1902) next to the
-- bony ones (2901, 3001, 1901); the Fresh choice (male 6529, female 6526) switches them. Forever hides it behind
-- requirement 4975, whose OverrideArchive 1 means "only with the client's China setting on". This sends both choice
-- rows again with Bony's requirement 55, so every Undead can pick Fresh in the creator and at the barber. With the
-- "Intact" jaw it should come close to the China look; the China model's body mesh is fuller still (to compare).
--
-- It also removes the skinned-model tests (pushes 9570000-9570002: China, China (B), China (C), Normal body), which
-- all drew the body black. A client drops the rows of a push the realm stops sending.
-- Hotfix push 9570003. Re-runnable. Restart the worldserver afterwards.
-- Undo: DELETE FROM `hotfix_data` WHERE `Id` = 9570003; DELETE FROM `chr_customization_choice` WHERE `ID` IN (6526, 6529);

-- the skinned-model tests
DELETE FROM `hotfix_data` WHERE `Id` IN (9570000, 9570001, 9570002);
DELETE FROM `chr_customization_choice` WHERE `ID` BETWEEN 954601 AND 954608;
DELETE FROM `chr_customization_element` WHERE `ID` BETWEEN 9546001 AND 9546226;
DELETE FROM `hotfix_blob` WHERE `TableHash` = 1436347628 AND `RecordId` BETWEEN 954601 AND 954608;

-- Fresh with Bony's requirement (every other field as in the Forever build 1.60.1.70790)
DELETE FROM `hotfix_data` WHERE `Id` = 9570003;
DELETE FROM `chr_customization_choice` WHERE `ID` IN (6526, 6529);
INSERT INTO `chr_customization_choice` (`Name`, `ID`, `ChrCustomizationOptionID`, `ChrCustomizationReqID`,
  `ChrCustomizationVisReqID`, `SortOrder`, `UiOrderIndex`, `Flags`, `AddedInPatch`, `SoundKitID`, `SwatchColor1`, `SwatchColor2`,
  `VerifiedBuild`) VALUES
('Fresh', 6529, 567, 55, 0, 2, 2, 0, 90001, 0, 0, 0, 70790), -- male
('Fresh', 6526, 568, 55, 0, 2, 2, 0, 90001, 0, 0, 0, 70790); -- female

-- Send them to the client: ChrCustomizationChoice 0x681D0F3D
INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES
(9570003, 957000301, 1746734909, 6529, 1, 70790),
(9570003, 957000302, 1746734909, 6526, 1, 70790);
