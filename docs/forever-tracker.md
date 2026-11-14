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
