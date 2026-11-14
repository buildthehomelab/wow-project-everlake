# Karrz 0.1.36 pin review — November 13, 2026

The candidate core is `143ea9392432ff8dcac97f282955b861dc0ac177`, the reviewed head of [core PR #54](https://github.com/buildthehomelab/wow-trinitycore-everlake/pull/54). Merge that PR with this commit retained, and require its full build matrix to pass before merging this dependent pin. If its code changes, update and recheck the pin.

Update after the merge: #54 merged as `88746967bc2a62782d338e920ecd3eea25123773`, with `143ea939` retained and one more commit, `9a7fc384` (a signed compare in `classic_instance_razorfen_downs.cpp` that gcc's `-Werror=sign-compare` rejects; Karrz builds with MSVC and clang does not warn). The image builds with gcc, so the pin is the merge commit.

## Recent changes and coverage

The current integration main already pins core `b5c98f7ad417269dbf7dec8e00782b9d43771a1c` and PTR world data `cb7c92787a9ab262b268d9bd6d5a63be1d95d466`, both matching their respective merged branch heads at review. This includes the 0.1.35 catch-up, pet movement and surname fixes, and the merged world-data work through PR #166 (vendor stock and drops). The world-data pin stays unchanged.

The candidate adds 0.1.36's swing timer, Revive, guild charter, transmog and quest item counting fixes; Razorfen Downs gong and class scripts; quest and spawn data; bot dungeon/raid tactics and commands; and client 70938 records. The integration entrypoint now accepts 70938 alongside 70790 and 70888. This does not change the launcher's download build.

The source review records 54 new world SQL files, eight new hotfix files, one auth file, one characters file and bot migration 0040. An existing hotfix file changes and will replay. The source PR reports a complete scratch replay and a second unchanged pass against this world-data pin; those results are upstream evidence, not a fresh runtime test of this pin.

Open work excluded: core #40 (BFD shrine waves), core #41 (Naralex retry), and world-data #165 (quest rewards and profession materials). A commit pin cannot include those until they are integrated. Tracker and launcher changes have separate deployment paths.

## Integration review

All core build arguments, PTR image tags and PTR IMAGE_TAG use the same full SHA. The world-data SHA stays in the PTR tag, so changing the core produces a new image name. A new dynamic-respawn migration repeats the existing rule after the candidate's latest world files. Its November 14 filename is for updater ordering, not the review date: November 13 sequence 00 would sort before the source's sequence 91.

Runtime points from the core review to check on PTR:

- Traditions of the Bluff (97485): item count handling lost its earlier exception; complete the quest through its item handoff.
- Bots now sell or destroy outgrown soulbound green/blue gear by default (`Playerbot.Behavior.SellOutclassedGear`). Check companion off-spec gear before relying on that default.
- `.bot goto` allows players to travel to their own bots.
- Check Heroic Strike auto-attacks, Revive, Razorfen Downs gong, pet movement and full-name whispers/invites.

## Deployment

1. Merge core #54 after its builds pass, then this pin after its CI passes. Pull the integration repository on TrueNAS.
2. Check `.env`: a `PTR_TC_COMMIT` or `PTR_WORLD_DATA_COMMIT` override wins over the defaults. Use the candidate core and world-data SHAs above. `TC_COMMIT` also overrides the live fallback build.
3. Restart the PTR app to build its new image. Check startup and DBErrors.log, including world/hotfix updates and bot migration 0040, then perform the in-game checks above.
4. After the PTR passes, run `sudo scripts/promote.sh` and restart the live app, including bnetserver. PTR shares login with live, so 70938 acceptance cannot be established by restarting PTR alone.
5. Run `sudo scripts/promote.sh status` to verify the selected image. Image rollback is `sudo scripts/promote.sh rollback` followed by restarting live; this only swaps image tags and does not undo database migrations.

No image build, hosted restart, promotion or in-game verification was performed for this pin.

## Local validation

`tools/ci/check-repo.sh`, `bash -n docker/entrypoint.sh` and `git diff --check` pass. Both Docker patches apply in order to the exact candidate's affected source files. The new respawn migration's SQL statements match the preceding migration exactly. Docker Compose and shellcheck are unavailable on this workstation; Compose rendering and the full CI suite remain required on the PR. No fresh database replay was run.
