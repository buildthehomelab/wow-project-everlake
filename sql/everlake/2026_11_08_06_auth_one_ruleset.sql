-- One ruleset card at login: Forever (realm 70, content set 137, the client's "Normal" card).
-- The client shows one RULESET card per content set among the listed realms (docs/era-data.md). The fork's
-- placeholder realms 71 "Forever PvP" (136), 72 "Forever RP" (138) and 73 "Forever Hardcore" (140) have no
-- worldserver but are listed, so they add the PvP, Roleplay and Hardcore cards. flag 3 takes them out of the list
-- (the core reads `realmlist` WHERE flag <> 3), and the login server only offers a card that has a listed realm.
-- The rows stay, so the realms can come back as era realms later. The names in the WHERE keep this off a row that
-- was already given another use (the spike's realm 2 "Everlake Two" was row 71).
-- Applied by the worldserver's updater on start (the Dockerfile copies it to sql/custom/auth).
-- Card title and text: sql/everlake/2026_11_08_07_hotfixes_forever_card.sql.
-- Undo: UPDATE `realmlist` SET `flag` = 0 WHERE `id` IN (71, 72, 73) AND `name` IN ('Forever PvP', 'Forever RP', 'Forever Hardcore');
UPDATE `realmlist` SET `flag` = 3
WHERE `id` IN (71, 72, 73) AND `name` IN ('Forever PvP', 'Forever RP', 'Forever Hardcore');
