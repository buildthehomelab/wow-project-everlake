# ForeverTracker

[ForeverTracker](https://github.com/filinodz/ForeverTracker) (MIT, by FilinoDZ) compares the official WoW Forever
client with a TrinityCore server: every dungeon, boss, zone, quest, item, spell, talent, recipe, mount, pet, toy,
achievement and flight point the client ships, whether players can really get or do it here, and why not when they
can't. It keeps a changelog of every client build, and its Forge turns what is missing into SQL (spawns, vendors,
loot, trainers, hotfix rows), previewed, applied in one transaction and recorded with its rollback.

Upstream is a Windows launcher with a setup wizard. We run our fork,
[buildthehomelab/wow-forever-tracker](https://github.com/buildthehomelab/wow-forever-tracker), as a container
(its `docs/DOCKER.md`): no launcher, no wizard, configured from the environment.

## Where it reads and writes

| Database | Tracker user `tracker` |
|---|---|
| `forever_tracker` | everything (its own `ft_*` tables) |
| `world`, `hotfixes` (live) | read only |
| `auth`: `realmlist`, `battlenet_accounts`, `account`, `account_access` | read only (client build, GM logins) |
| `world_ptr`, `hotfixes_ptr` (PTR) | read and write: the analysis reads them, the Forge applies fixes to them |
| `ft_world_build` | read only, while the world build is on: what a replay found. It is written by the second user, `tracker_build` ([the world build](#the-world-build)), which has every right there and no right on any database above |

So a fix is tried on the PTR first, and reaches live like every other change: as reviewed SQL (the Forge shows the
SQL of each fix and keeps it in its history). MySQL enforces this: `scripts/tracker-setup.sh` sets exactly these
rights on every start of the app. To report on live itself, set `TRACKER_WORLD_DB=world` and
`TRACKER_HOTFIXES_DB=hotfixes`; the Forge then still previews, and applying fails.

The PTR's worldserver reads its world at start: restart the `everlake-ptr` app after the Forge applies fixes.

The client's DB2 files come from `DATA_DIR/dbc`: the extractor takes them straight from Blizzard's CDN, so they are
the official files of the realms' build. The snapshot of a build is stored once; a new build (after
`DBC_ONLY=1 docker compose run --rm extractor` and a realm build bump) gets its own on the next start, and the
changelog compares the two.

## Install

1. In `.env`: `TRACKER_DB_PASSWORD` and `TRACKER_ADMIN_PASSWORD` (see `.env.example`).
2. The PTR app runs (the tracker reads its databases), and the server has the live image `everlake-trinitycore:live`
   ([the world build](#the-world-build) copies its files; the app does not start without it).
3. TrueNAS: Apps, Discover Apps, Custom App, Install via YAML, name `everlake-tracker`:

   ```yaml
   include:
     - <everlake folder>/docker-compose.tracker.yml
   ```

   The first start builds the image from the pinned fork commit, sets up the user, then stores the build, analyses
   and runs the locator in the background (a few minutes, then the locator asks Wowhead slowly). The app's log shows
   each step.
4. Open `http://<server>:8090/` and log in as `admin` (or with a GM account's Battle.net email and password).

Later runs: *Run again* in the Forge. A new fork commit: change the pin in `docker-compose.tracker.yml` (or
`TRACKER_COMMIT` in `.env`) and restart the app.

Since fork `a77090dc`, *New in Forever* means not in the Classic Era client (Season of Discovery rows no longer count),
the work list shows each fix once, and the analysis asks Wowhead for the names of new quests the server lacks
(`FT_WOWHEAD`, on by default; quests Wowhead does not know are hidden tracking quests). The first start of that image
analyses again by itself; the quest lookup makes that run longer the first time, then it is cached.

Since fork `30487b74`:

- **Forge to live.** Fixes are applied and tested on the PTR (the tracker writes only `world_ptr`). Forge › History ›
  *Data repo .sql* (or *All applied, as data repo files*) exports an applied operation as a world update file,
  `sql/world/YYYY_MM_DD_900_world_everlake_forge_<op>_<kind>.sql`, for wow-everlake-world-data. Check the open
  world-data PRs for the same rows first, then commit it there; it reaches the PTR and the live realm through their
  world-data pins like every other file. The file is safe on the PTR too (it skips what is already there). Spawns use
  guids `910000000 + op x 10000`, clear of the import block. Hotfix rows are not exported. Details: the fork's
  `docs/DATA-REPO.md`.
- **Trainer fixes** never offer talents, always require the previous rank, and skip `TRACKER_TRAINER_SKIP_IDS`
  (default `400000-499999`, the Season of Discovery runes in the client). The first start re-analyses once.

Since fork `94c8da34`, the analysis also asks Wowhead about every new item and trainer spell the server lacks: items
Wowhead marks as Season of Discovery leftovers, or does not know, move to *Internal / test*, and such spells are never
offered at trainers. The first start re-analyses; checking ~7,000 items takes about an hour the first time (cached after).

Since fork `90485afd`: Wowhead decides **what** Forever has, imports say **where it comes from**. Forge › Imports ›
*Import NorgannonDB* builds an import from the open NorgannonDB database (GPL-3.0) aimed at the last analysis' gaps:
drops and vendors for items players cannot get, givers/enders for quests that have none, and trainer spells its
players saw trainers teach. Apply on the PTR, test, export to world-data (credit NorgannonDB in its NOTICE). Trainer
guessing is off (`TRACKER_TRAINER_GUESS=0`). The export also no longer adds loot rows twice when a file runs again.

Since fork `1f787ac9`: Forge › Imports also imports **EG Link** (CC BY 4.0), **ForeverDB.net** (GPL-3.0, credit
"Data from ForeverDB.net") and **Icy Veins** (no licence stated: our server only; runs in the background, about an hour
the first time), each aimed at the analysis' gaps under the same rules as NorgannonDB (fork `docs/SOURCES.md`). Apply
on the PTR, test, export to world-data with the source's credit in its NOTICE.

Since fork `02d1357e`: NorgannonDB vendors and drops are kept only when EG Link, ForeverDB.net or Icy Veins
saw the same creature or chest sell or drop the item on live Forever (alone it brought Classic test vendors: unreleased
mounts, the Panda Collar, soul shards). Run *Import Icy Veins* first; its answers count. Forge › Checks no longer lists
levels whose ranges meet (62 against Wowhead's 61-62).

Since fork `41563272`: Forge › Imports also imports **AtlasLoot Classic Forever** (GPL-2.0, CurseForge), the loot
browser most Forever players run: which boss drops each item, Forever's new dungeons included. The container checks
CurseForge every `TRACKER_ATLASLOOT_EVERY_HOURS` (6) and makes a new import card when a new version is out; nothing is
applied by itself. Drops with no measured chance (AtlasLoot's own or a live recording's) get an even share of their
boss's list, at most 33 % (`TRACKER_ATLASLOOT_GUESS=0`: left out). Its boss tables also count as a second source for
NorgannonDB's drops. Rules in the fork's `docs/SOURCES.md`.

Since fork `12d3faf1`: the first two steps of [the world build](#the-world-build): `tracker.py world layers` and
`world pin` (the layers of sources a world is built from, and the newest version of each), and `world replay` and
`world why` (which file wrote each row of the realm's world). Nothing changes on the website, and the analysis is not
run again.

Since fork `e3b016b0`: **release phases** (the fork's `docs/PHASES.md`). Content the client carries but Forever has
not released yet shows as *Later* instead of missing, and stays out of the coverage and the work list: the first raids
(Onyxia's Lair, Hyjal Summit, Barrow Deeps) until 2026-12-09, then Molten Core, Blackwing Lair, Zul'Gurub, both
Ahn'Qirajs and Naxxramas until Blizzard announces their date. Everlake follows Forever's dates, so `TRACKER_PHASE`
stays empty; set it (a phase key, a number, `all` or `none`) only to run ahead of or behind Forever. A new date or raid
goes into the fork's `tools/phases/forever.json`; the first start of an image with a changed list analyses again by
itself. The first start of this image analyses again once too (the Wowhead checks make that run longer). The same pin
brings more of the world build's export (NPC templates, quest turn-in texts, vendor items sold like the world's other
vendors) and a `karrz` source in `world pin` that notices Karrz's new WoW Forever releases: command-line only, nothing
changes on the website for them.

Since fork `d7fc591f`: the instances WoW: Forever does not use (Season of Discovery's, such as The Tainted Scar,
Karazhan Crypts and Scarlet Enclave, plus the original game's unused Emerald Dream and Caverns of Time) and their bosses
are listed under *Internal / test*, not in the work list. Manor Mistmantle, which is not one of the nine launch
dungeons, waits in a *Later dungeons* phase. That leaves the 28 dungeon maps Forever opened (35 dungeons with the
Scarlet Monastery, Dire Maul, Blackrock Spire and Stratholme wings counted apart). Each phase now opens on its own date.
The first start of this image analyses again once.

Since fork `59e22b81`: the world build's export runs its trial in MySQL's strict mode, the mode the core's updater applies
files in (Karrz 0.1.36 runs them over its own connection), and its stage tables give every column they declare a default.
A file that would stop the realm's start now stops the export instead. Nothing changes on the website; the analysis is not
run again.

Since fork `d3072c91`: gaps that were none are gone. Season of Discovery's raid versions of Blackfathom Deeps, Gnomeregan
and the Sunken Temple, and a fight the client lists twice in an instance, no longer count as bosses of their own (they sit
under *Internal / test*). A boss also counts when a script brings it in instead of a spawn row (its page says so), when the
client misspells it, and by one of its creatures when the encounter is an event (The Seven). Warsong Gulch is no longer
flagged for its five creatures. Boats, zeppelins, script targets and a battleground's nodes are no flight points, and the
Eastern Plaguelands towers need no spawned flight master. Placeholder mounts, pets, toys and recipes (`[PH] ...`) are
internal; unnamed ones stay. Map 3002, an encrypted raid, waits with the first raids. The imports (Icy Veins, NorgannonDB,
EG Link, ForeverDB.net, Wowhead quest enders) look only at the client's own quests, so they ask far less. The first start
of this image analyses again once; an import a restart stopped goes on from its button.

Since fork `9aadbf38`, the report: a boss the instance script creates is found (Gahz'rilla, Darkmaster Gandling, Hurley
Blackbreath, Urok Doomhowl and ten more read "missing"), through a list read from the core's own scripts
(`tools/world/summoned.json` in the fork; run `tools/make_summoned.py` there again when the core pin moves to new
scripts). What a script brings in counts as present for its loot, stock and quests, and Spawns no longer offers to spawn
it for good. Each quest has a *Quest text* check (the giver's text, the turn-in text): a doable quest without its words
reads Incomplete near 90%. Real names are no longer filed as tests (Monster Omelet, Test of Faith). Forever's own copies
of later-raid items, and the Thunderfury and Atiesh chains, wait under *Later*. A quest Wowhead did not know is asked
again after a week.

The website: with `TRACKER_PUBLIC=0` a visitor now gets nothing but the login page (the search and tooltip API answered
anyone, and the login page showed the coverage). A restart no longer logs you out. The footer shows the fork commit the
image was built from. The Forge keeps its rollback before it changes anything. A source's new import card replaces its
earlier ones that were never applied, and an Icy Veins import a restart cut short goes on by itself. The first start of
this image analyses again once.

Since fork `5f3ab0d5`: an import no longer only adds what is missing. It also compares the drops the server already has
with what its source says now, and where a chance moved it proposes the new one on its card (*Creature drop chances
that moved*). Only rows an import brought are touched, by the same source or a more trusted one (Wowhead, then
Questie's data, then Icy Veins, then the others); the core's own rows are counted and left alone. Each change names the
value it replaces and can be rolled back, and a data repo file now names its source by itself. No new analysis at start.

Since fork `3eb898b3`, three things about how fresh the tracker's sources are:

- **The client itself.** The official list used to be read from the server's extracted copy, only when the realm moved
  build. Every `TRACKER_CLIENT_EVERY_HOURS` (6) the tracker now asks Blizzard's version server which Forever build is
  live and reads its tables straight from the CDN when it is newer than the newest one stored. Content the client
  ships encrypted stays hidden, as in the server's own copy; the build is read again as soon as one of its keys is
  published. The first check after this image starts stores the live build and analyses again: what the server does
  not have yet shows as gaps, the changelog shows what Blizzard changed, and the pages say "Server N · client M".
- **Wowhead.** An answer is believed for about 30 days (a week for "does not know it"), then asked again; before, a
  real answer was kept for good.
- **Ask every source again** (The Forge > Imports) makes every answer kept so far count as due. The next analysis and
  the next imports then take as long as the very first ones did.

The game client and the CDN are first in the order of trust, before Wowhead, Questie's data and Icy Veins.

Since fork `52ce9379`: Blizzard's hotfixes. Between two builds Blizzard changes the game's tables by hotfix, and for
WoW: Forever about 5,000 items are in no client table at all and reach the client that way (Carving Knife, Rhahk'Zor's
Hammer, the raids' loot): the tracker never listed them. With every client check it now downloads the hotfix cache of
the live game (a public mirror, refreshed daily) and reads the newest build with the hotfixes over it. The later word
wins: a hotfix over its build's table, the later hotfix over the earlier, a newer build over an older build's hotfix.
The official item list grows by about a quarter, so the coverage number moves. The same image reads spell durations
with the right layout (its schema entry was out of date).

Since fork `c59251bd`: the changelog no longer lists the items that exist by hotfix alone as "added" in the newest build
(they are in no build's tables, so nothing says when they appeared; the page says how many there are), and the
overview counts the resources of the newer client build that the server's data really does not know, instead of
calling all of them unknown. Press *Run again* once after the restart: the changelog of the newest build is written
again.

Since fork `4395bcdc`: *Check the client now* in the Forge, next to *Run again*. It asks Blizzard's servers for a newer
client build and for new hotfixes at once, and runs the analysis only when one of them brought something new; with
nothing new it says so and ends in a few seconds. The container's own first check no longer waits 20 minutes after the
start: it comes a minute after the start's analysis is over, then every six hours as before.

Since fork `67cdd362`:

- **Quests read again from the live game.** *Import EG Link* also compares the quests the realm already has with EG
  Link's newest recording of each (the quest as the live server sent it to a client) and proposes what differs, as lines
  of its card: rewards, XP, texts, objective amounts, money, levels. A recording is taken only from a later client build
  than the row. Flags and the other fields that decide how a quest works are counted on the card, never changed. Read
  the card before applying it; each change has its rollback.
- **Keys from Blizzard's hotfixes.** Time-gated content opens from the keys Blizzard hands out by hotfix, without
  waiting for the public key list. The first client check after this image learns the numbers of the keys the stored
  build waits for, once (about a minute and a half longer).
- The Forge says when Blizzard's servers were last asked and what they answered.
- *Checks*: a ticked level or rank difference takes Wowhead's value through the Forge. Nothing is ticked for you.
- The two druid flight points in Nighthaven no longer read as missing, zones are checked for creatures inside their
  map's rectangle, and a source's earlier import cards fold under its newest one.

The first start of this image analyses again by itself. Redeploy the tracker app after the pull: a restart keeps the
old image.

Since fork `668ae4da`:

- **The quest refresh proposes only what says something else.** Its first run on the whole world proposed 7,400 changes,
  most of them the same thing written another way. It now compares reputation as points (a tier and an override of the
  same amount are one reward), text as it reads (line breaks, spaces, the case of `$n`), never empties a value the
  recording does not state, and does not compare money or the quest's own level (the server sends both for the player
  who asked). A card made before this image must not be applied: *Import EG Link* again replaces it.
- **Whose side a creature is on.** *Checks* gains three tabs: *Faction* (the realm's faction attacks a side that saw
  the creature friendly on live, or befriends a side that only saw it hostile), *Shown to one side* (the realm hides it
  from a side that saw it on live) and *Vendor reputation* (a one-sided vendor whose faction has no reputation, so no
  discount applies). A list to look at: no source states the right faction. It cannot find a creature the realm shows
  to everyone that only one side should see.

The first start of this image analyses again by itself.

Since fork `167a4882`, from reading both lists on the whole world:

- The quest refresh compares a quest's items, choices, currencies and reputations as a list: the same rewards in another
  slot order are no change. *Import EG Link* again before applying a quest card made by an earlier image.
- *Checks › Faction* no longer names a creature whose faction's reputation players earn (a Gelkis centaur is friendly to
  whoever earned it), and *Vendor reputation* lists only vendors on a general faction.

This image does not analyse again at its start: press *Run again* once to refresh the *Checks* list.

Since fork `5c1e52f5`: players' reports from a file. *Imports* gains a *ForeverChanges* section: a pack made from a
copy of that site (`python tools/foreverchanges_pack.py copy.db out.fcpack`, under 1 MB) is sent there and becomes an
import card. The site names NPCs and places them on a map; the tracker matches a name to the realm's creature of that
name standing there and never guesses (a shared name, an unknown name and a creature nobody spawned are counted on
the card). Only what its players saw is taken: who gives and takes a quest marked as seen, vendors, and drops counted
in at least ten kills. The tracker never asks the site.

Since fork `dfac0852`, from the same pack (make it again with the new `tools/foreverchanges_pack.py`: it now carries
the NPCs and pins of the site's maps):

- **Places for what nobody spawned.** NPCs the site's own addon saw (by entry), and rares, commerce NPCs and library
  books (by name), that the realm has a template of and no spawn for, get their reported place. Press *Locate* on the
  *Spawns* page after reading a pack.
- **Whose quest it is.** The analysis compares the side players on live got a quest on with the races the realm offers
  it to. A difference is a check on the quest's page (*Offered to the right side*); nothing changes it by itself.
  Press *Run again* after sending a pack.

The site's turn-in texts are not used: it shows them with the recording player's name where the realm holds a
placeholder.

Since fork `b59ca703`, from reading the first card and the first side check on the whole world:

- A drop players saw once is no longer taken, and an item fifteen or more different creatures drop is a world drop and
  left out: the first card was nine tenths Waylaid Crates listed under every creature that happened to die when one
  fell.
- *Offered to the right side* only asks about a quest the realm keeps to one side. The first version compared the
  side in players' reports with the races a quest is offered to and named about 300 quests wrongly: most quests are
  offered to every race, and their giver's faction keeps the other side out.

Press *Run again* after this image, and *Read the pack again* on the Imports page: the earlier card and the earlier
side findings are replaced.

Since fork `3879fbbc`:

- **The pack is the full file.** `tools/foreverchanges_pack.py` writes a zip of under 10 MB: the lists the tracker
  reads, and beside them every data file of the site in English as the crawl has it, kept for later versions. Send
  this one on the Imports page; the earlier small pack is still read.
- **What the NPC says at the turn-in** comes from the reports too, for the quests players saw that have no such text
  on the realm. The site's marks for the player's name, class and race become `$N`, `$C` and `$R`. A text that may
  still hold the recording player's own name is left out and counted on the card. Where EG Link recorded the same
  window, its wording is taken first.

Since fork `93bcb522`: the quest givers, enders and vendors of the players' reports that nobody spawned on the realm
get the place the report gives them (when exactly one template has their name). *Read the pack again* on the Imports
page, then *Locate* on the Spawns page.

Since fork `c92e67cb`: a quest giver, ender or vendor of the players' reports that nobody spawned still gets its row,
when exactly one template has the name. Before, the reported place was kept and never used: the locator only places
what the realm's data says it needs, and nothing said so. *Read the pack again*, read the card, apply it, then *Run
again* and *Locate*: those NPCs show as ready to place where players met them.

Since fork `b1d38f76`: spells and achievements are judged by how the game hands them out. A spell a talent or perk
tree grants, or one that comes with learning another spell (the new profession rank spells), counts as learnable. A
spell nobody learns (the game data marks it as never learned, or another spell casts it) and a spell only a test or
Season of Discovery item teaches are listed under *Internal / test*. What stays on the list names the item that
teaches it. An achievement that rewards a Legacy Point needs no `achievement_reward` row: the core pays the point
once the achievement is earned. The analysis runs again by itself after the redeploy.

Since fork `8ea3e7be`: a recipe of the original game whose only teaching item is missing from the client stays on
the list (the Naxxramas frost resistance sets, Onyxia Scale Cloak, quest recipes): the pattern was never used and
the recipe is taught another way. A missing item files a spell under *Internal / test* only when the spell is a
Season of Discovery addition.

Since fork `5cacbd34`: a spell or recipe that cannot be learned yet says what it waits for, from the realm's own
data: the trainer that lists it and is not spawned (by creature ID), or the quest that rewards it and cannot be done
yet (by quest ID, a reward spell that teaches the recipe included). Only when neither exists does it name the item
that teaches it.

Since fork `4f517337`: the changelog goes back to the first beta. Every client check now also stores the builds that
came before the newest one stored, each once: the list of builds is wago.tools', the files are read from Blizzard's
CDN (WoW: Forever's beta shipped under the Classic beta's product name, `wow_classic_beta` 1.60.x). Each build then
has its own changelog page, beta builds are tagged, and a build that changed the program alone says "no data change"
(16 of the 30 builds up to 1.60.1.70938). The first check after this image starts reads the missing builds (about
50 MB and a quarter of a minute each, plus 125 MB of shared indexes) and analyses again: about a quarter of an hour,
once. They take about 15 MB each in the tracker's data volume. No new analysis at start by itself; **Check the client
now** in the Forge does it at once.

Since fork `51296471`: the original game's database (cmangos' classic-db, GPL-3.0) is a source, asked last and only
about profession recipes nobody can learn on the realm. The tracker never downloads it: make a pack from the
project's dump (`python tools/classicdb_pack.py ClassicDB_1_12_1_….sql.gz out.cdbpack`, about 150 kB) and send it on
the Imports page, under *Classic database*. The card proposes trainer rows at the trainers the realm has for those
creatures, and a reward spell for quests that cast nothing at the turn-in. A recipe Classic teaches through a line
of a creature's conversation needs a script, not a row: it is counted on the card and not written.

Since fork `e5f710f8`: on the Forge and on Spawns the page's title sits above the analysis card. Side by side, the
card took the whole row whenever its lines were as wide as the page, and the heading was drawn under it.

Since fork `385429dc`: the changelog starts at the original game. Patch 1.12, as Blizzard published it again in 2019
(the client WoW Classic launched with, 1.13.2.31650), is stored once as the build before the first beta, and the
first beta build has a page of what it added, changed and does not have against it. "Not in Forever" there is not
"removed": most of it is content that is not released yet (the later raids' loot). Every analysis also replays the
chain: the original game and every build's changes must give the newest build, resource for resource; the log says so
in one line and the original game's page shows it by kind. The first client check after this image starts stores the
original game (19 tables from wago.tools' public exports, about 13 MB) and analyses again, working every build's
changes out once more: a few minutes, once. **Check the client now** in the Forge does it at once. The tracker's
tooltips also give bows, guns, thrown weapons and wands the stats the game gives them (they showed too much before).

Since fork `44e42a6e`: the *Classic database* card asks only about recipes Forever kept (the old healing potions,
which Forever replaced, are no longer proposed at every alchemy trainer). A creature the original game trained at,
that stands in the world here without a trainer list (the Triage doctors, Henry Stern), gets one: a list numbered
1,000,000 plus the creature's number, the link to it and its recipes, and applying the card adds the trainer flags.
Press *Read the pack again* under *Classic database* after the redeploy: the card made before it is out of date.

Since fork `af342c41`: a recipe taught in a conversation counts as learnable. The analysis reads the realm's
conversation menus and the SmartAI of a menu choice that casts a spell, on spawned NPCs and objects, and one core
script known to teach on Forever (Gloom'rel's Smelt Dark Iron); the spell's page says "taught in a conversation".
The engineering transporters' core script is left out: it checks a skill line the Forever client lacks and teaches
nobody. The analysis runs again by itself after the redeploy.
Since fork `f9b5cefd`: Blizzard's hotfixes are entries of their own. Every hotfix cache that differs from the one
before is kept with its build (`data/builds/<build>/hotfixes/`, about 1 MB a day in the tracker's data volume), and
each later day's hotfixes get a dashed "Hotfixes of <day>" card on the home timeline and their own changelog page
(`/changes?build=70938&hotfix=1`). The history starts with the cache the tracker holds at the redeploy: earlier days
are not on the mirror any more. The first analysis after the redeploy works every build out again once (a few
minutes); the site reads the old analysis until it is done.
Since fork `434b83ef`: **checkout**. The Forge's new *Checkout* page writes the client's data at any step of the
timeline (a build, or a build and a day's hotfixes) as an SQL file for a **test realm's** hotfixes database: every
record that differs from the realm's own DB2 files (`DATA_DIR/dbc`), and what those have that the step does not, as
one hotfix push. *Make* builds it in the background (a build stored for the changelog alone first reads its other
tables from Blizzard's CDN, about 40 MB, once), then the page hands out the file. Loading it replaces the tables it
names: load it into a test realm, never the live one, restart that worldserver and clear the game client's `Cache`
folder. The same from a shell: `tracker.py checkout list` and `tracker.py checkout <step> --fetch`. The fork's
`docs/CHECKOUT.md` says what a checkout cannot say. `world replay --at <step>` (or `--until <date>`) stops the world
replay at that step's day, to pair with it. The first analysis after the redeploy works every build out again once
(a few minutes), as the table reader changed.
Since fork `2d8e4190`: the *Classic database* card writes the conversation lines that taught a recipe in the original
game and are missing here: the line (`gossip_menu_option`, in the conversation the NPC or object already opens, or a
menu of its own numbered 1,000,000 plus a creature's number or 2,000,000 plus an object's), Classic's conditions on it
and on the lines leading to it (`conditions`: skill, quest done, reputation, level, recipe known), and SmartAI that
teaches the recipe and closes the conversation; AIName and the gossip flag are filled only where empty. Gloom'rel gets
the core's own script name instead. An NPC run by another core script or AI, a shared conversation or a line already
there is left out and counted. The card needs a pack of the new format: build it again (`tools/classicdb_pack.py`)
and upload it under *Classic database* after the redeploy.
Since fork `cfdddc63`: a checkout takes the server's build from the realm list when config.ini does not say it, as the
analysis does (Everlake's tracker sets no `[server] build`).
Since fork `28431116`: **Wowhead pages** (The Forge › Imports). Wowhead refuses page requests from a script, so a
crawler file the page hands out runs in a browser tab on wowhead.com/forever at a pace it learns from Wowhead's blocks,
and `WHC.save()` downloads what it read (numbers only: drops, sellers, quest givers and enders). Sending that file
merges it into the tracker's data volume and makes an import card, under the same rules as every source. The tracker
itself asks Wowhead for nothing. The Imports page also says now that the *Classic database* card writes conversation
lines.

Since fork `7610863e`: **Icy Veins is mirrored whole.** *Import Icy Veins* keeps every NPC, object, quest, item,
zone, flight path and map Icy Veins lists (about 67,000 answers, gzipped in the data volume under `icyveins/`), the
gaps first: the first run takes about nine hours in the background, later runs only ask what is older than 14 days.
`FT_ICYVEINS_MAX` defaults to 100,000. Skinned leather and hides now go to `skinning_loot_template` and pick-pocket
loot to `pickpocketing_loot_template` (they used to be written as corpse loot; such rows an earlier card applied stay
until removed by hand). The card also brings chest and node contents, quest-only drops, quest givers and enders from
every side, turn-in words, and the innkeeper / banker / flight master / spirit healer flags an NPC lacks; the locator
places creatures Wowhead cannot from where players saw them. Also since `28431116`: Wowhead pages reads npc and
object pages (#78) and the whole Forever and Classic crawl (#75). The fork's `docs/ICYVEINS.md` lists all Icy Veins holds.
Since fork `ea62dc26`: the core's own Classic scripts that teach count as teachers: Master Craftsman Omarion's 13
Naxxramas recipes and the Field Repair Bot 74A schematic (an object, used at Engineering 300). Knot Thimblejack's and
the engineering transporters' scripts stay out until the core fork's fix (core PR 60) runs on the realm. On the
*Classic database* card, Gloom'rel, who runs SmartAI here (his challenge), gets a SmartAI line teaching Smelt Dark
Iron, and lines of a core-scripted teacher are counted as "the core teaches it" or "needs the core fix". The
analysis runs again by itself after the redeploy (marker 18). Also: the Wowhead crawler reads an empty id range as
empty instead of splitting it without end (#79).
Since fork `dc55eb9f`: a conversation choice that calls a SmartAI timed action list counts what that list casts.
That is how Gloom'rel teaches Smelt Dark Iron on Everlake, so it counts as taught now. Omarion's core script casts
pattern spells the Forever client lacks (all but Plans: Icebane Breastplate), so only that one recipe counts until
core PR 60 is live. The analysis runs again by itself after the redeploy (marker 19). Also: the Imports page's Icy
Veins text describes the whole mirror (#80).
Since fork `fc4851a6`: a conversation choice also counts the SmartAI rows it links to (Gloom'rel's choice closes
the window and links to the row that calls his teaching list), and only what a conversation's spell teaches counts as
learned, not the buff or teleport it casts. On the world data the realm started from that makes 15 recipes and
specializations taught by talking (Smelt Dark Iron, Wild Leather, the blacksmithing specializations, Goldthorn Tea,
Troll's Blood Elixir, Fishing), where their NPCs stand. The analysis runs again by itself after the redeploy (marker 20).

Since fork `61ddffa0`: *Import Icy Veins* makes an **early card** ("Icy Veins <date> (gaps)") as soon as the items,
quests and trainers the server lacks are all asked, a few minutes into a run that goes on from its mirror; the full
card at the end replaces it unless something was applied from it. Also Wowhead pages reads Classic pages (#82).

Since fork `3898aeaf`: *Import Icy Veins* writes the profession recipes trainers teach, with the skill and rank
each needs (Icy Veins records them now); a trainer keeps only its own profession's recipes. Also source snapshots
(#86: each import keeps what its source said, to show what changed) and Wowhead pages keeps every number (#84).

Since fork `1674b9dd`: a trainer card's spell goes only to a trainer list that already teaches its kind (the same
profession's skill line, or class spells): one creature can open several lists and one list serve several creatures,
and an Icy Veins bandage had landed on a blacksmithing list. Also cards made from the database (#87:
`source-import.php <source> --from-database`, seconds instead of hours) and the source store (#89).

Since fork `56627204`: that check goes by the trainer list's type (`trainer`.Type 2 = a profession): a profession
list takes recipes of its own profession (its rank spells do not count against it) and no class spell; other lists
take class spells only.
Since fork `d5ace13d`: Knot Thimblejack (Gordok Ogre Suit), Zap Farflinger and Jhordy Lapforge (the engineering
transporters) and Master Craftsman Omarion (13 Naxxramas recipes) count as teachers: core `f6bb68c6` (core fork PR 60),
live since 2026-11-15, fixed their scripts. The analysis runs again by itself after the redeploy (marker 21).

Since fork `1fc99a5a`: Icy Veins lists past its 10,000-row cap. Without an API key its list pages stop at row
10,000 (HTTP 400 "narrow the filters or sort, or use an API key"), which stalled *Import Icy Veins* on the NPC list.
Lists are now read from both ends (`dir=desc`): every kind is listed whole but items (20,000 of about 32,000), whose
rest come from what the NPCs, objects and quests name.
Since fork `eb7d62c6`: spells that aren't WoW Forever content are listed under *Internal / test* instead of
Incomplete: Season of Discovery spells nothing or only Season items teach, original spells nothing teaches that the
original game taught nowhere either (read from the Classic database pack under Imports; procs, passives, old talent
ranks), and the "Test Profession [DNT]" line. Incomplete spells should go from 646 to about 340. The analysis runs
again by itself after the redeploy (marker 22), and the first run re-reads every client build once (a few minutes).
Since fork `5a6fb589`: the Classic database pack (format 3, rebuild it with `tools/classicdb_pack.py`) also carries
Classic's drops and vendors of recipes and items learned on use, and the items the original game gave out nowhere.
The *Classic database* card proposes those drops and vendors for items players cannot get (world drops left out); the
analysis lists original items the original game never gave out, and the spells only they teach, under *Internal /
test*. It reads the pack: after the redeploy send the new pack under Imports › Classic database, then run the
analysis again (marker 23).
Since fork `3995a9c6`: the Imports page loads again once a source has kept a snapshot (it stopped at the *What the
sources said* table), and the Wowhead pages crawler reads the most valuable pages first (#96).
Since fork `70566e32`: the list of what the core's scripts bring in is read again from the core the realms run
(`f6bb68c6`) and in more shapes: a script's own summon helper, an array a summon picks from, an instance's entry swap.
570 to 623 creatures, among them Grizzle (Ring of Law), Solakar Flamewreath (rookery) and Bannok Grimaxe, whose
plans and schematic become obtainable. The analysis runs again by itself after the redeploy (marker 24).

Since fork `1400cb23`: Blizzard's hotfixes back to the beta, dated from the stored builds (each row by the first build
that carries it), one timeline entry per build window instead of one for all (#100); notes for every day from
Blizzard's blue posts (its forum's JSON), Icy Veins' hotfix articles and ForeverChanges' patch notes, each line marked
"In the client data" or "Server side"; `tracker.py notes`, part of the client check. Also a Wowhead page without a
*Dropped by* tab no longer stops the crawl (#99). The first check after the redeploy reads the notes (~3 min) and dates
the hotfixes (~7 min) before the analysis.
Since fork `374f6e3c`: **holiday spawns** from the Classic database pack (format 4: rebuild it with
`tools/classicdb_pack.py` and send it after the redeploy; an older tracker refuses it). Under *Classic database*, a
button per holiday makes a card of what the original game spawns while it runs: the **Darkmoon Faire** (new events 4
Elwynn Forest and 5 Mulgore, on Forever's holidays 263 and 264, whose dates the core reads from the client) and the
**Stranglethorn Fishing Extravaganza** (the realm's events 14, 15 and 62). The world data export writes each holiday
link with its spawn's number in the file. Restart the worldserver after applying: events are read at start.

Since fork `b3931f8c`: one hotfix card a day (the container reads the mirror several times a day), windows named from
their build's release to the day before the next build, Icy Veins' development notes shown with their build (#103).
After the redeploy press *Run again*: the windows are re-named from the stored dating in seconds, then the changelog
is worked out again (~15 min).

## The world build

The fork is becoming the tool that builds the realm's world data (its `docs/WORLD-BUILD.md`). The part that exists
replays the world a realm runs (the release dump, then every update file in the updater's order) in a scratch
database, and notes which file created, changed or removed each row:

```bash
sudo docker exec -u www-data <tracker container> sh -c 'python3 tools/tracker.py world replay --dump /world/current/TDB_full_world_*.sql --core /world/current/core --data /world/current/data --folder everlake=/world/current/everlake'
sudo docker exec -u www-data <tracker container> python3 tools/tracker.py world why creature_template 248415
```

`sudo docker ps` shows the container's name (the app's `tracker` service). The replay drops and rebuilds its scratch
database each time and writes nowhere else; it loads the whole release and several hundred files, so give it a while.

**Its own MySQL user.** Update files are other people's SQL, so the replay refuses to start unless its user can
write to the scratch database only; the tracker's normal user (which writes the PTR's databases) is refused. Set
`TRACKER_BUILD_DB_PASSWORD` in `.env` and restart the app: `scripts/tracker-setup.sh` then makes `tracker_build` with
every right on `ft_world_build` (`TRACKER_BUILD_DB`) and none on any other database. Every start takes all its rights
away first and gives these back. The scratch name must start with `ft_` (no realm, login or tracker database does),
and a database holding tables no replay made is refused. The website's user `tracker` may read the scratch database
(what a replay found) and write nothing there. Without the password, or with a refused name, `tracker_build` is left
locked with no rights (never made, if it was not there), `tracker` gets no read right from the world build, and
`tracker-init`'s log says so; the website starts either way.

**Its files are the realm's.** On every start of the app, `tracker-world-copy` runs inside the live realm's own image
(`everlake-trinitycore:live`, or `EVERLAKE_IMAGE_TAG` when `.env` sets it; `TRACKER_WORLD_IMAGE_TAG` for another, such
as the PTR's `ptr-<core>-<world data>`) and
copies what that image was built from into the `tracker-world` volume: the release dump its worldserver imports, and
its `sql/updates/world` and `sql/custom/world`. Nothing is downloaded again, so the replay reads the same bytes the
realm applies. `tracker-world-sort` then tells the image's custom files apart, because the replay labels each row with
the kind of file that wrote it:

| In `/world/current` | Files | Label |
|---|---|---|
| `TDB_full_world_*.sql` | the release dump | the release |
| `core/sql/updates/world`, `core/sql/custom/world` | the core's own | `core updates`, `core custom` |
| `data/` | wow-everlake-world-data's `sql/world` at the image's `WORLD_DATA_COMMIT` | `data repository` |
| `everlake/` | the files the `Dockerfile` of this folder copies into `sql/custom/world` | `everlake` |

The data repository is asked for its file names only (once per commit), and each of its files is compared with the
image's copy; `/world/current/source.txt` and the app's log say what the set was made from and anything that did not
match. Each start removes the set of the start before, so when anything goes wrong (the names cannot be fetched, the
image is not an Everlake image, the disk is full) there is no `/world/current` and the log says why: the website runs
either way. After `scripts/promote.sh` or a new PTR image, restart the tracker app to copy the new image's files. The
volume holds a second copy of the release dump.

The image must exist on the server, with or without a world build, or the app does not start.

A MySQL server that writes a binary log lets only an administrator create triggers, which the replay needs.
`docker-compose.yml` starts MySQL with `--skip-log-bin`, so nothing is needed here; on another server
`tracker-init`'s log says what an administrator runs once (`SET GLOBAL log_bin_trust_function_creators = 1`).

## Not used here

- ForeverScribe (records vendors, loot and quest givers while playing on the official realms): the container has
  no game client to read its notes from.
- The `.forge` core module and the remote console (spawning on the running server): the PTR has neither; the Forge's
  database spawn mode works, then restart the PTR.
