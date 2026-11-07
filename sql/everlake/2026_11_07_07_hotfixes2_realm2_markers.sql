-- Gate 5, tests 4-6 (docs/era-data.md): realm 2's switch markers, in realm 2's hotfix database (hotfixes2).
-- Two spell names every character has, renamed per realm, so a glance at the spellbook (or the EverlakeSwitch addon)
-- shows which realm's rows the client is using:
--   Attack (6603):      push 9550000, unique id 955000001 - the SAME push, unique id and record as realm 1's marker,
--                       with other text. Probes a shared client cache: if the client keys rows by push id, one realm
--                       shows the other realm's name.
--   Hearthstone (8690): push 9560001 - realm 2's own push range (9560000-9569999). Realm 1 uses 9550001.
-- The Test 1 class kit (pushes 9540010-9540030) is realm 2 only: sql/everlake/2026_11_07_01/03/05.
-- Re-runnable; undo: the two DELETEs.
DELETE FROM `hotfix_data` WHERE `Id` IN (9550000, 9550001, 9560001);
DELETE FROM `spell_name` WHERE `ID` IN (6603, 8690);
INSERT INTO `spell_name` (`ID`, `Name`, `VerifiedBuild`) VALUES
(6603, 'Attack (realm 2)', 70790),
(8690, 'Hearthstone (realm 2)', 70790);
INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES
(9550000, 955000001, 1187407512, 6603, 1, 70790),
(9560001, 956000101, 1187407512, 8690, 1, 70790);
