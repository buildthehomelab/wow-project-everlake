# Bringing Everlake's world up to live Forever

Everlake's world is the TrinityCore `forever` fork's world release plus the fork's update files. Live Forever has moved
on since that release: new quests, NPCs, loot and trainer spells that players see every day. This plan is how we bring
that into Everlake's own world database, a little at a time, without breaking the fork's updates or the game.

Nothing in this plan is built yet. The data side is: `tools/forever-data` pins the public Forever sources every day,
loads them next to the fork's world (the release plus the fork's update files, in the same order and by the same re-run
rules as Everlake's worldserver), and `gap_report.py` lists what is missing ([tools/forever-data/README.md](../tools/forever-data/README.md)).

## What is missing (gap report, 2026-11-08)

Everlake's world against live Forever (pins of 2026-11-08, client 1.60.1.70862):

| Kind | Missing or different |
|---|---|
| Quests seen live | 762 not in the world (111 of them Riverglades, 150 Craftsman's Writs); 114 more only in client or beta data |
| Quest givers and enders | 77 quests with no giver, 72 with no ender, about 140 with other givers or enders than the sources agree on |
| Quest details | 173 with no objective rows, 1 with no quest text, 42 with no progress text, 78 with no completion text, 5 missing reward items, 17 renamed |
| NPCs | 1,213 Forever uses with no template, 934 with a template but never spawned, 574 extra spawn spots |
| Loot | 643 NPCs whose loot lacks drops players recorded, 199 with recorded drops and no loot table |
| Trainers | 92 missing spells (some are profession ranks TrinityCore doesn't list), 1 with no trainer list |
| Objects | 178 with no template, 537 never spawned |
| Vendors | 39 missing some items, 2 with no stock |

The fork keeps fixing its world too (against the release alone, its update files bring the quests with no giver from 143
to 77 and with no ender from 149 to 72), so
every import is checked against the newest fork world first, and anything the fork has fixed since drops out of the list.

## Rules

1. **Forever's own ids.** The client knows quests, NPCs, objects and items by Forever's ids, so imported rows keep them.
   (The 10,000,000 id blocks were only for fitting Forever into AzerothCore on Evermore; they don't apply here.)
2. **Add, don't edit.** An import only adds rows the fork's world doesn't have. A fork row is never changed by an
   import, so the fork's own update files keep applying cleanly on top. Every change to a row the fork has goes in a
   separate, clearly labelled corrections file instead, one row per change with its sources, so it can be reviewed on
   its own and dropped when the fork catches up: a renamed quest, other givers, an empty progress or completion text
   filled in, a loot table linked to a creature (its LootID), a vendor or flight-master flag.
3. **The vote decides.** Every value comes from the weighted vote across sources (`source_weights.py`), and every row
   carries a note of which sources gave it. Close calls go on a review list, not into the world.
4. **Held back, not guessed.** A row that needs something we don't have (an item the client lacks, an NPC with no
   model, a spawn with no height) is held back and listed with why, never filled with a made-up value.
5. **Everything is an update file.** The import is ordinary TrinityCore update files, applied by the worldserver's own
   updater like the fork's. Each file deletes what it wrote before writing again, so it can run any number of times.
6. **PTR first.** Every import goes to the PTR realm first (a test realm with few bots, decided but not built yet), gets played and botted there, and only then goes to the Forever realm.

## How a run works

1. Pin and load the sources, load the fork's world (daily, as now).
2. **Generate** the update files for one slice (below): the rows to add, the corrections, and the held-back list.
3. **Dry run**: copy the fork's world (`tc_*`) to a scratch schema, run the generated files on it with the same
   updater rules, and check:
   - every fork row outside the corrections file is byte for byte unchanged;
   - every new row points at things that exist (givers and enders, loot items, trainer spells, models, maps, factions);
   - no id or spawn guid collides with the fork's, and re-running the files changes nothing;
   - the gap report on the result shows the slice's gaps gone and nothing new.
4. **Review**: the files and the dry-run report go up as a pull request. A person reads the corrections and the close
   calls and merges.
5. **Deploy to the PTR realm**, play and bot it; then the Forever realm.

## Slices, in order

Low risk and high value first. Each slice is its own pull request.

| # | Slice | What it adds | Sources | Notes |
|---|---|---|---|---|
| 1 | Givers, enders, objectives, texts | quest relation rows, quest_objectives, progress and completion text for quests the world has | forever-db, QuestieDB, EG Link, ForeverDB | New rows, plus corrections where a fork row's text is empty |
| 2 | Loot | missing drops on existing loot tables, new loot tables | forever-db drop lists, EG Link kill counts | Drop chance from kill counts, only above a minimum number of kills; linking a new table to a creature is a correction |
| 3 | Trainers and vendors | missing trainer spells, vendor stock | EG Link, ForeverDB | Profession rank spells checked by hand first; a missing vendor flag is a correction |
| 4 | Spawns | NPCs and objects that have a template but no spawn, and extra spawn spots | forever-db spawns, EG Link sightings | Needs the ground height at each point from Everlake's own extracted maps; patrol points are told apart from spawn points |
| 5 | New NPCs and objects | templates Forever uses that the world lacks | EG Link models, forever-db, QuestieDB, Wowhead | Server-side values the sources don't have (stats, AI) come from a similar fork NPC, and say so |
| 6 | New quests | quests seen live that the world lacks, Riverglades first | EG Link, forever-db, QuestieDB, ForeverDB | Needs slices 1-5 for their givers, targets and items; a quest whose parts aren't all there is held back |

Not in this plan: scripts (SmartAI, escorts, events) and gossip menus. The sources only show their effect, not the
script; those stay hand work or come from the fork.

## What needs a decision

1. **Where the import files live, and their licence.** Several sources are GPL-3.0 (Polestar's tables, QuestieDB,
   ForeverDB.net), and this repository is GPL-2.0, so the generated SQL can't simply go into `sql/everlake/`. Options:
   a separate data repository under GPL-3.0 that the image build copies in; or generating the files on the server at
   deploy time from the pinned sources, so no data is committed anywhere.
2. **Spawn guids.** The fork's world uses creature guids up to about 26 million and object guids up to about 34
   million. Imported spawns need a block of their own above that, kept in a small table so a re-run reuses the same
   guid for the same spawn point.
3. **Loot chances.** How many recorded kills before a drop chance counts, and whether a drop seen once (a rare) goes in.
4. **The PTR realm.** It is decided but not running yet; the first import needs it, or goes to a second test realm.
5. **Read access to Everlake's live world database**, so the dry run can also compare against what is really there,
   not only against the world rebuilt here.
6. **A ForeverDB.net API key** (theirs, free, needs a Battle.net login) for vendor stock beyond what EG Link saw.
