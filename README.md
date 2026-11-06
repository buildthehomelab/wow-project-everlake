# Project Everlake

A private World of Warcraft server built on the **WoW Forever** client (1.60.x, the modern 64-bit client that runs
natively on Apple Silicon), with a long-term goal of carrying the Forever 1-60 game on into later expansions.

Status: **spike**. Nothing here is playable yet. The first job is to prove four things:

1. **Server runs**: the TrinityCore `forever` core builds from source, a frozen client logs in and walks around.
2. **Custom files load**: the client draws a file it doesn't ship (one Outland terrain tile and its buildings),
   served from our own patch server.
3. **Bots scale**: PlayerbotV2 at 500, 1,000 and 2,500 bots, measuring server CPU and update time.
4. **Characters move**: one character converted from an AzerothCore 3.3.5 server.

## What's here

| Path | What it is |
|---|---|
| `Dockerfile` | Builds worldserver, bnetserver and the extractors from a **pinned** commit of the core |
| `docker-compose.yml` | MySQL, worldserver, bnetserver and the extractor |
| `docker/extract.sh` | Extracts server data straight from Blizzard's CDN (no installed client needed) or from a client folder |
| `docker/entrypoint.sh` | Writes the server configs from the environment on every start |
| `docker/patches/` | Fixes on top of the core that aren't merged upstream yet |
| `scripts/gen-certs.sh` | Your own root CA (limited to `*.actual.battle.net`) and the login server certificate |

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

Connecting a client needs three things on the player's computer: a hosts entry for the login server, the CA
certificate trusted, and the server's key given to the client. That part isn't written yet.

## Credits

- [advocaite/TrinityCore](https://github.com/advocaite/TrinityCore) `forever` branch, GPL-2.0: the server core
  (not an official TrinityCore branch).
- [jibay442/forever_docker](https://github.com/jibay442/forever_docker), GPL-2.0: the Docker build, entrypoint,
  extractor script, certificate script and the contact-list patch started there.
- [TrinityCore](https://github.com/TrinityCore/TrinityCore), GPL-2.0.

No Blizzard files are in this repository. The server data is extracted from Blizzard's own client files.

## License

GPL-2.0, see [LICENSE](LICENSE).
