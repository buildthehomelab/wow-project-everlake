# Bringing Everlake's world up to live Forever

Everlake's world is the TrinityCore `forever` fork's world release plus the fork's update files. Live Forever has moved
on since that release: new quests, NPCs, loot and trainer spells that players see every day. This plan is how we bring
that into Everlake's own world database, a little at a time, without breaking the fork's updates or the game.

Slices 1 to 5 have generators (`import_slice1.py` ... `import_slice5.py`), and one dry run covers every slice's files (`import_dryrun.py`); the rest is not yet. The data side is: `tools/forever-data` pins the public Forever sources every day,
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
   import, so the fork's own update files keep applying cleanly on top. Every change to a row the fork has goes in
   separate, clearly labelled corrections files instead (new ones with each slice), one row per change with its
   sources, so they can be reviewed on their own: a renamed quest, other givers, an empty progress or completion text
   filled in, a loot table linked to a creature (its LootID), a vendor or flight-master flag. A correction changes or
   removes a fork row only while that row is still as the correction was written against, so a re-run never overwrites a newer
   value from the fork, and once the fork catches up the correction no longer matches and does nothing.
3. **The vote decides.** Every value comes from the weighted vote across sources (`source_weights.py`), and every row
   carries a note of which sources gave it. Close calls go on a review list, not into the world.
4. **Held back, not guessed.** A row that needs something we don't have (an item the client lacks, an NPC with no
   model, a spawn with no height) is held back and listed with why, never filled with a made-up value.
5. **Everything is an update file.** The import is ordinary TrinityCore update files, applied by the worldserver's own
   updater like the fork's. A file is never changed once it is deployed: the updater would run it again, and with it
   every later custom file, the fork's included, and some of the fork's files can't run twice. A later fix is a new
   file. Each file is still safe to run again: it adds a row only where none exists, records the key of each row
   it actually inserts, with its own file name, in a small table of our own (`everlake_import_rows`), and deletes only
   rows listed there under its own name (a corrections file may also remove the fork rows it names, under rule 2). A key is recorded only when the row was missing, never from a fixed list, so
   a re-run never lists a row the fork has since added.
6. **PTR first.** Every import goes to the PTR realm first (a test realm with few bots, decided but not built yet), gets played and botted there, and only then goes to the Forever realm.

## How a run works

1. Pin and load the sources, load the fork's world (daily, as now).
2. **Generate** the update files for one slice (below): the rows to add, the corrections, and the held-back list.
3. **Dry run**, twice, both with the updater's rules: once from scratch (the fork's world, then the fork's files and ours
   in filename order, as a new realm builds it), and once stepping from the deployed pins to the new ones (a world built
   at the old fork and data pins, with its `updates` rows, then the new files), as the realm will. Then check:
   - every fork row outside the corrections files is byte for byte unchanged;
   - every new row points at things that exist (givers and enders, loot items, trainer spells, models, maps, factions);
   - no id or spawn guid collides with the fork's, and re-running the files changes nothing;
   - the gap report on the result shows the slice's gaps gone and nothing new.
   - the two dry runs end with the same world: a difference means files whose order differs between a new realm and
     the live one, fixed by a new file.
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

## Where the import files live (decided 2026-11-08)

Several sources are GPL-3.0 (Polestar's tables, QuestieDB, ForeverDB.net) and this repository is GPL-2.0, so the
generated SQL lives in its own repository, `wow-everlake-world-data`, under GPL-3.0:

- **What it holds.** The generated update files (`sql/world/`), the corrections files, the held-back list and the dry-run
  report of each slice, and a NOTICE naming every source, its licence and its pin (EG Link is CC BY 4.0 and needs the
  credit). No code: the generator stays here in `tools/forever-data`, and only reads the sources.
- **How Everlake gets it.** The Dockerfile pins it by commit, like the fork (`WORLD_DATA_COMMIT`), clones it in a build
  stage, and copies its `sql/world/` folder into `/src/TrinityCore/sql/custom/world/`, where the worldserver's updater
  applies the files with the fork's custom files. The pin is empty by default, so a build takes no import files. The
  files land in the world database (realm 2 shares realm 1's) and in the image every worldserver of the project runs,
  so `WORLD_DATA_COMMIT` (a full commit SHA) is set only in a compose project with its own world database and its own
  image: the PTR realm first (rule 6), then live by `scripts/promote.sh`. The build stops on anything in `sql/world/` that isn't a file
  named like ours. Moving a realm's pin forward comes after the slice's own pull request in the data repository is
  merged.
- **File names.** `YYYY_MM_DD_NN_world_everlake_import_<slice>.sql`. The fork never uses `everlake_import`, so no
  name of ours can replace or clash with one of the fork's.
- **When the fork adds a row we added.** On the realm our row is already there, so a fork file that plainly INSERTs it
  would stop the updater. Before the fork pin moves, the stepped dry run shows every such row. For each fork file that
  adds them, a new handover file named to sort just before it deletes those rows, only where `everlake_import_rows`
  lists them, and drops them from that table. Being new, it runs once without making anything else run again; if it
  ever does run again, it finds nothing listed and deletes nothing, so the fork's row stays. The handover file and the
  new data pin go in the same pull request as the new fork pin.

## What needs a decision

1. **Spawn guids** (decided 2026-11-08). Imported spawns count from 900,000,000 (creatures and objects each), far above
   the fork's (about 26 and 34 million). A file fixes each spawn's guid, so a re-run reuses it; a later slice continues
   after the guids an earlier one used (its manifest's `guids_used`). Slice 4 also decided: a spawn needs a live Forever
   sighting within 40 yards, since forever-db's points are largely Classic (holiday, invasion and test NPCs).
   Slice 5 (2026-11-08): only NPCs and objects that also get such a spawn; an NPC's faction is the commonest of the fork's
   NPCs of its type within 60 yards that react to players as EG Link's players saw it, the rest borrowed from the
   nearest of them; services and stock as EG Link saw them, training left to hand work.
2. **Loot chances** (decided 2026-11-08). A drop goes in where a Forever source (EG Link, QuestieTrace) shows the NPC
   drops it, and also where only forever-db's drop rows do: those are all Classic (pfQuest/CMaNGOS), so such a row is
   marked `classic` until a Forever recording replaces it. The chance is EG Link's once the NPC has 50 recorded kills
   (loot windows summed over builds), else forever-db's Classic one, marked so. A drop seen once goes to the review
   list; one with no usable chance is held back.
3. **The PTR realm.** It is decided but not running yet; the first import needs it, or goes to a second test realm.
4. **Read access to Everlake's live world database**, so the dry run can also compare against what is really there,
   not only against the world rebuilt here.
5. **A ForeverDB.net API key** (theirs, free, needs a Battle.net login) for vendor stock beyond what EG Link saw.
6. **Quest objective ids.** Most quests with no objectives (151 of 173 on 2026-11-08) lack Forever's objective ids:
   they wait for EG Link to record them, or for a decision to use an id block of our own. (Objective `Flags` and
   `Flags2`, which no public source records, were decided on 2026-11-08: 32 and 0, as 94% of sniffed Forever
   objectives have 32.)
