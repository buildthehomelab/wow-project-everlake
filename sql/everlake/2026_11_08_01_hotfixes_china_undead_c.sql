-- China Undead test, part 2 (docs/china-undead.md): "China (C)" per sex. The first test (push 9570000) drew the
-- China body black: a skinned model gets no character skin. These models name the China skin texture (skin colour
-- 0) in place of the character skin: 95450017 (male, texture 95450018) and 95450019 (female, texture 95450020).
-- Otherwise the same as "China": Fresh's parts plus the body as a skinned model. Hotfix push 9570001.
-- Re-runnable; the DELETEs undo it. Restart the worldserver afterwards.

DELETE FROM `hotfix_data` WHERE `Id` = 9570001;
DELETE FROM `chr_customization_choice` WHERE `ID` IN (954605, 954606);
DELETE FROM `chr_customization_element` WHERE `ID` BETWEEN 9546101 AND 9546126;
DELETE FROM `hotfix_blob` WHERE `TableHash` = 1436347628 AND `RecordId` IN (954605, 954606);

INSERT INTO `chr_customization_choice` (`Name`, `ID`, `ChrCustomizationOptionID`, `ChrCustomizationReqID`,
  `ChrCustomizationVisReqID`, `SortOrder`, `UiOrderIndex`, `Flags`, `AddedInPatch`, `SoundKitID`, `SwatchColor1`, `SwatchColor2`,
  `VerifiedBuild`) VALUES
('China (C)', 954605, 567, 55, 0, 5, 5, 0, 90001, 0, 0, 0, 70790), -- male
('China (C)', 954606, 568, 55, 0, 5, 5, 0, 90001, 0, 0, 0, 70790); -- female

INSERT INTO `chr_customization_element` (`ID`, `ChrCustomizationChoiceID`, `RelatedChrCustomizationChoiceID`, `ChrCustomizationGeosetID`, `ChrCustomizationSkinnedModelID`, `ChrCustomizationMaterialID`, `ChrCustomizationBoneSetID`, `ChrCustomizationCondModelID`, `ChrCustomizationDisplayInfoID`, `ChrCustItemGeoModifyID`, `ChrCustomizationVoiceID`, `AnimKitID`, `ParticleColorID`, `ChrCustGeoComponentLinkID`, `VerifiedBuild`) VALUES
(9546101, 954605, 0, 2109, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546102, 954605, 0, 203, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546103, 954605, 0, 2107, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546104, 954605, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 70790),
(9546105, 954605, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 70790),
(9546106, 954605, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 70790),
(9546107, 954605, 0, 0, 0, 0, 0, 0, 0, 5, 0, 0, 0, 0, 70790),
(9546108, 954605, 0, 0, 0, 0, 0, 0, 0, 6, 0, 0, 0, 0, 70790),
(9546109, 954605, 0, 0, 0, 0, 0, 0, 0, 7, 0, 0, 0, 0, 70790),
(9546110, 954605, 0, 0, 0, 0, 0, 0, 0, 8, 0, 0, 0, 0, 70790),
(9546111, 954605, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 70790),
(9546112, 954605, 0, 0, 0, 0, 0, 0, 0, 10, 0, 0, 0, 0, 70790),
(9546113, 954605, 0, 0, 954605, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546114, 954606, 0, 2109, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546115, 954606, 0, 203, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546116, 954606, 0, 2107, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790),
(9546117, 954606, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 70790),
(9546118, 954606, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 70790),
(9546119, 954606, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 70790),
(9546120, 954606, 0, 0, 0, 0, 0, 0, 0, 5, 0, 0, 0, 0, 70790),
(9546121, 954606, 0, 0, 0, 0, 0, 0, 0, 6, 0, 0, 0, 0, 70790),
(9546122, 954606, 0, 0, 0, 0, 0, 0, 0, 7, 0, 0, 0, 0, 70790),
(9546123, 954606, 0, 0, 0, 0, 0, 0, 0, 8, 0, 0, 0, 0, 70790),
(9546124, 954606, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 70790),
(9546125, 954606, 0, 0, 0, 0, 0, 0, 0, 10, 0, 0, 0, 0, 70790),
(9546126, 954606, 0, 0, 954606, 0, 0, 0, 0, 0, 0, 0, 0, 0, 70790);

INSERT INTO `hotfix_blob` (`TableHash`, `RecordId`, `locale`, `Blob`, `VerifiedBuild`) VALUES
(1436347628, 954605, 'enUS', X'a173b0050000000000ffffffff00000000', 70790), -- male China (C): model 95450017, geoset type 0 id 0, modifier -1, flags 0
(1436347628, 954606, 'enUS', X'a373b0050000000000ffffffff00000000', 70790); -- female China (C): model 95450019, geoset type 0 id 0, modifier -1, flags 0

-- Send them to the client: ChrCustomizationChoice 0x681D0F3D, ChrCustomizationElement 0xD6D051EC, ChrCustomizationSkinnedModel 0x559CECEC
INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES
(9570001, 957000101, 1436347628, 954605, 1, 70790),
(9570001, 957000102, 1436347628, 954606, 1, 70790),
(9570001, 957000103, 1746734909, 954605, 1, 70790),
(9570001, 957000104, 1746734909, 954606, 1, 70790),
(9570001, 957000105, 3603976684, 9546101, 1, 70790),
(9570001, 957000106, 3603976684, 9546102, 1, 70790),
(9570001, 957000107, 3603976684, 9546103, 1, 70790),
(9570001, 957000108, 3603976684, 9546104, 1, 70790),
(9570001, 957000109, 3603976684, 9546105, 1, 70790),
(9570001, 957000110, 3603976684, 9546106, 1, 70790),
(9570001, 957000111, 3603976684, 9546107, 1, 70790),
(9570001, 957000112, 3603976684, 9546108, 1, 70790),
(9570001, 957000113, 3603976684, 9546109, 1, 70790),
(9570001, 957000114, 3603976684, 9546110, 1, 70790),
(9570001, 957000115, 3603976684, 9546111, 1, 70790),
(9570001, 957000116, 3603976684, 9546112, 1, 70790),
(9570001, 957000117, 3603976684, 9546113, 1, 70790),
(9570001, 957000118, 3603976684, 9546114, 1, 70790),
(9570001, 957000119, 3603976684, 9546115, 1, 70790),
(9570001, 957000120, 3603976684, 9546116, 1, 70790),
(9570001, 957000121, 3603976684, 9546117, 1, 70790),
(9570001, 957000122, 3603976684, 9546118, 1, 70790),
(9570001, 957000123, 3603976684, 9546119, 1, 70790),
(9570001, 957000124, 3603976684, 9546120, 1, 70790),
(9570001, 957000125, 3603976684, 9546121, 1, 70790),
(9570001, 957000126, 3603976684, 9546122, 1, 70790),
(9570001, 957000127, 3603976684, 9546123, 1, 70790),
(9570001, 957000128, 3603976684, 9546124, 1, 70790),
(9570001, 957000129, 3603976684, 9546125, 1, 70790),
(9570001, 957000130, 3603976684, 9546126, 1, 70790);
