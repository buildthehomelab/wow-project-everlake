# China Undead (test)

Goal: an Undead character can pick the China look (no exposed bones) in the character creator and at the barber,
while every other Undead keeps the normal look. Status: test built 2026-11-08, not run.

## What Blizzard ships

- Blizzard's build holds two copies of some files under **one** FileDataID: the normal one, and a censored one in a
  root block flagged LowViolence (0x80). The client reads the censored copies only when its `overrideArchive`
  setting is on (the China client). Forever 1.60.1.70790 has 7,737 of them, 671 for the Undead.
- The China Undead model (`scourgemale_hd.m2` 959310, `scourgefemale_hd.m2` 997378) uses **the same skeleton file**
  as the normal one (byte for byte) and has no bones of its own (a SKID chunk), like retail's add-on models. Its
  body mesh is bigger (male 736 → 1,452 triangles, female 752 → 2,654: the ribs and spine are covered) and every jaw
  choice is the same covered jaw. The exposed-bone pieces (geosets 1204, 1702-1705, 2901, 3001, 3201-3202,
  5101-5103) are gone.
- Undead already have the option **Skin Type** (male 567, female 568): **Bony** (requirement 55) and **Fresh**
  (requirement 4975, `OverrideArchive` 1, so only shown with the China setting on). Fresh hides the bone pieces
  (geosets 19, 29 and 30 set to 2) and swaps cape geosets.

## The test

Two new Skin Type choices per sex, **China** and **China (B)**, offered like Bony (requirement 55):

- the Fresh choice's parts (bone pieces hidden, cape geosets), plus
- the China body as a skinned model (ChrCustomizationSkinnedModel, the way retail adds Mechagnome arms or Dracthyr
  horns), geoset type 0 id 0 (the body mesh), on the character's own skeleton.
- The two differ only in the skinned model's Flags: 0 and 1 (retail uses 1 on 20 of 1,027 rows; meaning unknown).

Pieces:

| What | Where |
|---|---|
| China models + their 7 skin files each as new FileDataIDs 95450001-95450016 (SFID repointed) | `tools/looks/china_undead.py` |
| Hotfix rows: 4 choices, 52 elements, 4 skinned models (in `hotfix_blob`, the core has no table for them), push 9570000 | `tools/looks/china_undead_sql.py` → `sql/everlake/2026_11_08_00_hotfixes_china_undead.sql` |
| Patched build: Blizzard's plus the 16 China files, served by the `cdn` service (port 8087) | `scripts/cdn-build.sh`, `docker-compose.yml` |
| Mac mini: the CDN's address (default: the server, 8087), the test copy, the China setting | `everlake-client.sh cdn`, `china-undead`, `china-mode on/off` |

The skinned-model record bytes follow layout 4C32AA8A: CollectionsFileDataID int32, GeosetType uint8, GeosetID,
Modifier, Flags int32, no ID (the table's IDs are non-inline).

## Running it

Server, in the checkout that holds `.env`:

1. The hotfix rows into the realm database `hotfixes` (`sql/everlake/2026_11_08_00_hotfixes_china_undead.sql`), then
   restart the worldserver.
2. The patched build: `docker compose run --rm cdn-build` (`scripts/cdn-build.sh`: the China files, then
   `patch.py` into `CDN_DIR`; the first run downloads Blizzard's indexes, about 3-4 minutes). Then restart the app
   so the `cdn` service starts; it serves the build on `CDN_PORT` (8087) and passes everything else to Blizzard.
   Later builds need no restart.

Mac mini (the CDN defaults to the game server's port 8087):

```sh
./client/macos/everlake-client.sh china-undead
./client/macos/everlake-client.sh play <account email> gate2
```

Then: Undead, Skin Type, China / China (B); screenshots at creation and in the world, with and without gear. For
comparison, Blizzard's own China look: `china-mode on gate2`, play, `china-mode off gate2`.

## What each result means

- **China shows a whole body**: per-character China look works. Left to do: the China skin textures per skin colour
  (they differ from the normal ones), bare hands/feet/legs under gear, and the choice's name.
- **Holes where the bones were** (Fresh's parts work, our body doesn't draw): the client doesn't draw a skinned
  model's mesh 0, or doesn't take a model with a SKID chunk. Next: move the body to another geoset id, or give the
  model its bones inline.
- **The choices don't show**: the hotfix rows didn't arrive or were refused (worldserver log, `check gate2`).
- **Client error or crash**: the skinned-model blob layout is wrong; read the crash log.

Undo: the DELETEs at the top of the SQL file, restart the worldserver; `gate2-uninstall` on the mini.
