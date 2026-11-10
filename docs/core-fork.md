# Our own core

Goal: Everlake runs a core we have read, tested and can stand behind. We take upstream work as fast as it comes, from
both upstreams (advocaite's `forever` fork and TrinityCore itself), but only after checking each change does what it
says, and every fix we take or make gets a test, so the core gets steadier with each change instead of less sure.

Status (2026-11-10): Everlake builds from the fork at `343fe6fb`, which adds TrinityCore master batches A-K (fork #23, #24, #26,
#28-#35), Karrz's v0.1.33 world data (#22) and Classic scripts (#25, with build fix #27), and Karrz's v0.1.34 world data (#36),
Ring of Law arena (#37, map 3200 from the extractor's map copies) and bot module (#38) from the `karrz-releases` branch (fork `docs/karrz-releases.md`,
`docs/upstream-prs/karrz-*.md`). All 99 advocaite pull requests open on 2026-11-08 are
reviewed (fork PRs #5-#17, one log per pull request in the fork's `docs/upstream-prs/`); patches 0003 (upstream #291) and
0009 (replaced by #138) are gone from `docker/patches/`, and 0008 (name reservation) is the fork's own code now,
reserving full names (name + surname). TrinityCore `master` commits are next.

## Why

Upstream on 2026-11-08:

- `forever` branched from TrinityCore's `master` (retail) on 2026-09-25. TrinityCore has 144 commits since (102 in the
  last 30 days); `forever` has picked up only a few of them by hand (#32027, #32047). Merged whole, TrinityCore's
  `master` clashes with `forever` in 15 files: 7 are client data structures and message numbers, 8 are game code.
- 98 pull requests are open against `forever`, 57 of them opened since 2026-11-06. The owner mostly pushes straight to
  the branch; pull requests wait. Several fix crashes or exploits.
- Tried one at a time on our pinned commit, 96 apply cleanly; 2 no longer apply. Taken all together in number order, 93
  do: 3 more change the same code as each other (below).
- 57 change only code, 35 only SQL, the rest both. They add 73 SQL files, 62 of them world update files.
- Our own patches are going upstream too: `docker/patches/0003` (the contact list request) is upstream pull request
  #291, word for word plus a longer comment.

A patch folder doesn't scale to that. A fork does: each change is a commit with its author, git tracks what upstream has
merged, and tests live next to the code.

## The repository

- `buildthehomelab/wow-trinitycore-everlake`, a GitHub fork of `advocaite/TrinityCore`, GPL-2.0 like the core, with
  TrinityCore's own repository as a second upstream.
- Mirror branches, never committed to: `forever` and `forever-bots` (advocaite), and TrinityCore's `master`,
  `wotlk_classic` and `cata_classic`.
- `everlake` is what the Forever realm runs: `forever` plus the pull requests and TrinityCore commits we took, our
  patches and our tests.
- The other realms get their own branch when they are built: a retail realm on TrinityCore's `master`, a classic realm
  on the TrinityCore classic branch it uses. Our own Everlake changes (name reservation, one sub-region, random surname)
  are kept as small, separate commits with their tests, so the same commits go onto every realm's branch.
- Everlake's Dockerfile points `TC_REPO` at the fork and pins `TC_COMMIT` to an `everlake` commit. The patches in
  `docker/patches/` move into the fork as commits, each with a test where it can have one, and the folder goes.

## Taking an upstream pull request

Each one goes through the same steps, as its own pull request into `everlake`, so each gets a review and a CI run.

1. **The claim.** What the title and description say it fixes, and how a player would see it.
2. **Check the claim.**
   - Code: follow the changed path, confirm it fixes the cause and not only one symptom, and look at everything else
     that calls the changed code.
   - Data: check the rows against the pinned public sources (`tools/forever-data`: EG Link, QuestieDB, forever-db,
     Wowhead tooltips) and the client's own DB2 data. Rows the sources disagree with are a finding.
   - Protocol: check message numbers and packet layouts against the client build.
3. **Test it.**
   - Code: a unit test in the fork's `tests/` (Catch2, built with `BUILD_TESTING`; the fork already has 72 test cases in
     22 files) that fails without the change and passes with it. Where the code can only run inside a live world (packet
     handlers, scripts), the logic moves into a function a test can call first, as its own commit.
   - Data: a check query the world dry run runs (the same dry run as the world import plan, `docs/forever-import.md`, in
     pull request #23).
   - What neither can reach gets a written in-game test for the PTR realm.
4. **Decide**: take it; take it with our fixes on top (our own commits, the author credited); hold it, saying why; or
   drop it (wrong, or replaced by another). Every verdict goes in a review log in the fork, `docs/upstream-prs.md`: pull
   request, claim, verdict, evidence, test.
5. **Land it** as a merge of the pull request's own commits. Upstream often squashes or rebases instead (9 of its last
   40 merged pull requests), so git won't always see them as the same commits. When upstream lands a pull request we
   took, the sync takes upstream's version, re-applies any fix of ours on top that upstream didn't take, and notes it in
   the review log.

## TrinityCore's own changes

TrinityCore fixes crashes, spells and movement every week, and `forever` takes few of them. TrinityCore's `master` is
never merged into `everlake` whole: each commit since the branch point goes through the same steps as a pull request and
comes in by `git cherry-pick -x`, so the commit names its source. The Forever client is on the same engine line as
retail 12.x (its builds run 70205-70862, TrinityCore's 12.1.5 support 70448-70783), and `forever` still uses retail's
data layouts almost unchanged. So no kind of commit is skipped by category; each is checked against the Forever build:

- **Core fixes** (crashes, memory, movement, AI, database): taken, with a test where the fix is testable.
- **Refactors**: taken when later fixes build on them, so those fixes still apply.
- **Spells and scripts**: taken where the spell exists in the Forever client and works the same way, checked against the
  client's spell data.
- **Client data and messages** (DB2 structures, packet layouts, new builds): taken only where the Forever build has the
  same layout; the rest goes to the retail realm's branch.

`forever` also picks TrinityCore commits by hand (#32027 and #32047 so far), so the same fix can arrive twice under
different hashes. The daily check matches commits by `git patch-id`, not by hash, and lists TrinityCore commits not
sorted yet, so `everlake` never falls far behind.

## Staying current

- **Upstream.** A daily check merges upstream `forever` into a test branch off `everlake`, builds it and runs the tests.
  A person merges it into `everlake` after reading what came in. Upstream's direct pushes get the same read as pull
  requests.
- **New pull requests.** The same check lists upstream pull requests not reviewed yet and whether each still applies.
  Nothing is taken automatically.
- **SQL taken early.** If upstream later merges a different version of an SQL file we already run, under the same name,
  the worldserver's updater would apply it again and then every later custom file; renamed, it would be applied twice.
  The daily check compares every SQL file `everlake` holds with upstream's and flags each difference. Each is decided by
  the same rules as the world import: keep ours, or add a new file with the difference. A rename is only safe when the
  same merge deletes our copy; kept differences go on a list of accepted ones so the check stops flagging them.
- **SQL file order.** An upstream file dated before one we took early runs after it on the live database (it arrives
  later) but before it on a fresh build. If both change the same rows, the two end up different. The import plan's two
  dry runs (from scratch, and stepped from the deployed pins) are compared with each other, which catches this; the fix
  is a new file.
- **Everlake** moves its pin only to an `everlake` commit whose CI passed.

## CI

The fork's `linux-build` workflow already builds with `BUILD_TESTING=1` and runs the unit tests. Its workflows run on
every push to every branch, so they get branch filters: `everlake` and pull requests into it, not the mirror branches.
Linux only to start (the macOS and Windows builds can come back later), plus a second build with AddressSanitizer and
UndefinedBehaviorSanitizer running the same tests, to catch the use-after-free and out-of-bounds kind of crash several
of the open pull requests fix.

## Order

1. **Crashes and exploits**: #276 (crash at start after a guild rank was deleted), #277 (freed loot read), #278 (lookup
   command crash), #279 (taxi index outside the mask), #280 (battleground with no map), #281 (bnetserver request limit),
   #282 (currency bought for free).
2. **Client and protocol**: #274, #275, #291 (our patch 0003), #292, #297-#300, #302 and the rest of the 70790 messages.
3. **Game code**: spells, talents, pets, trainers, auction house, PvP.
4. **World and hotfix SQL**, checked against the sources. The two large hotfix sets (#309, 5,982 lines; #318) are
   checked against a sample of the client's own hotfix data.

Overlaps to settle in review: #122, #127 and #325 all change the Classic spell scripts (Lightning Shield, Flametongue,
weapon imbues) and clash with each other; #70 and #275 both find mail recipients. #150 (the Talented perk, after #151
was merged) and #271 (logins for builds 70707 and 70755, older than the 70862 we run) no longer apply to our pin.

## Decided (2026-11-08)

1. **Name**: `wow-trinitycore-everlake`, one repository for every realm's core.
2. **Base**: `forever`, what Everlake runs today. The bot module (`forever-bots`, 80 commits ahead) can come in later as
   its own reviewed step.
3. **Giving back**: later, case by case; nothing goes upstream without asking first.
4. **CI**: GitHub's runners (free for a public repository), with ccache.
