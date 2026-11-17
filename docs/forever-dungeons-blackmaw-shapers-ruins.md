# Blackmaw Hold, The Shaper's Terrace, Ruins of Lordaeron: what each needs

A plan, written 2026-11-17. Nothing here is built yet.

The tracker's Spawns page listed 10 bosses in these three places as "not on Wowhead (Forever)". The places are
three of WoW Forever's nine new five-player dungeons, and all three are live on Blizzard's realms.

## The 10 tracker rows point at the wrong creatures

The locator matches a boss to every creature template that has the same name, on any map
(`tools/ft/locator.py`, the bosses step). All 10 ids are retail creatures that share a name with a Forever boss.
Wowhead has no Forever positions for them because Forever doesn't use them:

| Boss (encounter) | Ids the tracker listed | Forever creature (Wowhead / QuestieDB) |
|---|---|---|
| Unbound Spirit (3336) | 230522, 244914 | 247231 |
| Lordaeron Captain (3408) | 32414 | 255699 (rare elite) |
| Bolt (3505) | 161512 | 262081 |
| Cinder (3503) | 58525, 58520 | 261974 |
| Direhorn Matriarch (3507) | 123427 | 262127 |
| Thunderhoof (3500) | 146113, 90922, 76389 | 261812 |

So none of the 10 should be spawned. The real creatures have no `creature_template` row on our server, except
Viktor the Vile (256035) and Snowtalon (262297). The tracker doesn't list them at all, because the locator only
reports templates that exist. Tracker follow-up: match a boss to a creature through the dungeon's own creature list
(QuestieDB `zoneID`, or Wowhead's zone page), not through a name search across all templates.

## What the three places share

| | Blackmaw Hold | The Shaper's Terrace | Ruins of Lordaeron |
|---|---|---|---|
| Map id | 2974 | 3001 | 2999 |
| Client `InstanceType` | 1 (dungeon) | 1 (dungeon) | 1 (dungeon) |
| Players | 5 | 5 | 5 |
| Level (ContentTuning) | 55 (guides: 55-60) | 60 (guides: 58-60) | 15, target 27 (guides: 15-22) |
| Zone area | 16554 (internal name `TimbermawHold`) | 16667 | 16611 |
| Encounters | 7 | 11 | 7 |
| Map tiles | 25 | 12 | 9 |
| Coordinates | its own space (tiles 24-28) | Kalimdor's: a copy of north Un'Goro | Eastern Kingdoms': a copy of the Undercity ruins |
| Entrance (guides) | Azshara 38.7, 33.4 (furbolg tunnel). The portal is deep in it, on the Winterspring map at 66.6, 84.4 = Kalimdor (4538, -5045) | Un'Goro 48.1, 6.1 = Kalimdor (-6117, -1246), top of the titan stairs | Undercity ruins, stairs left of the front gate: already built from a sniff |
| `instance_template` | none | none | `classic_instance_ruins_of_lordaeron` |
| Spawns | 0 | 0 | 305 creatures, 120 objects (sniff) |

None of them is a delve, a scenario or an arena. The client's arena called Ruins of Lordaeron is a different map
(572, `arena_ruins_of_lordaeron.cpp`), so no arena work is needed.

**Terrain:** the extract (from Blizzard's CDN, `docker/extract.sh`, which extracts every map) has `.map` tiles,
vmaps and mmaps for all three maps. The tracker shows "—" for mmaps on all three, Ruins included, so either its check can't see the
mmaps folder or the server's copy lacks them. Confirm on the server before placing spawns on the navmesh.

**No client entrance:** the client has no area trigger near either new entrance. As the Ruins sniff showed, Forever's
entrances are server-side area trigger objects, so we build them the same way: `areatrigger` + `areatrigger_template` +
`areatrigger_create_properties` (custom) teleporting to a `world_safe_locs` row. `areatrigger_teleport` is not used.

**No UiMap:** none of the three maps has a `UiMapAssignment` row in the client. So map percentages from Wowhead or
QuestieDB can't place anything inside these maps, and the locator will never find positions for them.

**Sources, in trust order:**

1. Client files: the map, terrain and navmesh, the encounter list and order, level tuning, the Ruins signposts and
   Blackmaw's Magus Rimtori's Journal (`GameObjects.db2`, with positions), and one area trigger inside map 3001 at
   (-5800, -1279, -7) (`AreaTrigger.db2` 10556).
2. Wowhead (Forever): creature ids per zone (one zone page per dungeon). Wowhead has no positions inside these maps,
   and its Shaper's Terrace zone page lists no creatures at all.
3. QuestieDB: the same ids, names only. QuestieTrace has Blackmaw Thralls, Headhunters, Champions and a Berserker in
   Azshara (zone 16) at 27-39 / 23-61. Those look like the outdoor furbolgs near the tunnel, not the instance, and need
   checking before anything uses them.
4. Guides (Warcraft Tavern, Conquest Capped): entrances, boss order, where each boss stands, the route, and boss
   mechanics.

So for both new dungeons, positions follow the recipe The Drowned City and Krol'dok Stronghold already use (core fork
`sql/custom/world/2026_11_11_30_*` and `_33_*`): real map, navmesh and encounter list. Bosses go where the guides put
them and trash packs go along the walking route, on the navmesh. Every guessed row is marked INFERRED, to be replaced
by sniff data if anyone records a run. Templates come from players' creature caches where we have them, and otherwise
from placeholders marked as such.

---

## Blackmaw Hold (map 2974)

**On live:** yes. Three live quests are already in our world build and ask for it. They are "Get to the Roots of It"
(92344, Mathrengyl Bearwalker, Darnassus), "Claws That Rend, Tusks that Gore" (92069, Ogtinc, Azshara: kill
Withermaw and Bonesnout) and "Blackmaw Magic" (97198). Wowhead also lists 92065-92070, 92343, 96246, 97173 and 97327
in the zone. Today players can take these quests and cannot finish them.

**Exists:** the map, terrain, vmaps and mmaps, 7 encounters, sub-areas (Defiled Peak, Festering Grotto, Blackmaw Grove,
Blackmaw Stillwater, Bonesnout's Thicket), and one object position (Magus Rimtori's Journal, 3141.6, 2926.0, 267.1).

**Missing:**

- `instance_template` row (parent 1). The tracker's Forge says it applied this on 2026-11-09 on the PTR, but the last
  analysis still shows it missing, so check it before rebuilding.
- The way in: a server-side area trigger at the tunnel's portal, Kalimdor (4538, -5045, z from the ground). The landing
  spot inside and the exit trigger must be picked on the navmesh. A safe loc out, a graveyard (nearest Azshara or
  Winterspring one) and a `game_tele`.
- Templates for the 7 bosses and the creatures they need: Withermaw 247195, Bonesnout the Unbroken 247198, Impaan the
  Imprisoner 247206, Blackmaw Behemoth 247207, Elder Shaman Bloodmane 247209, Unbound Spirit 247231, Varrox Bleakhoof
  247234, plus Clawbert 247996 and Elder Bramblesnap 248765 (the Unbound Spirit's talk-to). The trash: Legashi
  Subjugator / Summoner / Slayer / Ritualist / Plaguebringer, Blackmaw Berserker / Thrall / Headhunter / Champion /
  Shaman / Druid / Devotee / Spearfisher, Felfire and Swarming Imps, Tunnelweb Matriarch, Depraved Owlbeast,
  Festering Swarmer, Flesh Maggot and others (ids on Wowhead's zone 16554 page). Three rares: Moontouched Wanderer
  269104, Gortek the Apprentice 269111 and Tunnelweb Matriarch 250034.
- Spawns: none exist.
- Boss scripts: an instance script with the 7 encounter ids (3315, 3316, 3322, 3323, 3327, 3334, 3336) through
  `ClassicDungeonEncounterTracker`, like Ruins. The fights with mechanics: Bonesnout stays invulnerable until four
  Legashi Ritualists die. Unbound Spirit stays invulnerable behind three Profane Totems, and Elder Bramblesnap opens it.
  The Behemoth and Clawbert are a pair.
- Loot: Wowhead lists the zone's drops (280056-280086, 286415 and the quest rewards). Item ids need checking against
  our hotfixes.
- The quests' objectives: Nordrassil Root Caps (objects), the Ritual Totem drop, and the Withermaw and Bonesnout drops.

**Positions from:** the guide's route (Grove first and open, Withermaw north in the Festering Grotto, Bonesnout east
in the Thicket, Impaan up at the Defiled Peak, Unbound Spirit down a south side passage, Bloodmane in a wide chamber
near the bottom, the Behemoth at the drop, Varrox in the cave behind the pool), matched to the client's area names
and placed on the navmesh. All INFERRED.

**Recommendation:** build it first. It is the only one of the two with live quests already on the realm pointing at
it. Use the Drowned City recipe, one core-fork SQL file plus `classic_instance_blackmaw_hold.cpp`. Before writing
spawns, ask players for a `creaturecache.wdb` from a Blackmaw run (it gives real templates). Leave the Barrow Deeps
raid door behind Varrox closed.

## The Shaper's Terrace (map 3001)

**On live:** most likely, but not certain. Conquest Capped says it opened with launch on 2026-11-04. Wowhead's zone
page lists no creatures, and QuestieTrace has seen none of its mobs. Kami-labs listed it as announced but not out.
Its 11 encounters and the bosses' creature ids are in the client and on Wowhead.

**Exists:** the map (a copy of north Un'Goro on Kalimdor's coordinates), terrain, vmaps and mmaps, 11 encounters,
sub-areas (Shaper's Plateau, Pillar of Assimilation, The Verdant Plains, Lost Tar Pits, Ruby Spring, Walk of Communion,
Highlands Causeway, Watcher's Overlook, Botanical Grounds, Crystalline Highlands), the area trigger at (-5800, -1279),
and Snowtalon's template (262297).

**Missing:**

- `instance_template` (parent 1). The same 2026-11-09 Forge note applies.
- The way in: an area trigger at the top of the stairs, Kalimdor (-6117, -1246). Map 3001 is on the same
  coordinates, so the landing can be the same spot inside (as Krol'dok does). The guide says players leave by jumping
  off the ledge, so the exit trigger goes there. Plus a graveyard (Marshal's Refuge) and a `game_tele`.
- Templates: Titanosaur 253201, Ravasaur Hunters (the Tor'Rel 261811 and Izha'Rel 253218 pair), Thunderhoof 261812,
  Venomridge 261813, Direhorn Matriarch 262127, Cinder 261974, King Op 261993, Bolt 262081, Vitrix 272561, Nanaya
  261809, plus the trash (Terrace Thunderer 261980, Ravasaur Trapper 262114, Ravasaur Hunter 253214 / 262688, Stone
  Guardians) and the Power Crystals.
- Spawns: none exist.
- Boss scripts: this is the most scripted of the three. Four consoles (red, blue, green, yellow) each take 15 Power
  Crystals gathered inside. Bolt, Cinder, Snowtalon and Vitrix stand at the consoles, and Nanaya is summoned at the
  Pillar of Assimilation once the consoles are lit. The guide says five of the ten guide bosses complete the dungeon,
  and King Op (encounter 3504) is in none of the guides read.
- Loot: no Forever loot list read yet.

**Positions from:** the guide's route (pond below the start ledge, Cinder's mountain cave west, Titanosaur on the
paved road, Snowtalon's cave behind the north-west waterfall, raptors and Vitrix's cave north, Direhorn east,
Thunderhoof on the south rim, Venomridge in the tar pits, Bolt behind him, Nanaya at the central pillar). Here the
coordinates are Kalimdor's, so Un'Goro's own map percentages from guides can be turned into positions on map 3001 with
the client's Un'Goro UiMap. That makes it less of a guess than Blackmaw. Still INFERRED.

**Recommendation:** build it second, after Blackmaw. First confirm it is open on live (one more Wowhead check in a few
days, or a player's report), because an empty Wowhead page this long after launch is odd. The console and crystal
logic needs its own C++ (crystal object, console `GameObjectAI`, Nanaya summon). Budget it as the largest of the
three.

## Ruins of Lordaeron (map 2999)

**On live:** yes.

**Exists, and already playable:** core fork `2026_10_11_00` (instance, server-side entrance trigger 42348 at
(1804.4, 180.0, 70.4) on map 0, exit, safe locs, graveyard 853), `2026_10_11_01` (sniffed spawns: 305 creatures,
120 objects), `2026_10_11_43` and `classic_instance_ruins_of_lordaeron.cpp`. The script tracks five encounters:
Witherfang, Rath'mael, The Butcher (= The Baron), The Abandoned and Bjork. The tracker counts 6 of 7 bosses present.

**Missing:**

- The Lordaeron Captain (255699, encounter 3408): no template, no spawn, no boss id in the script. Guides say it is a
  rare that spawns by chance on the west side, is hostile to the Horde and can't be killed by the Alliance (one
  guide's summary only, unverified), and drops Haunting Blade and Phantom Armor. No source gives a position.
- Viktor the Vile (encounter 3411): he has a template and is "Available", but the script gives him no boss id. In
  the guide, interacting with the fireplace in the burned house starts five waves of undead, and then he comes out.
  If the waves aren't scripted he never appears.
- The tracker's "No entrance teleporter" for this map is a false alarm: the check looks only at
  `areatrigger_teleport`, and this entrance is an `areatrigger` spawn.

**Recommendation:** small work, and it can come any time. Add 255699 (template from a cache, or placeholder), a
chance-based spawn on the west side (spot INFERRED, among the sniffed spawn points there), faction behaviour per the
guide, and give 3408 and 3411 boss ids in the script, plus the fireplace waves if they are missing. A sniff of a run
where the Captain appears would replace the guess.

## Order and size

1. Ruins of Lordaeron: the Captain and Viktor (small, one core PR).
2. Blackmaw Hold: entrance, templates, spawns, 7-boss script (one core PR, Drowned City sized).
3. The Shaper's Terrace: after confirming it is live (largest, with console and crystal logic).

Each one lands as core-fork SQL + C++, tried on the PTR first. The same gap exists for Alcaz Prison (map 2994), the
ninth new dungeon: no instance work at all. It is outside this plan.
