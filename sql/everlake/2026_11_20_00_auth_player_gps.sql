-- Players can use .gps, so bug reports can carry the exact map, zone, area, phase and coordinates.
-- Stock TrinityCore links permission 505 "Command: gps" only to role 196 (Administrator Commands). Moving it to role
-- 199 (Player Commands) gives it to every account: 199 hangs off 195 (Sec Level Player), and the moderator,
-- gamemaster and administrator levels all include 195, so GMs keep it. .gps only reads the caller's (or their
-- target's) position; it changes nothing.
-- Applied by the worldserver's updater on start (the Dockerfile copies it to sql/custom/auth). RBAC is read at
-- worldserver start, so it takes effect after a restart on the new image.
-- Undo: DELETE FROM `rbac_linked_permissions` WHERE `id` = 199 AND `linkedId` = 505;
--       INSERT IGNORE INTO `rbac_linked_permissions` (`id`, `linkedId`) VALUES (196, 505);
DELETE FROM `rbac_linked_permissions` WHERE `linkedId` = 505 AND `id` IN (196, 199);
INSERT INTO `rbac_linked_permissions` (`id`, `linkedId`) VALUES (199, 505);
