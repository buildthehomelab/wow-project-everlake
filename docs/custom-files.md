# Custom files on the Forever client (gate 2)

Goal: the client draws a file it doesn't ship, starting with one Outland terrain tile and its buildings.
Status: research, nothing built. Back on 2026-11-06 as the deciding test for running every ruleset on one client.

## What the Forever client has and lacks

Forever 1.60.1.70790 against the community listfile:

| | In Forever |
|---|---|
| Outland terrain tiles (`expansion01`) | 0 of 826 |
| Northrend terrain tiles | 0 of 1,131 |
| Outland props and textures (`world/expansion01`) | 3,496 of 4,934 |
| Outland buildings (`world/wmo/outland`) | 97 of 743 |

So a tile needs its ADT files, most of its WMOs, the map's WDT and a `Map` row (the server can hotfix DB2 rows).

## How files reach a modern client

The build config names `root` (FileDataID to content key), `encoding` (content key to encoded key), `vfs-root`
plus 583 `vfs-N` TVFS manifests, `install`, `download`, `size` and `patch-index`. The local install keeps
`data.NNN` archives with `.idx` journals.

The Mac binary contains a full streaming system: it downloads files it doesn't have from the CDN on demand ("make
loose file resident", "falling back to full file download", "CDN Hosts", "Failed to load armadillo key.
Streaming disabled.").

## Routes

**A. Hook the client's file loader (Arctium's way).** The MIT-licensed Arctium launcher (Windows) patches the
function that opens a file by FileDataID: a table of `fileId;path` pairs is checked first, and a matching file is
read from disk. It also flips the client's own "load by file ID / by path" checks. On the Mac we already inject a
dylib (the key patch), so the same idea would work from there, but Arctium's byte patterns are x86 Windows: the
matching arm64 code has to be found in the Mac binary by hand, and found again when a client update moves it.

**B. Our own patch server.** Serve a build that is Blizzard's plus our files: new archives, and `root`,
`encoding` and the TVFS manifests rewritten to include them. The client either streams them from us (pointing the
CDN hosts at our server) or we write them into the local install. Works the same for Mac and Windows players and
distributes itself. Unknowns: TVFS is only partly documented (path table and VFS table marked TODO on
wowdev.wiki; CascLib's source has the rest), and nobody has shown a client accepting a non-Blizzard build since
TVFS arrived (CASCHost's author: it doesn't work on 10.x/11.x clients because it has no TVFS support).

**C. Quick check with Arctium's current app on Windows.** Its 2026 app has mod folders and file mappings. If it
supports the Forever build, one mapping proves the client can draw an added tile within hours. It's a
third-party closed binary run on a player's PC, and Windows only.

## What each ruleset needs

- **Classic → WotLK:** Azeroth is Forever's own world, as the client ships it. Only Outland and Northrend are
  missing, and the client has no maps with those ids, so this ruleset only **adds** files and never replaces one.
  In TBC and WotLK the Blood Elf and Draenei starting zones (Eversong Woods, Ghostlands, Silvermoon, Isle of
  Quel'Danas, Azuremyst Isle, Bloodmyst Isle, the Exodar) sit on the Outland map (530), so they come with the same
  added map.
- **Retail:** the post-Cataclysm Azeroth replaces the same continents, so it needs its own map ids (or terrain
  swaps) to sit beside Forever's. This is the hard part, and it comes last.

## Findings, 2026-11-06

From the Forever 1.60.1.70790 build on Blizzard's CDN, read with the TACT tool in
`mod-retail-creatures/tools/tact.py`:

- **How the client finds a file:**
  1. The build config names `vfs-root`.
  2. `vfs-root` is a TVFS manifest of 37 KB with 9-byte encoded keys.
  3. Its `.root` entry points at the WoW root file (FileDataID → content key).
  4. The `encoding` file maps content key → encoded key.
  5. The archive indexes map encoded key → archive and offset.
- `vfs-1` is the same manifest as `vfs-root`. `vfs-root` also lists the other 582 sub-manifests by encoded key.
  None of them refers to the root file, so **they never need to change.**
- **Adding or replacing files therefore means rewriting four files plus one new archive:**
  - the root (new FileDataIDs)
  - `vfs-root` and `vfs-1` (their `.root` entry points at the new root)
  - `encoding` (entries for the new root, the new manifests and our files)
  - the build config (the new keys)
  - one new archive and index holding our files

  Blizzard's archives and the sub-manifests stay untouched.
- **Integrity:** every key is an MD5 of the content, so files we write get valid keys. No signature on the build
  config or manifests turned up. The client checks that its own version matches `.build.info`, so our build keeps
  Blizzard's build name and version.
- **Client strings (Mac binary):**
  - It streams missing files from the CDN ("make loose file resident").
  - It has a "loose file only" mode and repairs missing loose files.
  - It disables streaming when an Armadillo key can't be loaded. Whether the Forever product uses Armadillo is
    unknown.
- This is the TVFS layer CASCHost never supported, which is why it fails on modern clients. It's documented well
  enough to write.

## Experiment 1: replace one file the player can see

- **The file:** a small existing texture that's easy to spot, such as a loading screen, swapped for a marked
  image.
- **The tool,** new `tools/tact-patch.py`: reads Blizzard's build and writes our root, `vfs-root`, `vfs-1`,
  `encoding`, build config and one archive with its index, all keyed by MD5.
- **Delivery, first try:** a small HTTP server acts as the CDN. It serves our files and passes everything else
  through to Blizzard's CDN. The Mac mini's game copy (never the Battle.net install) gets our build key in
  `.build.info` and our server as its CDN host, so the client streams our files.
- **Delivery, if streaming refuses:** write our archive straight into the game copy's local storage
  (`data.NNN` + `.idx`).
- **Passes when** the mini shows our texture, it's still there after a client restart, and the Battle.net install is
  untouched.

### Status, 2026-11-06: passed on the mini (see below)

- **`tools/tact/patch.py`** writes the patched build.
  - `--selftest` rebuilds Blizzard's encoding file (141 MB), loose-file index, root and TVFS manifest with
    nothing added, and **all four come out byte for byte identical** to Blizzard's. That's the proof the writers
    understand the formats.
  - Patching replaces FileDataID 134414 (`inv_misc_rune_01.blp`, the Hearthstone icon) with the Ragnaros icon,
    plus a 14-byte marker so its bytes are unique. The check then walks the client's chain through the new build
    and finds our file, with every other file still Blizzard's. Adding a brand-new FileDataID (experiment 2's
    need) passes the same check.
  - Without the marker, the encoding file reuses Blizzard's own copy of identical bytes. That's correct, but it
    wouldn't show that our files load.
- **`tools/tact/cdn.py`** serves the patched build and passes everything else through to Blizzard, with byte
  ranges. It logs each request as OURS or BLIZZARD, which shows exactly what the client asks for.
- **`everlake-client.sh gate2`** on the mini builds a test game folder from APFS clones of the real one (instant,
  no extra disk space, the Battle.net install is never changed). Its `.build.info` points at our build and at our
  CDN through the forwarder.
- **The file table oddity:** its TVFS entry lists a size 1,024 bytes larger than the stored file, while every
  sub-manifest's entry lists the exact size. The tool keeps that same offset.

**Experiment 1 PASSED (2026-11-06, 23:46): the Hearthstone shows the Ragnaros icon.**
- **The run, from the CDN log:** the client loaded our configs, loose-file index, vfs-root, encoding, root and the
  rewritten `vfs-575`. Then it **streamed our icon from our server** (`382676ff…`, 3,286 bytes) and drew it.
- **What this settles:**
  - The client accepts a build that isn't Blizzard's.
  - It streams files it doesn't have from whatever CDN `.build.info` names.
  - Armadillo doesn't get in the way.
  - Its one request Blizzard refuses (an all-zero config key) is harmless.
- **The recipe:** list a file in the root and in the TVFS sub-manifest of its root block, plus the encoding and
  loose-file index entries, and serve it.
- **The test folder:** an APFS clone. The Battle.net install was never touched.

**First run on the mini (2026-11-06): the client accepted our build, and the icon was green.**
- **Accepted:** through our CDN, the client downloaded our build and CDN configs, the loose-file index, vfs-root,
  the whole encoding file and the root. Neither the version check nor the keys objected.
- **Green, not found:** the Hearthstone showed green (texture missing). The client never asked for the icon file.
  Its `Tact.log` said `Unable to lookup file with path '000173F600000000:00020D0E8748070A…'. Error(6): not found`.
- **Why:** the client finds a game file by a **TVFS path**, not through the encoding file. The path is the root
  block's locale and content flags, then the FileDataID and content key in hex. vfs-root has one sub-manifest per
  locale+flags (here `vfs-575`, 91 MB, 1,092,450 paths), and that path has to be listed there.
- **The fix:** `tools/tact/tvfs.py` reads and writes TVFS manifests. vfs-root and three sub-manifests come back
  byte for byte. The path tree branches one hex character per level, so a new path splits the leaf it shares a
  character with into a one-character folder, as Blizzard's own tree does. Container entries end in a
  patch-record count byte. The patched `vfs-575` keeps all 1,092,450 of Blizzard's paths unchanged and adds ours.
  `patch.py` now verifies the whole lookup the client does: root → vfs-root → sub-manifest → span → file.

**To run it:**

On the server Mac:

```sh
python3 tools/tact/patch.py --cache ~/retail-cache-wowf --out <dir> 134414=<marked icon>.blp
python3 tools/tact/cdn.py --dir <dir> --port 80 --log <dir>/cdn.log
```

On the mini:

```sh
./client/macos/everlake-client.sh gate2                       # reads the build keys from the server
./client/macos/everlake-client.sh play <account email> gate2
```

Then look at the Hearthstone in your bags.

**What the run tells us:**
- **Our icon shows:** the client accepts a non-Blizzard build and streams our files. Experiment 1 passes.
- **The cdn.py log shows no requests:** the client reads only local storage. Next is delivery B: write our files
  into the clone's `Data`.
- **The client refuses the build:** the game log says why (version check, invalid build key, Armadillo).

## Experiment 2 PASSED (2026-11-07, 01:10): Sunstrider Isle in the Forever client

Ora teleported to map 530 and saw **Sunstrider Isle**: TBC Anniversary terrain drawn by the Forever client, on a map
the client doesn't have, sent by our own server and CDN.

**What it took:**
- **Terrain:** 43 files from TBC Anniversary 2.5.6 (`collect.py`): the WDT and its 6 companions, plus 4 files each
  for the 3×3 tiles around Sunstrider Isle. All 178 textures, models and buildings they use are already in Forever.
- **The map, by hotfix** (`sql/everlake/2026_11_07_00_hotfixes_gate2_map530.sql`):
  - A Map row modelled on Forever's Kalimdor, with **ExpansionID 0**: the core refuses a map above the account's
    expansion, and Forever accounts are 0.
  - A MapDifficulty row, and the 9 AreaTable rows of those tiles.
  - The client accepted every row as valid.
- **The WDT trimmed to the shipped tiles** (`collect.py --only-tiles`). This was the actual fix. Outland's WDT lists
  800 tiles, and with 791 missing the client throws **WOW51900322 "a streaming error has occurred"** the moment the
  map loads, before any request reaches the CDN. Map 530 pointed at Kalimdor's WDT loaded fine, which narrowed it
  down.
- **Local storage** (`client/macos/casc_local.py`, `gate2-install`): the trimmed WDT has new bytes, so it was
  written into the game's own storage, in a new `data.048` (38 files, 8.4 MB, 16 index files updated, all read back
  good), and the client read it from there.

**Things learned on the way:**
- **The client finds a file by TVFS path** (the sub-manifest of its root block), not through encoding alone.
- **The download manifest is read by Battle.net's installer, not the game.**
- **Files byte-identical to anything Blizzard hosts on the shared `tpr/wow` CDN are fetched from Blizzard's
  archives.** Our TBC Anniversary tiles were, at startup.
- **The local storage format** was checked read-only against a real install first: about a million index entries
  with every Jenkins checksum right. The writer copies the 30-byte header the client writes for its own files.

**Still to do:**
- Server-side terrain for map 530 (map, vmap, mmap files). The server doesn't know where the ground is yet: Ora
  arrived under the isle at z 26 and was fine at z 200.
- Creatures.
- More tiles, then all of Outland and Northrend.

**Next:**
- **Experiment 2:** add a new FileDataID, one Outland-map tile plus its WDT, with a `Map` row by hotfix. An
  Eversong Woods tile is a good first pick: it's on the same map as Outland and easy to recognise.
- **Experiment 3: three Azeroths in one client.** The goal (user, 2026-11-06): each ruleset sees its own world.
  - Forever uses Forever's map, as shipped.
  - Classic → WotLK uses the **original** vanilla terrain, from Blizzard's Classic Era product on the same CDN.
  - Retail uses retail's post-Cataclysm terrain.

  Forever's version keeps the real map ids. The other two are added under new map ids, with their own WDTs and,
  where a file's id clashes, new FileDataIDs for their tiles. Each realm then shows its version through a
  **default terrain swap** (TrinityCore's `terrain_swap_defaults`: map 0 drawn with another map's terrain), so the
  world database keeps using map 0 and 1. Server collision and pathing come from the swapped map. If that doesn't
  hold, the fallback is Forever's map for the Classic ruleset (no clash at all), and retail last.

## Server terrain for map 530 (2026-11-07)

The server now has ground, buildings and a navmesh for the 9 Sunstrider Isle tiles, made from **exactly the files
the client draws**: the 36 TBC Anniversary 2.5.6.70577 tile files and the WDT trimmed to those 9 tiles (from
`~/Code/Wow/evermore2-spike/gate2/exp2d-files`). Every building and doodad they place is read from Forever's own
build.

**How:** TrinityCore's extractors only see maps in the build's `Map.db2`, and Forever's has no 530 (the client gets
it by hotfix). Three ways were weighed:
- Point the extractors at our patched build on our CDN: CascLib would need our CDN host, and `Map.db2` still has no
  530, so a patch is needed anyway.
- Run them on the TBC Anniversary product: its `Map.db2` has another layout than the one compiled in, the full WDT
  lists 800 tiles, and the models would be Anniversary's copies, not Forever's.
- **Chosen:** a small extractor patch, `docker/patches/0010-extractors-loose-files-extra-maps.patch`:
  - `EXTRACTOR_LOOSE_FILES=<dir>`: a file named `<dir>/<FileDataID>` is read instead of the storage's copy. That is
    how the trimmed WDT and the ADTs come in.
  - `EXTRACTOR_EXTRA_MAPS=530:828395:Expansion01` adds the map (id, WDT FileDataID, directory) to mapextractor and
    vmap4extractor; `EXTRACTOR_ONLY_MAPS=530` extracts only that map.
  - Everything else (models, liquid tables) still comes from Forever's build on Blizzard's CDN.

`docker/extractors.Dockerfile` builds only the tools at the server's pinned commit with `docker/patches` (about 4
minutes), so the worldserver image doesn't have to be rebuilt; the next full image build picks the patch up too.
`scripts/extract-extra-map.sh` runs them and copies the result into `data/`: it **adds** `maps/0530_*`,
`maps/0530.tilelist`, `vmaps/0530/`, `mmaps/0530*` and vmap models that aren't there yet, never replaces an existing
model, and moves any existing `0530` file to `data/.backup-<time>/` first (there was none).

```sh
cd ~/Code/Wow/wow-project-everlake      # the stack's folder (or this branch's checkout, with DATA_DIR set)
scripts/extract-extra-map.sh ~/Code/Wow/evermore2-spike/gate2/exp2d-files 530:828395:Expansion01
#   INSTALL=0  only extract (result in data/.extra-map-out)   REBUILD=1  rebuild the extractor image
docker compose restart worldserver
```

A run takes about 4.5 minutes and gives 9 `.map` (+ 9 `.road`), 15 vmap tiles, 16 mmap tiles and 131 new vmap
models. vmap and mmap tiles reach a little past the 9 terrain tiles where buildings hang over the edge. The 38 loose
reads are the WDT and the 36 tile files (the ADT roots twice). All 20 buildings on the tiles became vmap models; 100
of the 137 doodads did (the rest have no collision mesh). The 16 "Can't open FILE0002EE..." lines come from the
GameObject model pass, same as the normal extraction, and none of those files is used on these tiles.

**Checks** (worldserver restarted at 01:34 and 01:43 EST, both under the lock file):

1. **Terrain matches retail.** `tools/mapcheck/map_height.py` reads the ground from the `.map` files the way the
   server's `GridMap` does (checked on map 0 first: Northshire spawns sit 0.1 to 0.2 above it). Against all 411
   creature spawns AzerothCore has on these tiles (retail positions): 264 are within 0.5 yd of the ground (mean
   +0.11), 22 within 1.5, 125 are higher (on buildings, bridges, the Sunspire floors: vmap ground), **none below**.
   ```sh
   tools/mapcheck/map_height.py ~/Code/Wow/wow-project-everlake/data 530 10349.6 -6357.29
   #   10349.60   -6357.29  0530_12_43.map  area  3431  z   33.404     (3431 = Sunstrider Isle)
   ```
2. **The worldserver loads the tiles.** A bot logged in on the isle; with `.server set loglevel l mmaps 1` and
   `.server set loglevel a Server 1` the log shows `MMAP loaded name:Outland, id:530, x:14, y:43` (and 14,44) as it
   arrived. There is **no** "Could not load MMAP … id:530" for any of the 9 tiles (11-13 × 42-44). Two such lines
   remain, x:11 y:45 and x:14 y:42: grids next to the isle that the client has no terrain for either (outside the
   trimmed WDT), plus x:39 y:54 at PlayerbotV2 start-up (a portal anchor elsewhere in Outland).
3. **The server's height is ours, buildings included.** `.playerbot terrainprofile` (console; needs a bot on the
   map) runs the server's own `Map::GetHeight` (terrain + vmaps): at the four test spawns it gives 33.38, 34.03,
   26.39, 31.78, the offline reader 33.380, 34.032, 26.387, 31.782. The bot's own moves log
   `[ground] Terrainbot move_to z hint=33.5 ground=30.9` for (10329.7, -6355.7), offline 30.941. Inside the Sunspire
   the bot stood at z 38.5 where the terrain is 37.2: on the building's floor, where retail NPCs stand (38.6).
4. **Pathing.** The bot made 23 moves on the isle, all `Ok`, none in `[path_fail]`, from the courtyard into the
   Sunspire and up to z 53 (`.playerbot diag Terrainbot`). Offline, the fork's `mmap_probe` (Detour on our mmaps,
   in the extractor image) finds a complete path from the arrival point to the west shore across two tiles, 7
   points, 318 yd, and one into the Sunspire:
   ```sh
   docker run --rm --entrypoint /opt/trinitycore/bin/mmap_probe -v "$PWD/data/mmaps:/mmaps:ro" \
       everlake-extractors:latest /mmaps 530 10349.6 -6357.29 33.4 10080 -6200 14.7     # STATUS: OK
   ```
   `.playerbot goto` doesn't work there yet: it routes through PlayerbotV2's travel graph, which has no nodes on 530,
   so the bot keeps wandering.
5. **Creatures stand on the ground.** The first test spawns, Sunstrider Isle's own Mana Wyrm and Magistrix Erona,
   never appeared: `creature_template_model has no valid model for the entry`. TBC creatures' display ids are not
   in Forever's tables, so the server refuses to create them. Isle creatures need that data first. Instead, four
   creatures Forever has went in at retail Sunstrider spawn spots and heights (world DB, guids 9530001-9530004,
   random movement 5 yd): two Cats (6368, which retail also has in the Sunspire courtyard) and two Kobold Vermin (6)
   on the Mana Wyrm spots. After the restart `.debug objectcount 530` shows `Creatures: 4` (entry 6 ×2, 6368 ×2).
   The server's ground under them (`terrainprofile`) is 35.50, 35.47, 33.38, 26.39, and they stand at 35.61,
   35.57, 33.55, 26.50: 0.10 to 0.17 above, the same small offset retail spawns have everywhere. They are left in
   for the morning check. Remove them with
   `DELETE FROM world.creature WHERE guid BETWEEN 9530001 AND 9530004;` and a restart.

The bot test, as run from the console (`scripts/console.py "<command>"`):
```sh
playerbot create Terrainbot human warrior 0          # makes and logs in a bot (id 298, bot account 30)
playerbot logout Terrainbot
#   characters DB: UPDATE characters SET map=530, zone=3430, position_x=10349.6, position_y=-6357.29,
#                  position_z=33.5 WHERE guid=298 AND online=0;
playerbot login Terrainbot
playerbot inspect Terrainbot                          # Position : (10333.6, -6399.1, 38.5) map=530
playerbot diag Terrainbot                             # the moves it made
playerbot terrainprofile 10316.1 -6385.99 33.6 10352 -6359.93 34.1 Terrainbot
```

**Morning check (in game, as Ora):** `.go xyz 10349.6 -6357.29 34 530` should land on the ground beside the
Sunspire. Use z 34, not 30: `.go xyz` keeps the z it is given, and the ground there is at 33.4, so z 30 puts Ora 3.4
yd under the isle. `.gps` should then say area 3431 (Sunstrider Isle), and the two cats and two kobolds a few yards
west and south of the Sunspire should stand on the grass, not float or sink.

**Not done:** creatures and quests for the isle (TBC creatures have no model in Forever's tables, see check 5),
PlayerbotV2 travel nodes for 530, more tiles.

## Sources

- wowdev.wiki: [TACT](https://wowdev.wiki/TACT), [CASC](https://wowdev.wiki/CASC), [TVFS](https://wowdev.wiki/TVFS)
- [brian8544/Arctium-Launcher](https://github.com/brian8544/Arctium-Launcher) (MIT): `src/ModLoader.cs`,
  `src/Patterns/Windows.cs`
- [Beginner's Guide to CASCHost](https://www.wowmodding.net/topic/1498-beginners-guide-to-caschost/), and
  Marlamin's 2024 note on TVFS archived at
  [elijahketchersid.com thread 86139](https://elijahketchersid.com/forums/thread-86139.html)
