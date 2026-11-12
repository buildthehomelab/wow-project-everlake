-- The four ruleset cards match the realm names: Forever, Classic, Retail, PTR, in that order.
-- Card title, text, icon and order are client data (AvailableSuperDistrict, hash 0x45952E6E = 1167404654, layout
-- 87BD1F4D; see 2026_11_08_07_hotfixes_forever_card.sql for the record bytes). Each row maps one card to a realm by
-- content set (auth.realmlist.contentSetId):
--   row 3, SuperDistrictID 2, content set 137: "Forever" (Blizzard: Normal), realm 70, OrderIndex 1
--   row 4, SuperDistrictID 3, content set 138: "Classic" (Blizzard: Roleplay), realm 71, OrderIndex 2
--   row 2, SuperDistrictID 1, content set 136: "Retail"  (Blizzard: PvP), realm 72, OrderIndex 3 (not open yet)
--   row 5, SuperDistrictID 4, content set 140: "PTR"     (Blizzard: Hardcore), realm 73, OrderIndex 4; the Hardcore
--          card's skull background and glow atlases are left empty, so it draws like the other cards
-- Each card's text says what the ruleset is:
--   Forever: World of Warcraft Forever, levels 1 to 60: Forever's zones, quests and class changes. Quest and explore at your own pace; fight other players only when you choose to.
--   Classic: Classic Era as it first was, levels 1 to 60: the original zones, quests, classes and talents, with nothing added. Fight other players only when you choose to.
--   Retail: Modern World of Warcraft with the newest expansions, zones and classes. Not open yet: this ruleset comes later.
--   PTR: The test realm: new changes land here first, before Forever, Classic or Retail. Characters and progress may be reset. Testers only.
-- Icons stay Blizzard's. English only (other locales keep Blizzard's text).
-- Push 9580001 replaces push 9580000 (the Forever card alone): a new push id, so clients that cached 9580000 fetch
-- the rows again. Re-runnable. Goes into every realm's hotfix database (scripts/ptr-setup.sh cards; the image's
-- updater also applies it from sql/custom/hotfixes). A worldserver reads hotfixes when it starts, so each realm shows
-- the new cards after its next restart.
-- The client gets hotfixes from a worldserver: the cards read like this on the RULESET screen opened from character
-- select. Before the first realm, at the very first login, it may still show Blizzard's names.
-- Undo: DELETE FROM `hotfix_data` WHERE `Id` = 9580001; DELETE FROM `hotfix_blob` WHERE `TableHash` = 1167404654 AND `RecordId` IN (2, 4, 5);
--       then run 2026_11_08_07_hotfixes_forever_card.sql again.

DELETE FROM `hotfix_data` WHERE `Id` IN (9580000, 9580001);
DELETE FROM `hotfix_blob` WHERE `TableHash` = 1167404654 AND `RecordId` IN (2, 3, 4, 5);
INSERT INTO `hotfix_blob` (`TableHash`, `RecordId`, `locale`, `Blob`, `VerifiedBuild`) VALUES
(1167404654, 3, 'enUS', X'466f726576657200576f726c64206f6620576172637261667420466f72657665722c206c6576656c73203120746f2036303a20466f72657665722773207a6f6e65732c2071756573747320616e6420636c617373206368616e6765732e20517565737420616e64206578706c6f726520617420796f7572206f776e20706163653b206669676874206f7468657220706c6179657273206f6e6c79207768656e20796f752063686f6f736520746f2e00000003000000020000009324770001000000', 70790), -- Forever
(1167404654, 4, 'enUS', X'436c617373696300436c617373696320457261206173206974206669727374207761732c206c6576656c73203120746f2036303a20746865206f726967696e616c207a6f6e65732c207175657374732c20636c617373657320616e642074616c656e74732c2077697468206e6f7468696e672061646465642e204669676874206f7468657220706c6179657273206f6e6c79207768656e20796f752063686f6f736520746f2e0000000400000003000000c004020002000000', 70790), -- Classic
(1167404654, 2, 'enUS', X'52657461696c004d6f6465726e20576f726c64206f66205761726372616674207769746820746865206e657765737420657870616e73696f6e732c207a6f6e657320616e6420636c61737365732e204e6f74206f70656e207965743a20746869732072756c6573657420636f6d6573206c617465722e00000002000000010000006c9b030003000000', 70790), -- Retail
(1167404654, 5, 'enUS', X'505452005468652074657374207265616c6d3a206e6577206368616e676573206c616e6420686572652066697273742c206265666f726520466f72657665722c20436c6173736963206f722052657461696c2e204368617261637465727320616e642070726f6772657373206d61792062652072657365742e2054657374657273206f6e6c792e0000000500000004000000c504020004000000', 70790); -- PTR

-- Send them to the client: AvailableSuperDistrict 0x45952E6E
INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES
(9580001, 958000101, 1167404654, 3, 1, 70790),
(9580001, 958000102, 1167404654, 4, 1, 70790),
(9580001, 958000103, 1167404654, 2, 1, 70790),
(9580001, 958000104, 1167404654, 5, 1, 70790);
