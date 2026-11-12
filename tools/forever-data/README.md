# forever-data

Public WoW Forever data, pinned every day and loaded into its own MySQL database (`acore_forever`), so Everlake can
see what live Forever has that its world doesn't. Everlake's world starts as the TrinityCore `forever` fork's world
release (the `tc_*` tables here); every other source is a view of the live game.

| Step | Tool | Writes |
|---|---|---|
| Pin the public sources | `pin_sources.py` (`--verify` rechecks the hashes) | files + `manifest.json` with sha256, `CREDITS.md` |
| Load each source | `load_sources.py` | `src_<source>` tables + `src_pins` |
| Load the fork's world | `load_tc.py` | `tc_<table>` (TrinityCore layout): the release plus the fork's `sql/updates` and `sql/custom` world files, run as Everlake's worldserver runs them; `tc_updates` lists every update file in it |
| Load DatabaseForever's world | `load_dbf.py` | `dbf_<table>` (its own, older TrinityCore layout): EmuForever's world database, to compare with |
| What Everlake's world lacks | `gap_report.py [--zone NAME] [--world SCHEMA.PREFIX]` | `reports/everlake-gaps.md` + `.json` |
| What NorgannonDB adds, who else backs it | `norgannondb_report.py [--world ...] [--data DIR] [--tracker CSV] [--write DIR --name FILE]` | `reports/norgannondb-coverage.md` + `.json`; with `--write`, a vendor stock file in a world-data clone |
| Write an import slice | `import_slice1.py` ... `import_slice4.py` | update files, review and held-back lists in `world-data/` (gitignored) |
| Dry-run them | `import_dryrun.py` | two worlds in `acore_world_dryrun` (`elscratch_*`, `elstep_*`), `world-data/slices/<newest>/dry-run.md` |

Nothing here writes Everlake's own databases. The import (docs/forever-import.md) is written as ordinary update files,
generated here and kept in their own GPL-3.0 repository, because several sources are GPL-3.0 (Polestar's tables,
QuestieDB, ForeverDB.net) and this repository is GPL-2.0: generated SQL is never committed here. Wowhead and the item
history are reference only.

## Running it

```bash
export FOREVER_SOURCES=/path/to/forever-sources      # default: data/forever-sources in this repo (gitignored)
export FOREVER_DB_USER=... FOREVER_DB_PASS=...         # a login with all rights on acore_forever
python3 pin_sources.py                                 # --only NAME,NAME: some sources; --wowhead-only: the tooltips
python3 load_sources.py                                # --only NAME,NAME: some sources
python3 pin_sources.py --only wago --wago-build 1.60.1.70862
python3 load_sources.py --only wago
python3 load_tc.py
python3 load_dbf.py                                    # after pin_sources.py --only databaseforever
python3 gap_report.py
```

`FOREVER_DB_HOST`, `FOREVER_DB_PORT` and `FOREVER_DB_NAME` default to 127.0.0.1, 3306 and acore_forever. Needs Python 3 with `pymysql`, `gh` (logged in, for the
GitHub sources) and `7zz` (the world release). A source whose pin hasn't changed is skipped (`--force` reloads); each
table is filled as `__new` and swapped in with one RENAME, so a failed run leaves the old data.

The fork world everything is compared against is the `tc-forever` pin: advocaite's `forever` branch. To compare against
Everlake's own core instead, or an exact commit, pin it with `FOREVER_TC_REPO=buildthehomelab/wow-trinitycore-everlake
FOREVER_TC_REF=everlake python3 pin_sources.py --only tc-forever` (a branch or a commit) and run `load_tc.py` again.

`pin_sources.py` follows the newest live client build on wago.tools. It fetches Wowhead tooltips at 3 a second, up to
15,000 a run (`WOWHEAD_MAX`; new ids first, then refreshes after 30 days and re-checks missing ids after 7). `wowhead_npc_ids.txt`
is a short list of NPCs whose tooltips are also pinned daily on their own.

## Sources

Every `src_` table has the same columns: `tbl` (the source's table or file), `n` (row order), `k` (the source's key),
`id` (entity id), `ref` (a second id: the giver of a quest_start row, the map of a spawn), `data` (the row as JSON).

| Table | From | Licence |
|---|---|---|
| `src_forever_db` | [Polestar](https://github.com/fitzforge/polestar) forever-db: quests, givers, objectives, NPCs, objects, spawns | GPL-3.0 / CC BY 4.0 |
| `src_eg_link` | [EG Link](https://github.com/JIVESCORP/eg-link-output-wowf), every build: quests, NPC details, vendors, trainers, loot | CC BY 4.0, credit |
| `src_questiedb` | [QuestieDB](https://github.com/Questie/QuestieDB) Forever files, with QuestieTrace corrections players recorded since launch | GPL-3.0 |
| `src_foreverdb_net` | [ForeverDB.net](https://foreverdb.net) addon data: quests, vendors, trainers, dungeons, loot | GPL-3.0, credit "Data from ForeverDB.net" |
| `src_allthethings` | [AllTheThings](https://github.com/ATTWoWAddon/AllTheThings) Forever zone and dungeon files (raw Lua text) | MIT |
| `src_wago` | Forever client tables through [wago.tools](https://wago.tools) (areas, maps, taxis, factions, sounds, spells, items, skill lines, mounts and player conditions). Use `--only wago --wago-build` to reproduce a specific spell acquisition comparison. | Blizzard data |
| `src_live_hotfixes` | Live Forever's hotfix cache (`DBCache.bin`, [public mirror](https://storage.googleapis.com/raidbots-static/wow/forever/enUS/DBCache.bin) that [wowsims/forever](https://github.com/wowsims/forever) builds from): every hotfixed record live sends (spells, talents, items, TACT keys). `tbl` = table hash, `id` = record, `ref` = push; record bytes raw (hex), decoding needs the build's layouts. Pinned per content (`<build>-<sha>`), `--only live-hotfixes` alone. Reader: [`tools/live-hotfixes`](../live-hotfixes/README.md) | Blizzard data |
| `src_wowhead`, `src_wowhead_tooltips` | Wowhead's public Forever tooltips (quests, NPCs, objects, items, spells) | reference only |
| `src_norgannondb` | [NorgannonDB](https://github.com/zmarotrix/NorgannonDB) at commit `a2a5bcf103` (generated 2026-11-11, schema 1.5): quests, NPCs, objects, items, recipes, class `training` (`k` = `CLASS:spell`), `instances` (bosses in order with their own loot, Forever's own instances from DungeonJournal) and `loot_tables`. Compiled from QuestieDB, pfQuest, DungeonJournal, cmangos classic-db and its Collector, so it is never a second witness for those (see `norgannondb_report.py`) | GPL-3.0; pinned NOTICE identifies bundled sources |
| `src_everloot` | [Everloot](https://everloot.app/docs/api): aggregate drop rates with sample counts and a separate build-specific settled-coverage index | CC BY-SA 4.0, with attribution on each drop row |
| `src_zephras_talents` | [Zephras talent export](https://zephras.com/data/): latest versioned class and Legacy talent JSON and its index | CC BY 4.0 for Zephras's work; Blizzard content excluded |
| Pinned files only | [Sakhwoow/WoWForever](https://github.com/Sakhwoow/WoWForever/tree/forever): custom world and hotfix SQL for diffing against the core | GPL-2.0 repository; upstream comparison |
| Manual reference | [Icy Veins WoW Forever Database](https://db.icy-veins.com/wow-forever/) | Use exact Forever IDs to cross-check published client-derived quest, item, NPC, and spell fields and patch history. Early-access pages can omit fields. Confirm server-side behavior with a live observation or versioned game evidence. The NPC reference import is documented below. |
| `src_icyveins` | [Icy Veins' WoW Forever database](https://db.icy-veins.com/wow-forever/): one JSON per NPC from the API its pages use, with what players' addons recorded on live Forever. `tbl` `npc` = the creature row; the others are its relations, `id` = the NPC: `addon_points` (`ref` UiMap; x/y in tenths of a percent, players, reports, last build), `addon_levels`, `addon_drops` (`ref` item, chance), `addon_sells` (`ref` item, price), `addon_trains` (`ref` spell), `addon_quests` (`ref` quest, starts/ends), `addon_gossip`. Map points are sightings, not spawn rows. Fetched 2 a second, new NPCs first then refreshed after 14 days, missing ones re-checked after 7 (`pin_sources.py --icyveins-only`, `ICYVEINS_MAX`); a first full pull of about 15,800 NPCs takes about 2 hours | none stated: reference only, never named in import files (`import_sql.REFERENCE_ONLY`) |
| `src_item_history` | Items and spells per build and hotfix ([ericbtaylorjr/forever-db](https://github.com/ericbtaylorjr/forever-db)) | none stated: reference only, never copied into Everlake |
| `tc_*` | [TrinityCore `forever`](https://github.com/advocaite/TrinityCore/tree/forever) world release | GPL-2.0 |
| `dbf_*` | [DatabaseForever](https://github.com/EmuForever/DatabaseForever): the world database of the [EmuForever](https://github.com/EmuForever/EmuForever) emulator, cut down to Forever content plus about 4,400 NPCs of its own (1,400 of them spawned, 15,700 spawns), loot, vendors and trainers. Its added spawns are placed from map pins (a 0.1% grid, all facing 0, 120 s respawn) | none stated: reference only, never copied into Everlake and never named in import files (`import_sql.REFERENCE_ONLY`) |

To refresh just the new sources and stage their readable data in the lake:

```bash
python3 pin_sources.py --only norgannondb,everloot,zephras-talents,sakhwoow-forever
python3 pin_sources.py --verify
python3 load_sources.py --only norgannondb,everloot,zephras-talents
```

NorgannonDB is included in the usual pin run. Everloot, Zephras and the Sakhwoow SQL snapshot are opt-in.
NorgannonDB's entity rows carry the upstream `_provenance` label. A Questie or pfQuest label shares that
source's evidence. A collector label applies to the record and does not establish the origin of every field.
`norgannondb_report.py` measures it against QuestieDB and Wowhead, against the world (`--world`, e.g. the dry run's
`acore_world_dryrun.elstep_`) and the Forever Tracker's work list (`--tracker`, its To add > Export CSV), and splits each
drop or stock line the world lacks by who else shows it: EG Link or ForeverDB.net (a vendor its players saw on Forever)
count as independent; QuestieDB, QuestieTrace and forever-db are NorgannonDB's own origin; Icy Veins is reference only.
`--write` writes the independent, unlimited money-priced vendor lines no world-data file names yet.
Everloot's aggregate drop rows are distinct from its build-specific consensus list. The Zephras export contains
talents and Legacy data. These three tables are available for comparison before any candidate weighting or import.
Sakhwoow files stay in the snapshot directory for row-by-row diffing. The loader does not execute their SQL.

`CREDITS.md`, written by `pin_sources.py` into the sources folder, has to travel with anything made from this data.
Game content such as names and text belongs to Blizzard Entertainment.

`lua_data.py` reads the addons' Lua data files (literal tables only). `questietrace.py FILE...` reads QuestieTrace
recordings (SavedVariables or `/qlt export` text): vendor stock, gossip, trainers, quest text, loot. `pin_sources.py`
pins the files listed in `questietrace_paths.txt` (local, gitignored; see `questietrace_paths.example.txt`). We record
nothing ourselves on live Forever.

## Weighted vote

The same fact (a quest's giver, an NPC's level, a vendor's stock) comes from many sources, and none is complete or always
right. `candidates.py` gathers every source's value per quest and NPC field, and `source_weights.py` weighs them:
agreeing sources add up, Classic-derived data never beats Forever data, the newest build gets a small edge, and close
calls (runner-up within 15%) are flagged rather than decided silently.

Quest text keeps retail text tokens (`$1oa` and the like): the Forever client shows them.

## Gap report

`gap_report.py` compares the world release (`tc_*`) with the vote of every other source, zone by zone:

- quests missing, split into seen in the live game (EG Link at build 70790 or later, QuestieTrace, ForeverDB's seen
  list) and known only from client or beta data;
- quests with other names, givers or enders, or with none;
- NPCs Forever uses with no template, NPCs never spawned, extra spawn spots;
- vendor stock (EG Link's recorded stock against `npc_vendor`, following list references);
- objects missing or never spawned, loot missing recorded drops, trainers missing spells, quests with no objectives,
  missing reward items, or no progress or completion text.

Trainer comparisons count the spell on the active trainer list and any spell it explicitly teaches in the pinned
Forever `SpellEffect` data. Older source pins without that table compare exact IDs. Run the source pin and loader
again to add the table to an existing build.

When `dbf_*` is loaded, every gap DatabaseForever has rows for says what it holds there (a template and spawns, items,
spells, givers), with a count per kind under "What DatabaseForever has rows for". DatabaseForever never adds a gap: its
additions are an emulator's guesses, not a sighting in the live game. In the vote it speaks only for NPCs the fork's
world lacks (on shared NPCs its values are the fork's or bulk defaults), at weights below Wowhead's.

`load_tc.py` runs the fork's `sql/updates` and `sql/custom` world files on top of the release by the same rules as the
fork's own updater at worldserver start (`custom_sql.UpdatePlan`): new files are applied; a changed file is applied again,
except world baselines, which are only re-hashed; once a custom file is applied again, every later custom file is too.
`custom_sql.py` points each statement's tables at the new tables. It lets through only the statement kinds update files
use, checks every table a statement names (also in statements built inside strings), and stops the load on anything else,
so nothing outside the world tables is touched. A custom file pinned after the last `load_tc.py` run is
not in `tc_*` yet: gaps whose key rows it writes or changes are marked "custom SQL touches it". "Never spawned" includes creatures that scripts summon, and extra spots include
points along patrol paths.

## Import, slice 1: quest givers, enders, objectives and texts

`import_slice1.py` writes slice 1 of the import plan (docs/forever-import.md) for the quests the world already has:

- `sql/world/YYYY_MM_DD_00_world_everlake_import_slice1.sql`: givers and enders for quests with none, objective rows,
  and progress (`quest_request_items`) and completion (`quest_offer_reward`) texts where the world has no row;
- `sql/world/YYYY_MM_DD_01_world_everlake_import_slice1_corrections.sql`: changes to fork rows: other givers or enders,
  an empty quest text filled in;
- `slices/slice1/manifest.json` (every decision), `review.md` (close calls, kept out of the files) and
  `held-back.md` (rows that need something we don't have, with why).

How it decides:

- Every value is the weighted vote (`source_weights.py`) over every source, the fork's own Forever beta sniffs
  (`tc-sniff`) included; the fork's converted Classic rows only count where no Forever source speaks. Every row carries
  the sources that gave it (a comment in the file, and `note` in `everlake_import_rows`).
- Givers and enders are voted as a set (`resolve_set`). A member within 15% of the keep line is a close call: the whole
  quest goes to the review list. Removing a fork giver rests on the sources' silence about it, so it needs two Forever
  sources speaking about that quest's givers; with only one, the vote's new givers still go in and the removal goes to
  the review list. A giver with no creature or object template in the world is held back (new NPCs are slice 5).
- Texts come from EG Link's recorded progress and completion texts; two variants of one text (one with `$r`, one with a
  race name filled in) are a close call. Emotes are 0, as in every sniffed Forever row. Imported rows carry
  `VerifiedBuild` 0, so later votes don't count them as a sniff.
- Objective rows need Forever's own objective ids, which only EG Link's quest records have (forever-db has kind, target
  and count). No public source records objective `Flags`/`Flags2`: they are 32 and 0 (decided 2026-11-08; 32 is what
  94% of sniffed Forever objectives use), `--objective-flags F,F2` or `none` to hold every objective back. Area trigger
  and reputation objectives need more than a `quest_objectives` row and are always held back.

How the files are written (`import_sql.py`): an import file adds rows through a temporary stage table, marks the rows
the world is missing, inserts exactly those and records their keys with its own file name in `everlake_import_rows`; a
quest's givers, enders or objectives are only added while the quest has none but ours (recorded, and still
`VerifiedBuild` 0 as we wrote them), so a re-run after the fork has filled the quest in adds nothing next to the
fork's. Inserts name only the columns that get a value; the rest take the table's defaults. A corrections file checks
every guard first (the quest's whole giver set with each row's `VerifiedBuild`, or the value being changed and the
row's `VerifiedBuild`, still exactly as written against: not every column, so a later fork change to other columns
can't make a re-run fail) and then acts only on the corrections that passed; a re-run finds the rows changed and does
nothing. Files carry no timestamps: the same pins give the same bytes, and the
generator refuses to overwrite a file whose content changed (`--replace` only before it is deployed).

## Import, slice 2: loot

`import_slice2.py` writes slice 2: drops live Forever shows that the world's creature loot tables lack, and new loot
tables for creatures with none. It works on exactly the gaps `gap_report.py` lists (`loot_items_missing`,
`npcs_no_loot`), running the report itself (`--gaps FILE` reuses one).

- `sql/world/YYYY_MM_DD_NN_world_everlake_import_slice2.sql`: `creature_loot_template` rows, numbered after the files
  already in the folder for that date (slice 1's 00 and 01, so 02);
- `sql/world/YYYY_MM_DD_NN+1_world_everlake_import_slice2_corrections.sql`: each new table linked to its creature
  (`creature_template_difficulty.LootID` of its open-world row, a fork row);
- `slices/slice2/manifest.json`, `review.md` (drops seen once) and `held-back.md`.

Which drops go in (the user's decisions of 2026-11-08):

- Only where a Forever source shows the NPC drops it: EG Link's kill loot (`wowf/<build>/npc:<id>[|quest][|group]`;
  `|spell` keys are skinning, gathering and pick-pocketing and don't count) or a QuestieTrace sighting (QuestieDB's
  `foreverItemTraces.lua`, `npcDrops_add`). forever-db's `item_source` rows are built from pfQuest (VMaNGOS) and
  CMaNGOS alone (Polestar's `forge-data` publish step), so they are Classic data. The user chose (2026-11-08) to add a
  drop only they show with its Classic chance anyway, marked `classic` (`--classic-only hold` holds them back).
- Every row's note (in `everlake_import_rows`, and the comment beside the row in the file) says where its chance comes
  from: `eg-link 7/120` (drops/kills, `on quest` for a quest drop) or `classic forever-db 12.5% (pfQuest/CMaNGOS)`, so
  a reviewer can tell the Classic rows apart and a later Forever recording can replace them. The dry-run report counts
  both.
- The chance is EG Link's, drops / loot windows summed over every build (beta included), when the NPC has 50 or more
  recorded kills; for a quest drop, over the kills made on a quest. Otherwise it is forever-db's Classic chance, marked
  `classic`. With neither, the drop is held back.
- A drop EG Link saw once goes to the review list.
- Every row: `ItemType` 0, `GroupId` 0 (rolled on its own, so the fork's groups keep their odds), `LootMode` 1, one of
  the item. A drop EG Link saw in stacks over one is held back (no source records the range); so is an item missing
  from Forever's client item list (forever-db's `item`).
- `QuestRequired` 1 for a quest item (the client's flag, as forever-db lists it) that EG Link saw drop only on a quest,
  or that only Classic data shows, when a quest in the world asks for it. A quest item no quest in the world asks for
  is held back: with `QuestRequired` it would never drop, without it everyone would get it. EG Link files a whole kill
  under `|quest` when the looter was on any quest, so an ordinary item seen only there (cloth, water) stays an
  ordinary drop.
- A loot table several creatures share gets a drop only when every one of them shows it.
- New tables take the id 900,000,000 + the creature's entry: the fork's loot ids follow its creature entries (below
  10 million, which the generator checks), so ours can't collide with one and a re-run reuses the same id.

The import file adds a drop only where the table lacks it, the item doesn't already drop through one of the table's
reference lists (two levels deep), a creature still uses the table, and the drop was never added before: a row we
added that a later fork file removes stays removed (`everlake_import_rows` remembers it). A new table's rows go in only
while the creature still has no loot table but ours. The corrections file links a table only while the creature's
`LootID` is still 0 with the `VerifiedBuild` it was written against, and our table is there; once the fork links its
own, the correction does nothing and our table is left unused.

## Import, slice 3: trainers and vendors

`import_slice3.py` writes slice 3: spells a trainer teaches on live Forever that its trainer list lacks
(`trainer_spell`), and items a vendor sells that its stock lacks (`npc_vendor`), for the gaps `gap_report.py` lists
(`trainer_spells_missing`, `trainers_unlinked`, `vendor_items_missing`, `vendors_no_stock`).

- `sql/world/YYYY_MM_DD_NN_world_everlake_import_slice3.sql`, numbered after the other slices' files of that date;
  no corrections file (every vendor here already has its vendor flag);
- `slices/slice3/manifest.json`, `review.md` (profession ranks) and `held-back.md`.

The source is EG Link's newest trainer or vendor window that lists anything, the one the gap report reads too
(`gap_report.newest_windows`: the highest build, live over beta on a tie; a beta window's row says so in its note). A
window lists what the NPC offers, so one is enough.

- Trainer spells go into the list the creature uses. A list several creatures share gets a spell only when no other
  creature on it was seen without it in a window at least as new.
- `MoneyCost` is the price at Neutral or Friendly (EG Link's `costs` are per standing; those two match the fork's
  prices), or one seen only at Honored and above turned back with the game's discount (10, 15, 20%) when exact.
- `ReqLevel` is the newest non-zero level any window shows for the spell (a window shows 0 when its player already
  knew it); a class spell every window shows at 0 is held back unless the fork teaches it at level 0 too (weapon skills). `ReqSkillRank` is
  EG Link's. `ReqSkillLine` is the line the fork's own rows use for that skill name.
  `ReqAbility1..3` are what EG Link says the spell needs known first (`abilities`), or the rank before it, each found by
  name in the same window, and a rank before it must be on the list too.
- Held back or on the review list: profession ranks (Apprentice ... Artisan: the plan has them checked by hand first),
  pet training (the fork's trainers teach no pet spells), spells not in Forever's client spell tables (item-history,
  used only as a check), a skill name the fork never uses, no price, a creature with no trainer list (it needs a gossip
  option: hand work).
- Vendor items go after the vendor's last slot in the window's order, with no stock limit and `ExtendedCost` 0. Held
  back: items that cost more than money (the `ItemExtendedCost` id isn't recorded), limited stock (no restock time),
  items not in the client's item list, and a vendor whose stock another vendor lists.

The import file adds a row only where it is missing, never again once added (a row the fork removes stays removed), a
trainer spell only while a creature uses the list, and a vendor item only while the vendor doesn't already sell the item
at another price.

## Import, slice 4: spawns

`import_slice4.py --maps DIR` writes slice 4: spawns (`creature`, `gameobject`) for NPCs and objects that have a
template but no spawn, and NPCs' spots far from every spawn they have (`npcs_not_spawned`, `objects_not_spawned`,
`extra_spots`). `DIR` is Everlake's extracted maps folder (the worldserver's `data/maps`); `terrain.py` reads its
`.map` tiles (version 10) the way the worldserver does (`GridMap`), terrain and water only.

The user's decisions (2026-11-08):

- A point comes from forever-db (QuestieDB's points, with a height where a CMaNGOS spawn stands within 3 yards) and goes
  in only where a live Forever sighting of that NPC or object lies within 40 yards (EG Link's combat-log positions,
  deaths, loot and windows on live builds). forever-db's points are largely Classic data: holiday and invasion NPCs,
  test NPCs, WotLK ones. Only a few dozen of the 934 unspawned NPCs were ever seen live.
- Nothing summoned (by the fork's SmartAI or a client spell) or, for an NPC the fork doesn't spawn, scripted.
- A point with no height takes the terrain height, except in a dungeon or battleground, in water, or where a fork
  spawn within 10 yards stands more than 2 yards off the ground (a building, bridge or cave). Checked against the
  fork's own spawns: the terrain height is within a yard of 83% of them, median 0.08 yards.
- A unique NPC (elite, rare, boss, or one that gives quests, sells or trains) with several points, or an extra spot next
  to its spawn, goes to the review list: it may be one NPC on a patrol.
- Guids from 900,000,000, creatures and objects each; a later slice continues after the manifest's `guids_used` and
  above the live realm's highest guid (the worldserver gives a GM's `.npc add` the highest guid + 1, inside this block
  once these spawns are in).

Values no source has: orientation 0 and rotation (0, 0, 0, 1); an extra spot copies its phases, difficulty, equipment,
respawn and wandering from the NPC's nearest fork spawn (standing still where that one walks a path); a new NPC takes
the commonest respawn and wandering of the fork's NPCs of its classification on that map, an object those of its type.
The import file adds a spawn only while the fork has no spawn of the same NPC or object within 40 yards but ours, and
never again once added.

## Import, slice 5: new NPCs and objects

`import_slice5.py --maps DIR` writes slice 5: templates for NPCs and objects Forever uses that the world lacks
(`missing_npcs`, `objects_missing`), with everything they need to stand in the world: `creature_template`,
`creature_template_difficulty`, `creature_template_model`, `creature_classic_level` (the fork's own level table, which
it fills for its own Forever NPCs), the new merchants' `npc_vendor` stock, `gameobject_template`,
`gameobject_questitem` and a chest's `gameobject_loot_template`, and their spawns (`creature`, `gameobject`).

The user's decisions (2026-11-08):

- Only what also gets a spawn, by slice 4's rule (a forever-db point a live sighting confirms within 40 yards, with a
  height). Of 1,213 NPCs and 178 objects with no template, only a few dozen were ever seen live; the rest is beta,
  Classic or event data and is held back. Slice 6 brings in the NPCs its quests need.
- An NPC's faction: no public source records one. It is the commonest faction of the fork's NPCs of the same creature
  type spawned within 60 yards that react to a player of the side EG Link's players were as they saw it, both ways
  (`Reactions`, following TrinityCore with starting reputations: how the player sees the NPC, as the client colours it,
  and whether the NPC attacks the player), preferring a shared first name (Razormane, Spitelash) and then the exact
  reaction (neutral, friendly). A hostile NPC may take another type's faction, never a critter's. Tested on 1,474 fork
  NPCs EG Link players saw: whether the fork's own faction attacks matches what players saw for all of them; the guess
  attacks (or not) as the fork NPC's own faction does every time it picks, picks the exact faction 61% (friendly) to
  68% (hostile) of the time, and nothing for 8%, which is held back. The nearest fork NPC of that faction (of the same
  type where there is one) lends speeds, attack times and immunity to players and NPCs.
- A unique NPC (elite, rare or boss, titled, offering a service, or with every point within 60 yards of the others)
  with several points goes to the review list, as in slice 4: it may be one NPC wandering or on a patrol.
- Services as EG Link's players saw them, with the stock EG Link recorded (`import_slice3.vendors`); gossip only when
  nothing else. Training needs a trainer list and a gossip option (hand work): the trainer flag is left off and the NPC
  goes on the review list.

Template values come from EG Link's creature and object details, the client's own query data (of a live build, else a
beta build, said so): names, titles, types, classification, models (checked against Forever's client
`CreatureDisplayInfo` and `GameObjectDisplayInfo`, pinned from wago.tools), health and power multipliers, type flags,
movement, kill credits, cursors; an object's whole template. Levels are EG Link's live levels, else forever-db's.
Damage and armour modifiers 1 and `unit_flags2` 2048, as the fork's own Forever NPCs. A chest's loot, when the fork
has none: its quest items at 100% for players on the quest (as the fork's quest chests), other items at their share of
EG Link's openings once there are 50 (fewer: review list). No equipment, scripts or loot for the NPCs: their loot comes
with a slice 2 run once the templates are in. Spawns as slice 4's new NPCs; guids continue after slice 4's.

Every row goes in only while the template is ours (`everlake_import_rows` names it under this file, and it still has
`VerifiedBuild` 0 as written; the build its details came from is in the note) and never again once added: where the
fork adds the NPC or object first, or takes it over with a sniffed template, nothing of ours goes in next to it. An NPC
or object the fork already spawns without a template is held back. NPCs offering a service stand still.

## Dry run (every slice)

`import_dryrun.py` runs every file in the data folder (`--data`, a clone of wow-everlake-world-data or `world-data/`)
together: the files in `sql/world/` must be exactly the ones the slices' manifests (`slices/<slice>/manifest.json`)
name. It runs both dry runs by the fork's updater rules (`custom_sql.UpdatePlan`, through the same `load_tc.py` code)
in `acore_world_dryrun`, touching only tables named `elscratch_*` and `elstep_*` (`--drop` removes them afterwards):
from scratch (the release, every fork file and ours in name order) and stepped (the fork world as `tc_*` holds it, then
all of ours: nothing is deployed yet). It checks that both end with the same world, that fork rows outside the
corrections are unchanged (rows added = keys recorded, rows removed or changed = the corrections'; a table with no
primary key, like `creature_loot_template`, is compared under its first index with duplicates counted), that no
recorded key was a fork row, that new rows point at existing creatures, objects, quests, client items and reference
lists, that every new loot table is some creature's (a new chest's loot some chest's), that new templates' models are in
Forever's client and each new template has a spawn, that running the files again (directly, and through the
updater) changes nothing, also after each slice's simulated fork changes (run last, so they change the stepped world),
and that the gap report on the result has each gap of the slices' categories closed or listed with its reason and
nothing new (loot, trainer-spell and vendor-item gaps count per item of an NPC; a decision on `npc/*` covers all of
an NPC's items). The report goes to the newest slice's folder (`--report SLICE` for another).
`--skip-scratch` runs only the stepped run (a few minutes instead of the release load).
