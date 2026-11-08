# Classic on the Forever client: how big is the difference?

Measured 2026-11-08. Builds: Forever **1.60.1.70862** (`wowf`) and Classic Era **1.15.9.70576** (`wow_classic_era`),
both read straight from Blizzard's CDN.

The plan (user, 2026-11-08): three realms on one launcher. **Forever** stays exactly as Blizzard made it. **Classic** is
its own realm, a 1:1 recreation of WoW Classic running on the Forever client (its engine and UI), from the same install.
**Retail** runs on the retail client with TrinityCore master. This page measures what the Classic realm has to add to
the Forever install, and how.

The rule that shapes everything: Forever must stay pure, so nothing Classic needs may replace a Forever file or row.
Classic's differences go **beside** Forever's: files under new file ids, and table rows sent as the Classic realm's own
hotfixes (the client keeps one hotfix set per realm, proven by the two-realm test on 2026-11-07).

## Results

### Files

| | Files | Size (compressed) |
|---|---|---|
| Classic Era build, all files | 157,062 | about 4.7 GB |
| Same bytes in Forever | 50,364 | 1.7 GB |
| Same file id, different bytes | 98,966 | 2.7 GB |
| Only in Classic Era | 7,732 | 0.2 GB |
| Only in Forever | 1,096,326 | 72 GB |

- **Space saved by sharing the install is small.** Classic needs at most 2.9 GB that the Forever install doesn't
  already hold, against 4.7 GB for the whole Classic Era client. The reason to do it is the Forever engine, UI and one
  launcher, not disk space.
- **Forever's build holds far more retail art than expected.** The 1.1 million Forever-only files include about 70,000
  creature files, 200,000 item files and 230,000 sound files. What Forever does **not** have is terrain past vanilla:
  no tiles for Outland (`expansion01`), Northrend or any later continent. This corrects an earlier note that Forever cut
  retail's models; it cut retail's terrain and game tables.

### Terrain

Azeroth and Kalimdor: 5,018 tile files differ by bytes, 1,682 are the same. Bytes alone don't say whether the ground
moved, so `adt_heights.py` compared the heights of 40 random differing tiles:

- **12 of 40 have real ground changes** (dozens to all 256 chunks moved, up to 650 yards). Some are new land where
  Classic has open sea (Azeroth 26_57, Kalimdor 27_51).
- 2 of 40 moved one chunk by about 2.5 yards.
- 26 of 40 have the same ground; the file was re-exported (Forever's copies are 30-80 % bigger).

So about a third of the continents' ground is Forever's own. **Classic needs its own Azeroth and Kalimdor**: Classic
Era's tile files under new file ids (under 1 GB), and the Classic realm's `Map` rows for maps 0 and 1 pointing at
Classic's WDTs. Not measured: buildings and objects on the tiles reference models by file id, so where Forever changed
a building, Classic shows Forever's version unless that model is copied too.

### Game tables

Compared row by row from wago.tools CSVs, matching columns by name. Several columns differ on almost every row only
because of the engine (Forever moved base points to a float column, sets `Attributes_15` 8192 on every spell, zeroes
`BaseLevel` and `Talent.ClassID`, and so on); `normalized.py` drops those. Counts are rows Classic must send from its
realm: rows Forever changed, plus rows Forever doesn't have.

| Area | Forever changed | Only in Classic | Notes |
|---|---|---|---|
| Spells (16 tables) | about 17,300 | about 37,300 | 1,985 spells' text, 7,125 effects, 5,387 misc rows; 4,869 spells Forever removed |
| Items (`Item`, `ItemSparse`, `ItemEffect`, `ItemSet`) | about 13,700 | about 19,900 | stat changes, 2,019 on-use spells; `ItemSparse` has 10,191 Classic rows Forever's file lacks |
| Creature looks (`CreatureDisplayInfo`) | 7,335 | 2 | Forever points player-race models at the HD ones (`nightelfmale_hd.m2`); Classic uses the originals |
| World (`AreaTable`, `Map`, `Faction`, `Light` ...) | about 600 | about 100 | ambience, map flags, reputation masks |
| Talents (`Talent`, `TalentTab`) | 0 | 0 | Forever still ships Classic's trees untouched, but its talent frame reads trait trees |
| Quests (`QuestV2`) | 5 | 2 | quest content lives on the server (vmangos), not in the client |

**Total: roughly 60,000 to 100,000 rows.** Some engine noise is probably still in the spell-misc and item-flag counts,
and Forever's `ItemSparse` may lack rows that Blizzard sends as live hotfixes, so read it as an upper bound.

## What this means

1. **The game tables decide it, not the files.** Test 1 sent a few hundred hotfix rows. Classic needs about a hundred
   times that, from one realm, cached by the client after the first login. The next test: a realm sends about 100,000
   hotfix rows; measure the first login, the client's memory, and whether switching between Forever and Classic stays
   clean. If the client copes, Classic on Forever works as planned.
2. **If it doesn't cope**, the fallback is our own table files in the patched build, with Classic's rows as the base and
   the Forever realm sending Forever's rows as hotfixes instead. It's the same volume the other way round, so it only
   helps if the problem is the first download rather than the row count.
3. **Talents:** Classic's trees are already in the client's files; they need building as trait trees for Forever's
   talent frame, the way Test 1 built the Death Knight tree.
4. **A choice for the user: Classic's look.** Forever uses the HD character models. A 1:1 look means the Classic realm
   points 7,335 creature displays back at the original models. Whether Forever's build still holds the original model
   files as they were wasn't checked: 4,338 character files share ids with Classic Era but differ in bytes.
5. **TBC and WotLK later:** Forever has no Outland or Northrend terrain, so those continents come in the same way as
   Sunstrider Isle did. Much of their art is probably already in Forever's build.

## Re-running it

The scripts are in `tools/era/classic_diff/`. Pick a work folder outside the repo (downloads are untrusted data):

```bash
W=~/everlake-classic-diff; mkdir -p $W/dl $W/wago
python3 -I tools/era/classic_diff/index.py $W/cache-wowf wowf
python3 -I tools/era/classic_diff/index.py $W/cache-era wow_classic_era
curl -sL -o $W/dl/listfile.csv https://github.com/wowdev/wow-listfile/releases/latest/download/community-listfile.csv
python3 -I tools/era/classic_diff/files_compare.py $W
python3 -I tools/era/classic_diff/adt_heights.py $W
T=SpellName,Spell,SpellMisc,SpellEffect,SpellLevels,SpellPower,SpellCooldowns,SpellAuraOptions,SpellCategories
T=$T,SpellClassOptions,SpellReagents,SpellShapeshift,SpellTargetRestrictions,SpellInterrupts,SpellXSpellVisual
T=$T,SkillLineAbility,Talent,TalentTab,Item,ItemSparse,ItemEffect,ItemSet,CreatureDisplayInfo,CreatureModelData
T=$T,GameObjectDisplayInfo,AreaTable,Map,TaxiNodes,UiMap,Faction,FactionTemplate,Light,QuestV2,ItemModifiedAppearance
python3 -I tools/era/classic_diff/tables_compare.py $W 1.60.1.70862 1.15.9.70576 $T
python3 -I tools/era/classic_diff/normalized.py $W
```

Indexing downloads about 150 MB of encoding files and 1,404 archive indexes per build and takes a few minutes. The
builds stay pinned in each cache's `tact/build.txt`. `normalized.py` expects the CSVs of the tables it lists to be
cached already.
