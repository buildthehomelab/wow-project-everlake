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
| `scripts/extract-extra-map.sh` | Server terrain (maps, vmaps, mmaps) for a map the client only gets by hotfix, such as 530 ([notes](docs/custom-files.md#server-terrain-for-map-530-2026-11-07)) |
| `tools/mapcheck/map_height.py` | Ground height and area id from the extracted `.map` files, the way the server reads them |
| `scripts/gen-certs.sh` | Your own root CA (limited to `*.actual.battle.net`) and the login server certificate |
| `tools/tact/` | Gate 2: `patch.py` makes a build that is Blizzard's plus our files, `cdn.py` serves it ([notes](docs/custom-files.md)) |
| `client/macos/everlake-client.sh` | Sets up a Mac to play here (hosts entry, CA, key patch, game copy) and starts the game |
| `docs/client-connection.md` | What a client needs to connect, and why |

## Pins

| What | Value |
|---|---|
| Core | [advocaite/TrinityCore](https://github.com/advocaite/TrinityCore/tree/forever) `forever` @ `6ac7bece` (2026-11-06) |
| Client | WoW Forever **1.60.1.70790** |
| World DB | `forever-tdb-2026-10-14` release of the same repository |

The server, the client and the extracted data must all be the same build. Battle.net updates the client on its own,
so freeze it before testing, and check the CDN build before extracting:

```sh
curl -s http://us.patch.battle.net:1119/wowf/versions | grep '^us|'
```

## Run it

Needs Docker, about 8 GB of RAM to build (4 GB to run) and about 20 GB of disk.

```sh
cp .env.example .env               # set the passwords
./scripts/gen-certs.sh             # your own CA + server certificate (never share certs/ca/*.key)
docker compose build               # compiles TrinityCore, takes a while
docker compose run --rm extractor  # game data from Blizzard's CDN into ./data
docker compose up -d
docker compose logs -f worldserver # the first start imports the database
```

Create an account from the worldserver console:

```sh
docker compose attach worldserver   # leave with Ctrl+P, Ctrl+Q
bnetaccount create mail@example.com Password
```

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

## Credits

- [advocaite/TrinityCore](https://github.com/advocaite/TrinityCore) `forever` branch, GPL-2.0: the server core
  (not an official TrinityCore branch).
- [jibay442/forever_docker](https://github.com/jibay442/forever_docker), GPL-2.0: the Docker build, entrypoint,
  extractor script, certificate script and the contact-list patch started there.
- [TrinityCore](https://github.com/TrinityCore/TrinityCore), GPL-2.0.

No Blizzard files are in this repository. The server data is extracted from Blizzard's own client files.

## License

GPL-2.0, see [LICENSE](LICENSE).
