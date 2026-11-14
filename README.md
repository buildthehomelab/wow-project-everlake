# Project Everlake

A private World of Warcraft server built on the **WoW Forever** client (1.60.x, the modern 64-bit client that runs
natively on Apple Silicon). The goal is one client for every ruleset: Forever, Classic to WotLK, and retail, picked
in the client's ruleset screen.

Status: **spike**. Nothing here is playable yet. The first job is to prove these things:

1. **Server runs**: the TrinityCore `forever` core builds from source, a frozen client logs in and walks around.
2. **Custom files load**: the client draws world files it doesn't ship (Outland, Northrend, the post-Cataclysm
   world), served from our own patch server. This decides whether one client can run every ruleset
   ([notes](docs/custom-files.md)). Experiment 1 **passed** 2026-11-06: the client streamed and drew a replaced
   icon from our own build. Experiment 2 **passed** 2026-11-07: the client drew TBC Sunstrider Isle on map 530, which
   it doesn't ship. Next: server-side terrain for map 530, then all of Outland.
3. **The world feels alive**: PlayerbotV2 bots go where real players are and sleep elsewhere; find the number of
   bots each kind of place needs, check that bots on screen act like players (they wave back), and measure the
   cost per bot ([plan](docs/living-world.md)).
4. ~~Characters move~~: dropped. Everyone starts fresh.
5. **Each ruleset has its own era**: a second realm sends the client TBC warrior talents and spells, and switching
   between realms switches the data without mixing ([plan](docs/era-data.md)).

## What's here

| Path | What it is |
|---|---|
| `Dockerfile` | Builds worldserver, bnetserver and the extractors from a **pinned** commit of the core |
| `docker-compose.yml` | MySQL, worldserver, bnetserver and the extractor |
| `docker/extract.sh` | Extracts server data straight from Blizzard's CDN (no installed client needed) or from a client folder |
| `docker/entrypoint.sh` | Writes the server configs from the environment on every start |
| `docker/patches/` | Fixes on top of the core that aren't merged upstream yet |
| `scripts/gen-certs.sh` | Your own root CA (limited to `*.actual.battle.net`) and the login server certificate |
| `tools/forever-data/` | Public Forever data pinned daily into its own database, and a report of what Everlake's world lacks ([notes](tools/forever-data/README.md)) |
| `docker-compose.tracker.yml` | ForeverTracker: what of the official Forever content players can get here, SQL fixes applied on the PTR, and the world build's replay of the realm's world ([notes](docs/forever-tracker.md)) |
| `tools/tact/` | Gate 2: `patch.py` makes a build that is Blizzard's plus our files, `cdn.py` serves it ([notes](docs/custom-files.md)) |
| `client/macos/everlake-client.sh` | Sets up a Mac to play here (hosts entry, CA, key patch, game copy) and starts the game |
| `docs/client-connection.md` | What a client needs to connect, and why |

## Pins

| What | Value |
|---|---|
| Core | [buildthehomelab/wow-trinitycore-everlake](https://github.com/buildthehomelab/wow-trinitycore-everlake) @ `b1ba6dfa` (fork `everlake`: advocaite's `forever` 2ae1313e + forever-bots + the reviewed advocaite pull requests, fork PRs #4-#19, TrinityCore master batches A-K, Karrz v0.1.33 world data and scripts, Karrz v0.1.34 world data, the Ring of Law arena and the bot module at 0.1.34, bot dual names, the Wintergrasp condition fix, Karrz v0.1.35 with his whole core catch-up, the Zephras Isle scene NPC fix, Karrz's 37 git commits after 0.1.35 with the 0.1.35 gaps, pet Move To / Stay and water pathing, name lookups that keep the surname, Karrz v0.1.36, hunter pets on WoW Forever's rules), bots on. The live app and the PTR app build the same commit, so either one makes the same image |
| Client | WoW Forever **1.60.1.70938**, the build the launcher installs; 1.60.1.70790, 70862 and 70888 clients are also let in (`Realm.AlsoAcceptBuilds`) |
| World DB | `forever-tdb-2026-10-14` release of the same repository |
| ForeverTracker | [buildthehomelab/wow-forever-tracker](https://github.com/buildthehomelab/wow-forever-tracker) @ `167a4882` (`docker-compose.tracker.yml`) |

The server, the client and the extracted data must all be the same build. Battle.net updates the client on its own,
so freeze it before testing, and check the CDN build before extracting:

```sh
curl -s http://us.patch.battle.net:1119/wowf/versions | grep '^us|'
```

70790, 70862 and 70938 have the same table layouts and the same map files; only table contents differ. Between
70862 and 70938, 112 of 1,245,658 files changed: 79 tables, 28 interface files and 5 programs, and no map, model or
texture file (compared file by file on Blizzard's CDN on 2026-11-14). All 370 tables the server loads have, in 70938,
the layout the pinned core expects. 35 of them hold sections locked by three keys Blizzard has not published
(`0DA4670DB36FB2A9`, `DA0E7785727A0A65`, `3146BA4C4ECDBFAB`); those sections are the same size in 70862 and 70938,
so new tables lose nothing the server could read before. Data extracted from 70790 or 70862 still loads.
To bring the tables up to 70938 without redoing maps, vmaps and mmaps: `DBC_ONLY=1 docker compose run --rm extractor`.
The live realm and the PTR read the same data folder, so copy `dbc` and `gt` aside first; a worldserver reads the
tables only when it starts, so the running realm is not touched until its next restart.

Some maps exist only on the server: map 3200, the Ring of Law arena, is Blackrock Depths (230) under its own id, with
its Map row in the hotfixes database, so the client files have nothing for it. The extractor copies map 230's maps,
vmaps and mmaps to 3200 after every extract and mmaps run (`MAP_COPIES`, default `3200:230`), and the PTR does it on
each start (`ptr-mmaps`). On data that is already extracted: `MAP_COPIES_ONLY=1 docker compose run --rm extractor`
(seconds).

## Run it

Needs Docker, about 8 GB of RAM to build (4 GB to run) and about 20 GB of disk.

```sh
cp .env.example .env               # set the passwords
./scripts/gen-certs.sh             # your own CA + server certificate (never share certs/ca/*.key)
docker compose build               # compiles TrinityCore, takes a while
docker compose run --rm extractor  # game data from Blizzard's CDN into ./data
EXTRACT_MMAPS=1 docker compose run --rm extractor  # or this instead: also the bots' navigation meshes (long)
docker compose up -d
docker compose logs -f worldserver # the first start imports the database
```

Create an account from the worldserver console:

```sh
docker compose attach worldserver   # leave with Ctrl+P, Ctrl+Q
bnetaccount create mail@example.com Password
```

### Bots

`PLAYERBOTS=1` (the default; with a core commit that has the module, `src/modules/PlayerbotV2`: the fork's `everlake` branch) builds
the WoW Forever Bots into the image, switched on with the module's own defaults, except on the live realm: 500 world bots, a modest crowd around each player (30 in a leveling zone, 80 in a town, 15 in a start zone) and the rest waiting in towns and quest hubs all over the world (`BOTS_*` in `.env`, see `.env.example`), the auction house bot,
raid bots and dungeon finder fill. Change any other setting in `overrides/playerbot.conf` (`Key = Value` lines, read after
the defaults); the keys are in the module's `playerbot.conf.dist` and `zz-forever-bots.conf`. Realm 2 runs no world,
auction house or dungeon finder bots.

The bots need three things the server didn't before:

1. **Their database** (`playerbot`): the `bots-init` service creates it before worldserver starts
   (`docker/mysql-init/02-playerbot.sh`), and worldserver fills it on its first start with the bots.
2. **Navigation meshes** (`data/mmaps`): the PTR app builds them when there are none (`ptr-mmaps`), or
   `MMAPS_ONLY=1 docker compose run --rm extractor` (long: tens of minutes on many cores).
3. **`MMAP_PATHFINDING=1`** in `.env`, so worldserver loads them. Without 2 and 3 the bots stand still, and
   worldserver says so at start.

The first start with bots creates the bots' accounts and characters in the background, which takes a while; bot log
lines go to `logs/Playerbot.log`.

**Dynamic respawns.** With hundreds of bots, quest mobs and herb/ore nodes would be camped empty. Every realm runs
`Respawn.DynamicMode = 1`, and `sql/everlake/2026_11_09_00_world_dynamic_respawn.sql` (in the image, applied by
worldserver) puts 56,330 quest creatures, 9,250 quest objects and 20,789 herb and ore nodes into the core's dynamic
spawn groups (2 and 4). Up to 20 players in a zone (bots count), nothing changes; at 40, they respawn twice as fast; at
100, five times as fast, never under 30 s for mobs and 60 s for herbs, ore and quest objects (`RESPAWN_*` in `.env`,
set as the core's `Respawn.Dynamic*` keys by the compose files; a restart applies them).

### PTR

The PTR (realm 73, "PTR", port 8097) is where a new build runs before a live realm: its own image, its own
`world_ptr`, `hotfixes_ptr`, `characters_ptr` and `playerbot_ptr` databases, few bots, GM accounts only. It is a
TrueNAS app of its own from this folder (`docker-compose.ptr.yml`), and does everything itself when it starts: builds
its image (bots on, the world data pinned in `docker-compose.ptr.yml`, or `PTR_WORLD_DATA_COMMIT` from `.env`) if it's missing, sets up its databases and realm row
(`scripts/ptr-setup.sh init`), builds the mmaps if there are none, then starts its worldserver. Nothing runs on the host
but `git pull`.

1. `git pull`, then start (or restart) the `everlake-ptr` app, and try it.
2. Good: `sudo scripts/promote.sh`, then restart the `everlake` app. No rebuild and no `.env` edit: realm 1, the login
   server and the extractor run `everlake-trinitycore:live`, and the script points that tag at the image the PTR's
   worldserver ran (the one before stays as `live-previous`). Realm 2 keeps its own (`REALM2_IMAGE_TAG`, default `latest`).
3. Back: `sudo scripts/promote.sh rollback` (swaps `live` and `live-previous`), then restart the `everlake` app.

`sudo scripts/promote.sh status` shows what `live`, `live-previous` and the PTR run and what each was built from, and
the worldserver prints it at every start (`[entrypoint] image live: core ..., world data ..., bots ...`). The first
promote also keeps the image live is running as `live-previous` and comments out an old `EVERLAKE_IMAGE_TAG` line in
`.env` (with a dated backup), which would otherwise win over the `live` tag. `MMAP_PATHFINDING=1` stays in `.env`.
Don't run `docker compose build` for the `everlake` app on a server that has a `live` image: it would replace `live`
with an untested build. The app builds by itself only when there is no `live` image yet (a new install).

Start the PTR app first, so it builds the tag. Both apps build the same core with the bots, but only the PTR has run it.
Every worldserver started as a PTR tag checks the image against the tag (`image-build.env`, written at build) and prints
`[entrypoint] ERROR: image ... is not the PTR build its tag names` when they differ, e.g. an image an older checkout of
the `everlake` app built without the bots. Then remove that tag (`docker image rm everlake-trinitycore:<tag>`), start the
`everlake-ptr` app so it builds it again, and restart the `everlake` app.

## Play from a Mac

Connecting needs three things on the player's Mac: a hosts entry for the login server, the CA certificate trusted,
and the server's key given to the client ([why](docs/client-connection.md)). With the Forever client installed by
Battle.net (and Battle.net quit, so it can't update the game) and Apple's command-line tools
(`xcode-select --install`):

```sh
./client/macos/everlake-client.sh setup <server address> forever_root_ca.crt   # once, and after game updates
./client/macos/everlake-client.sh play <account email>                        # asks for the password
./client/macos/everlake-client.sh undo                                         # removes everything again
```

Not tested yet. Windows: not written yet.

## Checks

CI (`.github/workflows/ci.yml`) runs on every pull request. It does not compile the core.

- `tools/ci/check-patches.sh [commit]`: `docker/patches` still apply, to the pinned core and to the forever-bots
  core. When you bump `TC_COMMIT`, run this first. When the bots core changes, bump the commit in the workflow too.
- `tools/ci/check-repo.sh`: the core pin is the same in the Dockerfile, `docker-compose.yml` and `.env.example`,
  and the `sql/everlake` file names follow the `YYYY_MM_DD_NN_<database>_<what>.sql` pattern with no number used twice.
- shellcheck, ruff (bug rules only), luacheck for `client/addons`, `docker compose config`, and a clang build of
  `client/macos/keypatch.c` with the Mac client's Python parsed on 3.9.

## Credits

- [advocaite/TrinityCore](https://github.com/advocaite/TrinityCore) `forever` branch, GPL-2.0: the server core
  (not an official TrinityCore branch).
- [jibay442/forever_docker](https://github.com/jibay442/forever_docker), GPL-2.0: the Docker build, entrypoint,
  extractor script, certificate script and the contact-list patch started there.
- [TrinityCore](https://github.com/TrinityCore/TrinityCore), GPL-2.0.

No Blizzard files are in this repository. The server data is extracted from Blizzard's own client files.

## License

GPL-2.0, see [LICENSE](LICENSE).
