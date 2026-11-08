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
| `tools/tact/` | Gate 2: `patch.py` makes a build that is Blizzard's plus our files, `cdn.py` serves it ([notes](docs/custom-files.md)) |
| `client/macos/everlake-client.sh` | Sets up a Mac to play here (hosts entry, CA, key patch, game copy) and starts the game |
| `docs/client-connection.md` | What a client needs to connect, and why |

## Pins

| What | Value |
|---|---|
| Core | [buildthehomelab/wow-trinitycore-everlake](https://github.com/buildthehomelab/wow-trinitycore-everlake) `everlake` @ `d4fcfa58` (2026-11-08): advocaite's `forever` @ `2ae1313e` plus `forever-bots` (the bot module) |
| Client | WoW Forever **1.60.1.70862**; 1.60.1.70790 clients are also let in (`Realm.AlsoAcceptBuilds`) |
| World DB | `forever-tdb-2026-10-14` release of the same repository |

The server, the client and the extracted data must all be the same build. Battle.net updates the client on its own,
so freeze it before testing, and check the CDN build before extracting:

```sh
curl -s http://us.patch.battle.net:1119/wowf/versions | grep '^us|'
```

70790 and 70862 have the same table layouts and the same map files; only table contents differ (spells, items and
about 80 other tables, compared file by file on Blizzard's CDN on 2026-11-08). Data extracted from 70790 still loads.
To bring the tables up to 70862 without redoing maps, vmaps and mmaps: `DBC_ONLY=1 docker compose run --rm extractor`.

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

The image builds the WoW Forever Bots module (`src/modules/PlayerbotV2` in the core fork) and switches it on with the
module's own defaults: up to 250 world bots (around players, in towns and at start zones), the auction house bot,
raid bots and dungeon finder fill. Change any setting in `overrides/playerbot.conf` (`Key = Value` lines, read after
the defaults); the keys are in the module's `playerbot.conf.dist` and `zz-forever-bots.conf`. Realm 2 runs no world,
auction house or dungeon finder bots.

The bots need three things the server didn't before:

1. **Their database** (`playerbot`). A new MySQL volume gets it from `docker/mysql-init`; on an existing one, once:
   `docker compose exec mysql bash /docker-entrypoint-initdb.d/02-playerbot.sh`. worldserver fills it on its next start.
2. **Navigation meshes** (`data/mmaps`), from the maps and vmaps already extracted:
   `MMAPS_ONLY=1 docker compose run --rm extractor` (long: tens of minutes on many cores).
3. **`MMAP_PATHFINDING=1`** in `.env`, so worldserver loads them. Without 2 and 3 the bots stand still, and
   worldserver says so at start.

The first start with bots creates the bots' accounts and characters in the background, which takes a while; bot log
lines go to `logs/Playerbot.log`.

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
