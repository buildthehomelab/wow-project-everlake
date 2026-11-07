-- Gate 5, tests 4-6 (docs/era-data.md): realm 1's switch markers, in realm 1's hotfix database (hotfixes).
-- The counterpart of 2026_11_07_07_hotfixes2_realm2_markers.sql:
--   Attack (6603):      push 9550000, unique id 955000001 - the same push and record as realm 2's, other text
--   Hearthstone (8690): push 9550001 - realm 1's own push range (9550000-9559999). Realm 2 uses 9560001.
-- Neither record has a row in Forever's own hotfixes (checked against TDB_full_hotfixes_forever_2026_10_14).
-- Re-runnable; undo: the two DELETEs.
DELETE FROM `hotfix_data` WHERE `Id` IN (9550000, 9550001, 9560001);
DELETE FROM `spell_name` WHERE `ID` IN (6603, 8690);
INSERT INTO `spell_name` (`ID`, `Name`, `VerifiedBuild`) VALUES
(6603, 'Attack (realm 1)', 70790),
(8690, 'Hearthstone (realm 1)', 70790);
INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES
(9550000, 955000001, 1187407512, 6603, 1, 70790),
(9550001, 955000101, 1187407512, 8690, 1, 70790);
