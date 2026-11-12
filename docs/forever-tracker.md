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
2. The PTR app runs (the tracker reads its databases).
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

## Not used here

- ForeverScribe (records vendors, loot and quest givers while playing on the official realms): the container has
  no game client to read its notes from.
- The `.forge` core module and the remote console (spawning on the running server): the PTR has neither; the Forge's
  database spawn mode works, then restart the PTR.
