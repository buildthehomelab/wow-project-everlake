# China Undead look, per character

Every Undead can pick the China look: no bones showing, buff and pale, intact face. Pick **Skin Type: Fresh** (body
tab) and one of the **China skin colours, 7-12** (Skin Color, head tab), at character creation or at the barber.
Characters on Bony keep the normal look. It is all Blizzard's own art in the Forever client, switched on by server
data: no client files.

Status 2026-11-08: works in the creator on the Mac mini (male, test copy, China setting off). Not yet checked:
finishing a character and logging in (the server saving Fresh with a China colour), a female, other players seeing it.

## What it took

| File | Push | What |
|---|---|---|
| `sql/everlake/2026_11_08_03_hotfixes_undead_fresh.sql` | 9570003 | Fresh (6529 male, 6526 female) offered with Bony's requirement 55 |
| `sql/everlake/2026_11_08_05_hotfixes_undead_china_colours.sql` | 9570005 | Requirements 4975-4977 with OverrideArchive -1 |

Run both into the realm's `hotfixes` database, then restart the worldserver (the app in the TrueNAS UI).

## How Blizzard built it

- The China client (the client setting `overrideArchive` = 1) reads censored copies of some files: Blizzard's build
  keeps them under the same FileDataIDs, in root blocks flagged LowViolence (0x80). Forever 1.60.1.70790 has 7,737,
  671 of them for the Undead. `everlake-client.sh china-mode on|off` switches a Mac's copy into that mode.
- Customization data says which choices that mode may use: a `ChrCustomizationReq` with OverrideArchive 1 means
  "only with the China setting on", 0 "only with it off", -1 "always". The core doesn't check it; the client does.
- Undead **Skin Type** (male 567, female 568): Bony (6527/6524, requirement 55) and Fresh (6529/6526, requirement
  4975, China only). Fresh switches geosets 19, 29 and 30 from 1 to 2: covered pieces instead of bony ones, which the
  normal model has too.
- Undead **Skin Color** (58/63) has six normal colours (requirements 61/66) and six China colours (`skin00_12`-`17_hd`,
  requirements 4976/4977, China only), with the same swatches. `ChrCustomizationReqChoice` pairs them: normal colours
  need Bony, China colours need Fresh. The China textures carry their own painted face, so they need no Face layer.
- With only Fresh offered, a China colour was shown and then dropped by the creator's next check, and the normal
  colour it fell back to pulled Skin Type back to Bony. Hence the second file.

## Dead ends (2026-11-07/08)

- **Skinned models** (ChrCustomizationSkinnedModel, as retail adds Mechagnome arms): the China body drew in the right
  shape but black, with the character skin, with a named texture and even with Blizzard's own Undead model. Any body
  attached this way draws black on this character.
- **Merging the China model into Blizzard's model** as extra geosets: it differs in about 50 parts per sex, and the
  male would pass the 65,535-vertex limit of a level of detail (72,693 at the closest). Not needed in the end.
- **Showing Undead Skin Color by giving the option Flags 80** like other races: it was never hidden (head tab).
- A first Fresh test drew black parts; most likely the China textures still streaming into the test copy.

The patched-build pipeline these tests used stays for other added files: `tools/tact/patch.py`, the `cdn` service and
`cdn-build` (`docs/custom-files.md`).
