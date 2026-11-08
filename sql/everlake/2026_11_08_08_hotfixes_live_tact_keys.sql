-- Every TACT key live WoW Forever sends that the core (2ae1313e9f) lacks or holds with other bytes:
-- 2 missing, 0 different. A key unlocks client data Blizzard ships encrypted; the client
-- reads that data only after a server sends the key as a TactKey hotfix.
-- Source: live Forever hotfix cache DBCache.bin, build 70862 (public mirror, see
-- tools/live-hotfixes/dbcache.py). Made with tools/live-hotfixes/tact_keys.py. Re-runnable.
-- Hotfix push 9590000.
-- Undo: DELETE FROM `hotfix_data` WHERE `Id` = 9590000; and the tact_key rows below (the core's own come back
-- when its files are applied again).

DELETE FROM `tact_key` WHERE `ID` IN (8283,8321);
INSERT INTO `tact_key` (`ID`,`Key1`,`Key2`,`Key3`,`Key4`,`Key5`,`Key6`,`Key7`,`Key8`,`Key9`,`Key10`,`Key11`,`Key12`,`Key13`,`Key14`,`Key15`,`Key16`,`VerifiedBuild`) VALUES
(8283,211,28,116,254,55,5,175,87,72,136,228,162,48,120,84,129,70862),
(8321,88,14,186,23,67,169,40,158,31,189,90,205,155,127,217,155,70862);

DELETE FROM `hotfix_data` WHERE `Id` = 9590000;
INSERT INTO `hotfix_data` (`Id`,`UniqueId`,`TableHash`,`RecordId`,`Status`,`VerifiedBuild`) VALUES
(9590000,959000001,3744420815,8283,1,70862),
(9590000,959000002,3744420815,8321,1,70862);
