# forever-data

Public WoW Forever data, pinned every day and loaded into its own MySQL database (`acore_forever`), so Everlake can
see what live Forever has that its world doesn't. Everlake's world starts as the TrinityCore `forever` fork's world
release (the `tc_*` tables here); every other source is a view of the live game.

| Step | Tool | Writes |
|---|---|---|
| Pin the public sources | `pin_sources.py` (`--verify` rechecks the hashes) | files + `manifest.json` with sha256, `CREDITS.md` |
| Load each source | `load_sources.py` | `src_<source>` tables + `src_pins` |
| Load the fork's world release | `load_tc.py` | `tc_<table>` (TrinityCore layout) + `tc_updates` |
| What Everlake's world lacks | `gap_report.py [--zone NAME]` | `reports/everlake-gaps.md` + `.json` |

Nothing here writes Everlake's own databases. Filling the gaps is not built yet. The plan: Forever's own ids (the client
knows them), only rows the fork lacks, so the fork's own updates keep flowing in. Where that SQL lives and under which
licence is still open: several sources are GPL-3.0 (Polestar's tables, QuestieDB, ForeverDB.net), which this GPL-2.0
repository can't take in as is, and Wowhead and the item history are reference only.

## Running it

```bash
export FOREVER_SOURCES=/path/to/forever-sources      # default: data/forever-sources in this repo (gitignored)
export FOREVER_DB_USER=... FOREVER_DB_PASS=...         # a login with all rights on acore_forever
python3 pin_sources.py                                 # --wowhead-only [--wowhead-max N]: only the tooltips
python3 load_sources.py                                # --only NAME,NAME: some sources
python3 load_tc.py
python3 gap_report.py
```

`FOREVER_DB_HOST`, `FOREVER_DB_PORT` and `FOREVER_DB_NAME` default to 127.0.0.1, 3306 and acore_forever. Needs Python 3 with `pymysql`, `gh` (logged in, for the
GitHub sources) and `7zz` (the world release). A source whose pin hasn't changed is skipped (`--force` reloads); each
table is filled as `__new` and swapped in with one RENAME, so a failed run leaves the old data.

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
- vendor stock (EG Link's recorded stock against `npc_vendor`, following list references).

The fork's `sql/custom` world files that the release doesn't already hold (its `updates` table, kept as `tc_updates`,
lists the ones it does) are not applied. Every gap whose key rows those files write or change is marked "custom SQL
touches it", so it can be checked first. "Never spawned" includes creatures that scripts summon, and extra spots include
points along patrol paths.
