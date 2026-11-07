# Keeping up with the Forever client

Blizzard is still developing WoW Forever: 1.60.1.70790 (what we run) was followed by 70840 and 70862 within three
days. Battle.net updates the game on its own, and the server only accepts the builds it has a `build_info` row for.
Our hotfix kits also depend on the client's exact table layouts (Test 1: every spell needs its Spell text row, and
rows changed inside a push the client already has never reach it). So every new build has to be checked before
anyone plays on it.

`tools/clientwatch` does as much of that check as public data allows, and a scheduled job runs it.

## Levels

| Level | What | Where | Person? |
|---|---|---|---|
| L1 | **Watcher**: which Forever builds exist, which are newer than ours | `clientwatch.py builds` | no |
| L2 | **Static checks** of each newer build against ours: table layouts, the rows we override, content added or removed, what the core fork did for the build | `clientwatch.py check` / `run` | no |
| L3 | **Live check**: the new client logs in to our server and runs a smoke test | Mac mini, `everlake-client.sh smoke` (planned) | yes, at the mini |

L1 and L2 run on a schedule and report through one GitHub issue. L3 needs the real client.

## L1: the watcher

Two sources, both public:

- **Blizzard's version server**, `us.patch.battle.net:1119/wowf/versions` (and `bgdl`, the background
  pre-download, when there is one). It is what the launcher installs, so it has a new build first.
- **wago.tools**, `https://wago.tools/api/builds`. It lists every build it has processed, with the time it first
  saw it. Its table CSVs exist only once a build is in this list.

"Ours" is read from the checkout: the `client 1.60.1.N` note on the `TC_COMMIT` line in the `Dockerfile`, and
`TC_COMMIT` from `.env`, `.env.example` or the Dockerfile. `CLIENT_BUILD` from `.env` is shown when it is set.
Override them with `--baseline` and `--tc-commit`.

## L2: the static checks

For each newer build (newest first, at most `--limit 3`), compared with ours:

1. **Layouts**, from [WoWDBDefs](https://github.com/wowdev/WoWDBDefs). Each table's `.dbd` file groups builds
   by layout hash, so two builds in the same block have the same layout. Every table is compared, in three tiers:
   - **ours**: the tables our hotfix SQL writes (`sql/everlake/*hotfixes*.sql`), the tables our kits write
     (`tools/era/kits/*.json`, including every spell table for a kit with spells and the Trait tables for a
     tree clone), and a fixed list: Spell, SpellName, ChrClasses, ChrRaces, ChrSpecialization,
     ChrClassesXPowerTypes, PowerType, CharBaseInfo, SkillLine, SkillLineAbility, SkillRaceClassInfo, Map,
     MapDifficulty, AreaTable, and every Trait* table. A layout change here **fails** the build.
   - **server**: every `.db2` the pinned core loads (`DB2Stores.cpp` at `TC_COMMIT`, about 370 tables). A layout
     change **fails** too: the core checks layout hashes when it loads its data and builds hotfix packets in its
     compiled field order.
   - **other**: everything else, listed as information.
2. **Rows we override.** Every row our hotfix SQL inserts (each table's `ID`, and `hotfix_blob` rows by table
   hash) is looked up in both builds on wago.tools:
   - Blizzard **added** a row with an ID we use for our own (custom IDs, map 530, a spell a kit sends): **fail**.
     Our hotfix silently replaces Blizzard's row, and a kit would now skip that spell.
   - Blizzard **changed** or **removed** a row we override: **warn**, with the changed columns. Our row still
     wins, but we may be overwriting a fix.
   - The rows a kit copies from the target build itself (a `clone_trees` source tree and its nodes): **warn**
     when they differ; the kit should be run again.
3. **Content added or removed**: the ID sets of SpellName, ChrClasses, ChrRaces, SkillLine, Map and TraitTree,
   with counts and the first IDs and names. A class, race or map change is a **warn**.
4. **The core fork**, from GitHub's API: how far `forever` and `forever-bots` are ahead of our pin, whether a
   commit after the pin adds `build_info` (or `build_auth_key`) for the build, and which commits touch the
   opcode and packet files.

Kits record the build they were made for (`target_build`); each kit made for an older build is listed as a **todo**:
re-run it with the new target and the new client's DB2 headers before the server moves.

A build is **PASS** when nothing fails and all the data was there, **PENDING** when WoWDBDefs or wago.tools has
not processed it yet (it is checked again on the next run), and **FAIL** otherwise. The run exits 1 on a FAIL.

### Running it

```bash
python3 tools/clientwatch/clientwatch.py builds
```

```bash
python3 tools/clientwatch/clientwatch.py run --out reports/clientwatch
```

```bash
python3 tools/clientwatch/clientwatch.py check 1.60.1.70862 --source ../everlake-wt/classes --out reports/clientwatch
```

`--source` adds another checkout's hotfix SQL and kits (a branch that isn't merged yet). `--cache` (default
`~/.cache/everlake-clientwatch`) holds the downloads, laid out like `tools/era/hotfix_kit.py`'s cache, so both
tools can share one folder. A first run downloads about 100 MB of CSVs from wago.tools; later runs only fetch
new builds. Set `GITHUB_TOKEN` to avoid GitHub's anonymous limit of 60 requests an hour.

The parsers have offline tests:

```bash
python3 -m unittest discover -s tools/clientwatch
```

## Where it runs: a GitHub Actions schedule in this repository

`.github/workflows/client-watch.yml` runs every 3 hours and by hand (optionally for named builds). It keeps **one**
open issue labelled `client-watch`, titled with the newest build and its status. The body is the latest report.
The workflow comments when the status changes, and it closes the issue once no build is newer than ours (after
the pin moves). The same pattern is used in wow-ci's `upstream-watch`.

Why here and not elsewhere:

- **Not wow-ci.** wow-ci serves the AzerothCore modules. This check needs this repository's own SQL, kits and pin.
  Keeping it here keeps the public repo standalone.
- **Not a launchd job on a Mac.** The server Mac sleeps and restarts, and a local job fails silently. It would
  report into a log nobody reads. GitHub's hosted runners are free for a public repo. Everything the check reads
  is public, so it needs no secrets beyond the workflow's own token. The issue is the notification.
- **The cost:** GitHub only runs schedules from the default branch, so the workflow starts once it is merged to
  `main`, and it checks `main`'s SQL and kits. Run it by hand (`workflow_dispatch`) from a branch to check
  unmerged work.

## What still needs a person

The report repeats these under "Needs a person":

- **Opcodes.** A build can move client messages. 70790 added two at 0x71/0x72
  (`docker/patches/0001-classic-70790-client-messages.patch`). No public data shows this. Only a login with
  the new client and the server's packet log do.
- **Accepting the build.** The server needs a `build_info` row for it. Either the fork adds one (it did for
  70862 in `7bb0cfcc`, "Classic 1.60.1.70862: auth support"), or we set `CLIENT_BUILD` in `.env`, and
  `docker/entrypoint.sh` writes the row. There are no auth keys for Forever builds; we run with
  `Network.SkipBuildAuthKeyCheck = 1`.
- **Gate 2's patched build.** `tools/tact/patch.py` rewrites one build's build config, root, encoding and TVFS.
  A new client build needs it made again from that build (about 300 MB of indexes from Blizzard's CDN), and
  `collect.py` re-run, since the new build may now ship files we add. Not automated: it is heavy, and it only
  matters once we move.
- **The client's hotfix cache.** Test 1 showed that rows changed inside a push the client already has don't
  reach it. Whether an update clears `DBCache.bin` is not known. After moving, check in game that the kits'
  rows still arrive.
- **Server data.** dbc/maps/vmaps/mmaps come from the build that was live when `extract` ran. With unchanged
  layouts the old data keeps working, so re-extract only for a layout change or new map data.

## L3: the live check on the Mac mini (plan, not built)

Battle.net updates the mini's game on its own, so the mini is usually the first place a new build runs. The
check has to be a subcommand of `client/macos/everlake-client.sh`: the user can't paste commands onto the mini
([client-connection.md](client-connection.md)). Pull with `git -C ~/everlake pull`, then run the one subcommand.

`everlake-client.sh smoke [game folder]`, planned:

1. **Build.** Read the installed build (`game_build`, CFBundleVersion) and the build the server accepts (new
   endpoint on the report-drop service, or `/everlake/build.json` style). If they differ, say so and stop: the
   server needs `CLIENT_BUILD` or a pin move first.
2. **Re-sign.** Remake the ad-hoc copy when the app changed (Battle.net replaces the app on update; `setup`
   already says to run it again). Compare the app's CFBundleVersion with the one the copy was made from.
3. **Login.** `play` with the test account, then wait for the client to reach character select. Read
   `Logs/` for the realm list and for disconnects.
4. **In world.** A small addon in the test folder (as gate 2's prefetch addon) that, on login, writes to its
   SavedVariables:
   - the build (`GetBuildInfo()`);
   - whether test spells exist (`C_Spell.GetSpellInfo` for Death Coil 47541, a spell from each kit);
   - map 530's data;
   - the class list (`GetNumClasses`/`GetClassInfo`);
   - Lua errors.

   Then it logs out (`/logout` via `Logout()`).
5. **Report.** Send the SavedVariables, the newest client log lines and the build to the server (report-drop
   service, port 8099, as `check` does). On the server, a small script compares them with the expected kit
   results and prints PASS/FAIL beside the L2 report.
6. **Opcode sniff.** The server side of the same run: grep `Server.log` for unknown or unhandled opcodes and
   wrong packet sizes in the minutes of the smoke login.

Steps 1-2 and 5 are plain shell, like `check`. Steps 3-4 need a person at the mini for the first runs (the
first realm login of a session can fail with "server identity check failed"; Reconnect works). After that it can
run from launchd on the mini, triggered when the build changes.

## Results: 70840 and 70862 against 70790 (2026-11-07)

Run with `--source` pointing at the Test 1 branch (`claude/test1-classes`, not merged yet) and the core at
`forever-bots` `5206a727` (what the server image is built from). Both builds **PASS**:

- **Builds:** 70862 is live in every region on Blizzard's version server. 70840 is no longer offered there
  (wago.tools saw it at 02:28 UTC, 70862 at 04:43).
- **Layouts:** no table changed layout between 70790, 70840 and 70862. That covers 1,161 tables, the 67 our
  hotfixes and kits use, and the 370 the core loads. This matches the fork's own note on its 70862 commit.
  - As a control, `check 1.60.1.70790 --baseline 1.60.1.70450` **fails**: SpellDuration's layout went
    A931BD2B → 4FDF0951 (DurationPerLevel added). It also warns that 5 nodes of Warrior tree 1117, which the
    talent kit copies, changed. Against 69876, five tables changed layout.
- **Rows we override:** 958 rows in 39 tables, from 4 hotfix files and 3 kits. 66 of them replace a Blizzard row
  (SkillRaceClassInfo, SkillLineAbility and other widened rows); the rest use IDs Blizzard doesn't have. None
  was added, changed or removed by Blizzard in either build, so the kits' output would be the same.
- **Content:** both builds add 395 spells (SpellName 32,087 → 32,482) and 5 maps (The Drowned City, Blackmaw
  Hold, Alcaz Prison, The Shaper's Terrace, Krol'dok Stronghold), so Blizzard is adding Forever content. No
  class, race, skill line or talent tree was added or removed. 70840 and 70862 have the same content
  differences from 70790.
- **Core fork:** `forever` commit `7bb0cfcc` adds `build_info` 70862 (merged into `forever-bots` as
  `0be29df2`). Nothing adds 70840, which Blizzard's version server no longer offers. The only opcode change after
  our pin is `6ac7bece`, which we already apply as `docker/patches/0001-classic-70790-client-messages.patch`.
- **To move to 70862:** bump the pin to `forever-bots` `0be29df2` or later (or set `CLIENT_BUILD=70862`).
  Then:
  - re-run the three Test 1 kits with `target_build` 1.60.1.70862 (same rows expected);
  - rebuild the gate 2 patched build from 70862;
  - run the L3 login on the mini.
