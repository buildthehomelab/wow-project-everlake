# Classic world-entry crash investigation

Status: candidate experiment, not a release fix. Do not promote or release until live world entry and terrain have been verified.

The Mac client 70790 reproduces an ERROR #132 invalid-memory-access crash when the Roleplay human warrior enters map 0. The received Map 9000 hotfix points to parent 0 and WDT 40011612. Both WDTs resolve locally, and the installed overlay passes hash verification. This establishes identity and storage integrity, not rendering compatibility.

Map 9000 currently has zero rendering flags. All 687 active overlay tiles reference split object and texture ADTs. The pinned core names flags 0x200 and 0x400 ObjectFile and TextureFile. The proposed experiment sets only those two flags, preserving the other fields. It has not yet been shown to cure the crash.

Use the repository checkout for this branch on the host. No certificate-trust change or standalone database command is needed.

```sh
sudo bash scripts/classic-entry-test.sh check
sudo bash scripts/classic-entry-test.sh apply
```

The script targets the existing TrueNAS containers declared by this deployment. It checks realm 71, port 8095, content set 138, the Classic database overrides, and the expected map and hotfix rows. Apply backs up the map row and original Flags1 in a private temporary directory, stops only the Roleplay worldserver, changes Flags1, advances the hotfix push/unique ID, and restarts that container. Keep the printed backup path. Forever, PTR, characters2, and the other map fields are not modified. Coordinate with anyone using Roleplay before running apply.

Reconnect through the launcher, select Roleplay, and enter the same human warrior. Confirm world entry, the new flags in the client hotfix cache, pre-Shattering Northshire terrain, movement and collision, then relog and repeat. Hash verification or reaching character selection does not count as a pass. Capture logs if it fails.

To undo, use the backup path printed by apply:

```sh
sudo bash scripts/classic-entry-test.sh rollback /tmp/everlake-classic-entry.XXXXXXXX
```

Rollback restores the original Flags1 and advertises a newer hotfix revision so the client receives the restoration. If the candidate succeeds, update the provisioning SQL and add the validated upgrade to the release before merging; do not leave the production definition dependent on this experiment.

## Result of the split-file flag test

On 2026-11-12 the live Mac client received push 9690001 with Flags1=1536, then reproduced the same EXC_BAD_ACCESS at address 0x878 as map 0 started loading. The two flags alone did not resolve the crash. Do not promote that experiment as a fix.

## Isolate terrain activation

The next diagnostic temporarily removes only the map 0 → 9000 default terrain swap from world_classic. It preserves the hotfix, all character data, other terrain swaps, and all client assets. It inherits the same deployment guards as the previous script. The script stops only Roleplay during the database change and restarts it afterward.

```sh
sudo bash scripts/classic-terrain-isolation.sh disable
```

Keep the printed restore directory. Reconnect and try the same human warrior. If entry succeeds, record the base-terrain result without travelling or changing the character; it does not verify Classic terrain. If entry still crashes, capture its report. Restore the Classic terrain activation after the comparison:

```sh
sudo bash scripts/classic-terrain-isolation.sh restore /tmp/everlake-classic-terrain.XXXXXXXX
```

The restore directory is separate from the earlier flag backup. This experiment is not a release mode and must not be left disabled as the solution.

## Result with default activation disabled

On 2026-11-12, a separate test account entered Forever's Northshire successfully
with the same client and overlay. Classic then crashed at `Load Map Begin : 0`
with EXC_BAD_ACCESS 0x878; the first ten relative stack frames match the earlier
crash. The host check confirms zero Classic terrain activation rows, with only
stock map 0 defaults 736, 1066 and 1190 remaining. Map 9000 is still advertised,
with parent 0, WDT 40011612 and Flags1=1536. Removing the default swap alone did
not fix world entry.

## Isolate the custom map's parent relationship

The core registers maps with `ParentMapID != -1` in its terrain-swap registry
separately from loading default activation rows (`ObjectMgr::LoadPhases`). This
motivates a narrower comparison; it does not establish the client's crash cause.
Temporarily set only Map 9000's parent to -1 while activation stays disabled:

```sh
sudo bash scripts/classic-parent-isolation.sh detach
```

This diagnostic checks the isolated realm, map and hotfix identity, refuses active
Classic defaults, saves the original map row, stops only Classic, changes the
parent and advances the advertised hotfix revision, then restarts Classic. It
refuses revision overflow. No client files, character rows or other realms change.

Fully quit the game, reconnect to Classic, and try Alden Classicbrook. Inspect the
received Map 9000 hotfix for ParentMapID=-1 before interpreting the result. A
successful entry would only verify base terrain, not Classic terrain. If it still
crashes, preserve the report and compare the stack; do not call this a fix.

Restore the relationship **before** restoring terrain activation:

```sh
sudo bash scripts/classic-parent-isolation.sh restore
sudo bash scripts/classic-terrain-isolation.sh restore /tmp/everlake-classic-terrain.XXXXXXXX
```

Use the actual terrain backup path printed by the earlier disable command.
The parent restore uses the guarded original value 0 and a fresh hotfix revision.
The earlier flags experiment remains separate. Do not release until the intended
Classic terrain is active and world entry, terrain, collision and relog pass.

## Detached-parent result and full-detail candidate

On 2026-11-12, Alden Classicbrook entered Classic's Northshire twice, with a
logout between attempts, after the client received push 9690002 and parent -1.
Activation remained disabled. This verified base-world entry, not Classic terrain.

The original crash instruction dereferences a null texture-resource pointer at
`0x10123c598` (unslid arm64 address, client UUID
`18AE944B-BDC7-339E-9060-37F9F59F775F`). Local inspection of loaded executable code
traces this resource to the terrain tile-loading path. The low-detail constructor
can omit that resource; the subsequent readiness check accesses it unconditionally.
The packaged donor WDT MPHD flags are 584 (0x248), with no LoadLodAdt bit 0x100;
the installed base WDT has that bit. The client's WDT loader derives its low-detail
mode from that bit and the parent map. This is evidence for a low-detail mismatch,
not yet proof that the candidate resolves every terrain issue.

The core defines MapFlags `DisableLowDetailTerrain = 0x00200000`; inspection of
this exact client confirms it reads that flag into terrain-loader state. The
candidate adds this flag to map 9000's split-ADT flags, restores parent 0 and adds
the Classic default swap in one transaction across the isolated schemas.
It changes no assets or executable code. Full-resolution tiles remain packaged.

```sh
sudo bash scripts/classic-full-detail-terrain.sh apply
```

Apply requires the exact tested baseline: parent -1, Flags1=1536 and no activation
for map 9000. It backs up the map row, stops only Classic, updates the map and
activation in one transaction, advertises a fresh hotfix revision and restarts
Classic. It refuses unexpected state and uint32 revision overflow.

Fully quit and relaunch the game. Verify the received map has parent 0,
Flags1=2098688 and WDT 40011612. Enter Classic, confirm pre-Shattering terrain at
recognizable changed locations, walk across tile boundaries, check ground/building
collision, and repeat after logout and a full restart. Check other starting zones
covered by the Eastern Kingdoms overlay and revisit Forever to verify separation.
Character selection, base terrain and hash integrity alone are not release gates.

If it fails, return to the last working diagnostic baseline:

```sh
sudo bash scripts/classic-full-detail-terrain.sh rollback
```

Rollback requires the exact candidate registration and activation comment. It
removes only this activation, restores parent -1 and Flags1=1536, and advertises a
new revision. Do not combine the earlier restore commands with this candidate.
Do not promote this to provisioning SQL or release until live validation passes.
