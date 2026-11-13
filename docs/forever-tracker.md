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
