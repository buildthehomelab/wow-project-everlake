# live-hotfixes

Live WoW Forever changes spells, items and other client tables by hotfix after a client build ships. Blizzard's hotfix
cache for live Forever (`DBCache.bin`) is mirrored publicly and refreshed daily; wowsims/forever (MIT) builds its data
from it:

    https://storage.googleapis.com/raidbots-static/wow/forever/enUS/DBCache.bin

No game account is needed to read it. The file header names the client build it belongs to.

| Tool | What it does |
|---|---|
| `dbcache.py` | Reads a `DBCache.bin` (XFTH version 9): build, records per table, or one table's records as JSON lines |
| `tact_keys.py` | Writes the hotfixes SQL for every TACT key live sends that the core lacks or holds with other bytes |
| `test_live_hotfixes.py` | Unit tests: `python3 -m unittest discover -s tools/live-hotfixes` |

## TACT keys after a client update

A TACT key unlocks client data Blizzard ships encrypted. The client reads that data only after a server sends the key
as a TactKey hotfix. Live sends a few real keys and marks the rest "not public" (no key bytes); only the real ones are
written. After each client build:

```sh
curl -sO https://storage.googleapis.com/raidbots-static/wow/forever/enUS/DBCache.bin
python3 -I tools/live-hotfixes/dbcache.py DBCache.bin | head -1          # build must be the client's
python3 -I tools/live-hotfixes/tact_keys.py --cache DBCache.bin \
    --core-repo ../wow-trinitycore-everlake --core-ref "$(sed -nE 's/^ARG TC_COMMIT=//p' Dockerfile)" \
    --push 9590000 --out sql/everlake/2026_11_08_08_hotfixes_live_tact_keys.sql
```

Keep the same push id and file while the list only grows: the file is re-runnable and the Dockerfile copies it into
`sql/custom/hotfixes`. A changed key needs a new push id (the client keeps the rows of a push it already has). A push
holds up to 99 rows.
