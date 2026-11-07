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

## Sources

- wowdev.wiki: [TACT](https://wowdev.wiki/TACT), [CASC](https://wowdev.wiki/CASC), [TVFS](https://wowdev.wiki/TVFS)
- [brian8544/Arctium-Launcher](https://github.com/brian8544/Arctium-Launcher) (MIT): `src/ModLoader.cs`,
  `src/Patterns/Windows.cs`
- [Beginner's Guide to CASCHost](https://www.wowmodding.net/topic/1498-beginners-guide-to-caschost/), and
  Marlamin's 2024 note on TVFS archived at
  [elijahketchersid.com thread 86139](https://elijahketchersid.com/forums/thread-86139.html)
