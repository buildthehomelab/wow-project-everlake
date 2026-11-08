# forever-data

Public WoW Forever data, pinned every day and loaded into its own MySQL database (`acore_forever`), so Everlake can
see what live Forever has that its world doesn't. Everlake's world starts as the TrinityCore `forever` fork's world
release (the `tc_*` tables here); every other source is a view of the live game.

| Step | Tool | Writes |
|---|---|---|
| Pin the public sources | `pin_sources.py` (`--verify` rechecks the hashes) | files + `manifest.json` with sha256, `CREDITS.md` |
| Load each source | `load_sources.py` | `src_<source>` tables + `src_pins` |
| Load the fork's world | `load_tc.py` | `tc_<table>` (TrinityCore layout): the release plus the fork's `sql/updates` and `sql/custom` world files, run as Everlake's worldserver runs them; `tc_updates` lists every update file in it |
| What Everlake's world lacks | `gap_report.py [--zone NAME] [--world SCHEMA.PREFIX]` | `reports/everlake-gaps.md` + `.json` |
| Write an import slice | `import_slice1.py` | update files, review and held-back lists in `world-data/` (gitignored) |
| Dry-run it | `import_dryrun.py` | two worlds in `acore_world_dryrun` (`elscratch_*`, `elstep_*`), `world-data/slice1/dry-run.md` |

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
python3 load_tc.py
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
| `src_wago` | Forever client tables through [wago.tools](https://wago.tools) (areas, maps, taxis, factions, sounds) | Blizzard data |
| `src_wowhead`, `src_wowhead_tooltips` | Wowhead's public Forever tooltips (quests, NPCs, objects, items, spells) | reference only |
| `src_item_history` | Items and spells per build and hotfix ([ericbtaylorjr/forever-db](https://github.com/ericbtaylorjr/forever-db)) | none stated: reference only, never copied into Everlake |
| `tc_*` | [TrinityCore `forever`](https://github.com/advocaite/TrinityCore/tree/forever) world release | GPL-2.0 |

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
- `slice1/manifest.json` (every decision), `slice1/review.md` (close calls, kept out of the files) and
  `slice1/held-back.md` (rows that need something we don't have, with why).

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

`import_dryrun.py` then runs both dry runs by the fork's updater rules (`custom_sql.UpdatePlan`, through the same
`load_tc.py` code) in `acore_world_dryrun`, touching only tables named `elscratch_*` and `elstep_*` (`--drop` removes
them afterwards): from scratch (the release, every fork file and ours in name order) and stepped (the fork world as
`tc_*` holds it, then ours). It checks that both end with the same world, that fork rows outside the corrections are
unchanged (rows added = keys recorded, rows removed or changed = the corrections'), that no recorded key was a fork row,
that new rows point at existing creatures, objects and quests, that running the files again (directly, and through the
updater) changes nothing, also after a simulated fork change (run last, so it changes the stepped world), and that
the gap report on the result has each slice-1 gap closed or listed with its reason
and nothing new. `--skip-scratch` runs only the stepped run (about two minutes instead of the release load).
