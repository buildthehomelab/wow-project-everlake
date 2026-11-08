-- The ruleset card says "Forever" with a short text instead of Blizzard's "Normal" card.
-- The card's title, text and icon are client data: AvailableSuperDistrict row 3 (SuperDistrictID 2 = content set 137,
-- our realm 70). Blizzard's row: "Normal", "This ruleset allows you to focus on adventuring and fighting monsters
-- while allowing you to fight other players at your own discretion.", icon 7808147, OrderIndex 1.
-- The core has no hotfix table for AvailableSuperDistrict, so the row goes to hotfix_blob as the client's record bytes:
-- the four strings in field order, null-terminated (title, text, no background atlas, no glow atlas), then ID 3,
-- SuperDistrictID 2, IconFileDataID 7808147, OrderIndex 1 as 32-bit ints (layout 87BD1F4D, same in 70790 and 70862).
-- Table hash 0x45952E6E (AvailableSuperDistrict.db2 header). English only: other locales get status Invalid from the
-- core and keep Blizzard's text.
-- New text: "World of Warcraft Forever, levels 1 to 60. Quest, explore and fight monsters at your own pace; fight other
-- players only when you choose to."
-- Hotfix push 9580000. Re-runnable. Applied by the worldserver's updater on start, before hotfixes load (the
-- Dockerfile copies it to sql/custom/hotfixes).
-- Not seen in game yet: the client gets hotfixes once it reaches a worldserver, so the card should read Forever on
-- the RULESET screen opened from character select, and before that only if the client keeps cached rows from its
-- last realm.
-- Undo: DELETE FROM `hotfix_data` WHERE `Id` = 9580000; DELETE FROM `hotfix_blob` WHERE `TableHash` = 1167404654 AND `RecordId` = 3;

DELETE FROM `hotfix_data` WHERE `Id` = 9580000;
DELETE FROM `hotfix_blob` WHERE `TableHash` = 1167404654 AND `RecordId` = 3;
INSERT INTO `hotfix_blob` (`TableHash`, `RecordId`, `locale`, `Blob`, `VerifiedBuild`) VALUES
(1167404654, 3, 'enUS', X'466f726576657200576f726c64206f6620576172637261667420466f72657665722c206c6576656c73203120746f2036302e2051756573742c206578706c6f726520616e64206669676874206d6f6e737465727320617420796f7572206f776e20706163653b206669676874206f7468657220706c6179657273206f6e6c79207768656e20796f752063686f6f736520746f2e00000003000000020000009324770001000000', 70790);

-- Send it to the client: AvailableSuperDistrict 0x45952E6E
INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES
(9580000, 958000001, 1167404654, 3, 1, 70790);
