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
