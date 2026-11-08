-- China Undead test, part 3 (docs/china-undead.md): "Normal body" per sex. China and China (C) drew the China
-- body black, with the character skin and with a named texture alike. This attaches Blizzard's own Undead model
-- (959310 male, 997378 female; bones inline, unchanged) the same way, with Fresh's parts. Textured = skinned
-- bodies work and the China model's borrowed skeleton (SKID, no bones) is the problem; black = any skinned body
-- draws black on this model. No new files. Hotfix push 9570002. Re-runnable; the DELETEs undo it.
-- Restart the worldserver afterwards.

DELETE FROM `hotfix_data` WHERE `Id` = 9570002;
DELETE FROM `chr_customization_choice` WHERE `ID` IN (954607, 954608);
DELETE FROM `chr_customization_element` WHERE `ID` BETWEEN 9546201 AND 9546226;
DELETE FROM `hotfix_blob` WHERE `TableHash` = 1436347628 AND `RecordId` IN (954607, 954608);

INSERT INTO `chr_customization_choice` (`Name`, `ID`, `ChrCustomizationOptionID`, `ChrCustomizationReqID`,
  `ChrCustomizationVisReqID`, `SortOrder`, `UiOrderIndex`, `Flags`, `AddedInPatch`, `SoundKitID`, `SwatchColor1`, `SwatchColor2`,
  `VerifiedBuild`) VALUES
('Normal body', 954607, 567, 55, 0, 6, 6, 0, 90001, 0, 0, 0, 70790), -- male
('Normal body', 954608, 568, 55, 0, 6, 6, 0, 90001, 0, 0, 0, 70790); -- female

INSERT INTO `chr_customization_element` (`ID`, `ChrCustomizationChoiceID`, `RelatedChrCustomizationChoiceID`, `ChrCustomizationGeosetID`, `ChrCustomizationSkinnedModelID`, `ChrCustomizationMaterialID`, `ChrCustomizationBoneSetID`, `ChrCustomizationCondModelID`, `ChrCustomizationDisplayInfoID`, `ChrCustItemGeoModifyID`, `ChrCustomizationVoiceID`, `AnimKitID`, `ParticleColorID`, `ChrCustGeoComponentLinkID`, `VerifiedBuild`) VALUES
(9546201, 954607, 0, 2109, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546202, 954607, 0, 203, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546203, 954607, 0, 2107, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546204, 954607, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 70790),
(9546205, 954607, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 70790),
(9546206, 954607, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 70790),
(9546207, 954607, 0, 0, 0, 0, 0, 0, 0, 5, 0, 0, 0, 0, 70790),
(9546208, 954607, 0, 0, 0, 0, 0, 0, 0, 6, 0, 0, 0, 0, 70790),
(9546209, 954607, 0, 0, 0, 0, 0, 0, 0, 7, 0, 0, 0, 0, 70790),
(9546210, 954607, 0, 0, 0, 0, 0, 0, 0, 8, 0, 0, 0, 0, 70790),
(9546211, 954607, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 70790),
(9546212, 954607, 0, 0, 0, 0, 0, 0, 0, 10, 0, 0, 0, 0, 70790),
(9546213, 954607, 0, 0, 954607, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546214, 954608, 0, 2109, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546215, 954608, 0, 203, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546216, 954608, 0, 2107, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546217, 954608, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 70790),
(9546218, 954608, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 70790),
(9546219, 954608, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 70790),
(9546220, 954608, 0, 0, 0, 0, 0, 0, 0, 5, 0, 0, 0, 0, 70790),
(9546221, 954608, 0, 0, 0, 0, 0, 0, 0, 6, 0, 0, 0, 0, 70790),
(9546222, 954608, 0, 0, 0, 0, 0, 0, 0, 7, 0, 0, 0, 0, 70790),
(9546223, 954608, 0, 0, 0, 0, 0, 0, 0, 8, 0, 0, 0, 0, 70790),
(9546224, 954608, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 70790),
(9546225, 954608, 0, 0, 0, 0, 0, 0, 0, 10, 0, 0, 0, 0, 70790),
(9546226, 954608, 0, 0, 954608, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790);

INSERT INTO `hotfix_blob` (`TableHash`, `RecordId`, `locale`, `Blob`, `VerifiedBuild`) VALUES
(1436347628, 954607, 'enUS', X'4ea30e000000000000ffffffff00000000', 70790), -- male Normal body: model 959310, geoset type 0 id 0, modifier -1, flags 0
(1436347628, 954608, 'enUS', X'02380f000000000000ffffffff00000000', 70790); -- female Normal body: model 997378, geoset type 0 id 0, modifier -1, flags 0

-- Send them to the client: ChrCustomizationChoice 0x681D0F3D, ChrCustomizationElement 0xD6D051EC, ChrCustomizationSkinnedModel 0x559CECEC
INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES
(9570002, 957000201, 1436347628, 954607, 1, 70790),
(9570002, 957000202, 1436347628, 954608, 1, 70790),
(9570002, 957000203, 1746734909, 954607, 1, 70790),
(9570002, 957000204, 1746734909, 954608, 1, 70790),
(9570002, 957000205, 3603976684, 9546201, 1, 70790),
(9570002, 957000206, 3603976684, 9546202, 1, 70790),
(9570002, 957000207, 3603976684, 9546203, 1, 70790),
(9570002, 957000208, 3603976684, 9546204, 1, 70790),
(9570002, 957000209, 3603976684, 9546205, 1, 70790),
(9570002, 957000210, 3603976684, 9546206, 1, 70790),
(9570002, 957000211, 3603976684, 9546207, 1, 70790),
(9570002, 957000212, 3603976684, 9546208, 1, 70790),
(9570002, 957000213, 3603976684, 9546209, 1, 70790),
(9570002, 957000214, 3603976684, 9546210, 1, 70790),
(9570002, 957000215, 3603976684, 9546211, 1, 70790),
(9570002, 957000216, 3603976684, 9546212, 1, 70790),
(9570002, 957000217, 3603976684, 9546213, 1, 70790),
(9570002, 957000218, 3603976684, 9546214, 1, 70790),
(9570002, 957000219, 3603976684, 9546215, 1, 70790),
(9570002, 957000220, 3603976684, 9546216, 1, 70790),
(9570002, 957000221, 3603976684, 9546217, 1, 70790),
(9570002, 957000222, 3603976684, 9546218, 1, 70790),
(9570002, 957000223, 3603976684, 9546219, 1, 70790),
(9570002, 957000224, 3603976684, 9546220, 1, 70790),
(9570002, 957000225, 3603976684, 9546221, 1, 70790),
(9570002, 957000226, 3603976684, 9546222, 1, 70790),
(9570002, 957000227, 3603976684, 9546223, 1, 70790),
(9570002, 957000228, 3603976684, 9546224, 1, 70790),
(9570002, 957000229, 3603976684, 9546225, 1, 70790),
(9570002, 957000230, 3603976684, 9546226, 1, 70790);
