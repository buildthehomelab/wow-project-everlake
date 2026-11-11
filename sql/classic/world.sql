-- Classic world database only. Keep quests, characters and spawns on logical map 0.
INSERT INTO `terrain_swap_defaults` (`MapId`, `TerrainSwapMap`, `Comment`)
VALUES (0, 9000, 'Classic Eastern Kingdoms terrain');

-- The Human Warrior smoke test starts at Northshire rather than the NPE.
UPDATE playercreateinfo
SET npe_map=NULL, npe_position_x=NULL, npe_position_y=NULL, npe_position_z=NULL,
    npe_orientation=NULL, npe_transport_guid=NULL, npe_intro_scene_id=NULL
WHERE race=1 AND class=1;
