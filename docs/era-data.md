# One era's class data per realm (gate 5)

**Back on 2026-11-06:** needed if every ruleset runs on the one Forever client (the goal); not needed for the
three-client fallback.

The long-term plan is one realm per game mode (Forever, Classic, TBC, WotLK and later), all sharing one login
server. Each mode needs its own era's spells, talent trees and trainer lists, while the client stays the same
Forever client. This gate proves that a realm can give the client another era's class data, and that switching
realms switches the data without the two mixing.

What has to match the era is the content: which talents and spells exist, their numbers and the point rules. The
screens don't have to look like the originals:

- **Forever and Classic** keep Forever's own Classic-style talent screen.
- **TBC and every later expansion** use the same retail talent screen. Each era's tree is built as a retail
  trait tree, so one screen and one server system cover them all.

Nothing here is built or run yet, except Test 1 below.

## What the client and core already have

Checked on 2026-11-06 against client build 1.60.1.70790 and core `6ac7bece`:

- Forever's talent screen is the old Classic-style tree (three tabs, points per tier).
- The client also ships the retail spellbook and talent frame (`Blizzard_PlayerSpells`) and the trait-tree tables
  (`TraitTree`, `TraitNode` and the rest).
- The core has the full retail trait system: `TraitMgr`, its packet handler, and hotfix support for the trait
  tables. Building a TBC tree as a trait tree is data work, not new server code.
- The core can hotfix the spell tables too, including `SpellMisc` and `SpellRange`.
- Each worldserver reads its own `HotfixDatabaseInfo`, so each realm can have its own hotfix database.
- **Unknown:** whether the Forever client opens the retail talent frame at all, or whether something (a game rule,
  the client's game type) keeps it on the Classic screen. This is the first thing to find out.

## Setup

- **Realm 1, Forever:** the realm as it is today.
- **Realm 2, TBC test:** same image, own characters database, own hotfix database, on the same login server, with
  whatever setting turns on the retail talent frame.
- **Realm 2's hotfixes, warrior only,** with the content taken from the TBC Classic (2.5.x) tables:
  - The full TBC warrior talent tree (Arms, Fury, Protection, 41-point talents), built as a trait tree with TBC's
    point rules (one point per level from 10, 61 points at 70).
  - Mortal Strike at its TBC rank and values.
  - A spell whose range differs between the two eras, to test the client's own range check.
  - Two warrior spells that are new in TBC: Intervene and Spell Reflection.
- **Server side:** realm 2 teaches and trains the TBC spells; a GM command makes a level-70 warrior.

## Tests (on the Mac mini, run by one `everlake-client.sh` subcommand)

1. Log in to realm 2 with the level-70 warrior. The retail talent frame opens with the TBC tree; spending and
   resetting points works and the server keeps them after a relog. Screenshot.
2. Mortal Strike's tooltip shows TBC numbers. Intervene and Spell Reflection are in the spellbook and can be
   cast, and the server applies them.
3. The client's own checks follow realm 2's data: a cast from a distance that is in range for one era and out of
   range for the other behaves as the TBC data says.
4. Back to the ruleset picker, then realm 1: Forever's Classic-style screen and Forever tooltips are back, with no
   TBC rows left over. Screenshot.
5. Back to realm 2: TBC data again. Count the hotfix requests in the server log to see whether the client asks
   again or reuses a cache it kept for that realm.
6. Switch five more times, with one client restart in between. Check the client's `Cache/WDB` folder for one cache
   per realm or a single shared cache.
7. **Addon prototype `EverlakeEra`:** it knows which mode it is in, keeps data per realm in its saved
   variables, and dumps the spellbook and talents for comparison. After the switches it holds both realms'
   data, each correct.

## Passes when

- Every switch shows the right screen, tree, tooltips and spells, with no mixing.
- Talent points spent on realm 2 are saved and applied by the server.
- The new TBC spells can be cast.
- The addon keeps correct data for both realms.

## If it fails

- **The client keeps one cache and mixes the eras:** give each realm its own range of hotfix ids so they never
  collide, and send the full era set on every login.
- **The Forever client won't open the retail talent frame:** show the TBC tree in the Classic-style screen (it's
  the same kind of tree) through the `Talent` table, or have the Everlake addon draw it and learn talents over
  addon messages, with the server checking each one.
- **A trait-tree or spell table can't be hotfixed:** add it to the core's hotfix store as a patch.

## Test 1: classes the Forever client doesn't ship (2026-11-07)

**The question:** can the Forever client (1.60.1.70790) create and play a class it doesn't ship, when our server
sends the data? If yes, the Classic → WotLK ruleset gets its Death Knight on the one client, and the retail ruleset
can at least start there. If no, the retail ruleset needs the retail client.

**Status:** research done, kit on the spike server, client test waiting for the user (checklist below).

### What the client has

Read from the Forever build (wago.tools tables, `tools/tact` for UI files, the community listfile):

- **The data is cut back to vanilla.** ChrClasses has 9 classes (no Death Knight 6, Monk 10, Demon Hunter 12,
  Evoker 13). SpellName has 32,088 spells against retail's 416,287. No Death Knight, Monk or Demon Hunter spell is
  there, not even TBC's Intervene. No Death Knight skill line. PowerType has no Runes, Runic Power or Chi. SpellVisual
  has 6,162 rows against retail's 169,894.
- **The engine is retail.** Every spell and skill table has exactly the layout of retail 12.1.5.70783, except
  SpellDuration (one extra field) and SkillLineAbility (two). Retail rows can be sent as they are. WotLK Titan
  (3.80.2) rows need small mapping (SpellEffect, SpellMisc, SpellPower and a few more differ by a field or two).
- **The art is there.** The class icons of Death Knight, Monk and Demon Hunter, the icons of all 8 Death Knight test
  spells, and 9,430 files with "deathknight" in their path ship in the client.
- **Character creation is data-driven.** `Blizzard_CharacterCreate` loads a Forever-specific (`camelot`) version.
  It lists whatever `C_CharacterCreation.GetAvailableClasses()` returns and already has layout slots for Monk,
  Demon Hunter, Death Knight and Evoker.
- **Some class frames are retail-only.** In `Blizzard_UnitFrame.toc`, the rune bar (`RuneFrame`), the class power
  bars (Chi and others) and the totem frame load only for other game types, never for Forever (`camelot`). A Death
  Knight on the Forever client gets no rune display from Blizzard's UI. Our own addon can draw one: the rune API is
  in the client.
- **Forever's talent screen is the retail talent frame.** `Blizzard_PlayerSpells` (the retail spellbook and talent
  frame) loads with Forever-specific files. Forever's Classic-style trees are retail trait trees: one TraitTree per
  class (Warrior 1117), linked through SkillLineXTraitTree to the class skill line, with the three tabs as node groups
  and one currency (3820, a point per level from 10, 51 at most). The frame's per-class art table (`ClassVisuals`)
  lists only the 9 Forever classes, but its code is nil-safe.

### What the server does

Core `5206a7275f` (forever-bots), world database = retail TDB:

- **The server reads the client's ChrClasses.** It has no class 6 either, so it skipped all 59 Death Knight, Monk,
  Demon Hunter and Evoker rows of `class_expansion_requirement` ("Class 6 ... does not exists") and their
  `playercreateinfo` rows. A ChrClasses row sent by hotfix fixes both sides: the server loads hotfix rows into its own
  stores at startup.
- **Expansion gate:** TDB asks ActiveExpansionLevel 2 for a Death Knight and 4 for a Monk. A Forever session's
  active expansion is 0 (`Expansion = 0`; the accounts themselves are 11), so creation would fail with "requires
  expansion". The kit lowers the 8 Forever races' rows to 0.
- **Three crashes the kit has to avoid:**
  - `Player::Create` reads the PowerType row of each class power without a null check: a Death Knight without
    Runes and Runic Power rows crashes the worldserver.
  - The core's Death Knight runs on retail runes (`POWER_RUNES`, 6 runes). With WotLK's Blood, Frost and Unholy
    rune types (power types 20-22, as in the Titan data) `m_runes` stays empty and the first regeneration tick
    crashes. **The WotLK ruleset's rune types are core work**, not client work.
  - The default specialization is `ASSERT_NOTNULL`: every class needs a ChrSpecialization row.
- **Start positions:** TDB puts Death Knights and Monks of the 8 old races at their race's normal start (Northshire
  and so on). Acherus (map 609) isn't in the client; the WotLK ruleset will need it the way map 530 was added.
- **Bots:** this realm counts as vanilla (MaxPlayerLevel 60), so world bots only roll vanilla race and class pairs.
  The new classes don't change the bot population.
- **The core's DK scripts check for helper spells** (Death Coil needs 47632, 137007 and 196263; Death Strike needs
  45470, 77513, 77535, 137006 and 66188). Without them the script is skipped and Death Coil does nothing. The kit
  sends them.
- **Spell tooltips:** this core has no hotfix table for `Spell` (the description text), so a sent spell has a name,
  icon, cost and range but probably no description.

### The kit (applied to the spike server 2026-11-07)

Made with `tools/era/hotfix_kit.py`, which lays another build's DB2 rows out as the Forever client's tables and
writes hotfix SQL. It also copies whole spells (every spell table keyed by SpellID, plus missing shared rows, and
visuals only where Forever has them) and whole talent trees. The kits are in `tools/era/kits/`.

| File | What | Hotfix pushes |
|---|---|---|
| `sql/everlake/2026_11_07_01_hotfixes_test1_classes.sql` (`test1.json`) | ChrClasses 6 and 10 (MoP Classic rows, Forever-style flags), PowerType Runes, Runic Power and Chi, class powers, specializations 1455 and 1450, CharBaseInfo for races 1-8, DK skill line 796, 24 retail spells (Death Coil, Death Strike, Anti-Magic Shell, Obliterate, Howling Blast and their helpers) with their `Spell` text rows in `hotfix_blob`, and the all-class, weapon and armor skill rows for both classes | 9540020-9540024 |
| `sql/everlake/2026_11_07_03_hotfixes_test1_talent_tree.sql` (`test1_tree.json`) | Forever's Warrior tree copied as TraitTree 954100 and linked to the DK skill line: 53 talents, 43 groups, 18 tier conditions. 498 rows. It tests whether a tree the client never shipped opens and takes points. The talents are Warrior spells | 9540010-9540015 |
| `sql/everlake/2026_11_07_02_world_test1_classes.sql` | `class_expansion_requirement` for DK and Monk on races 1-8: 0/0 | |

The Monk is the probe of the retail engine: class, powers (Energy, Chi, Mana) and spec only, no spells.

To rebuild a kit (the schema file is the `information_schema` query in the tool's header):

```sh
python3 tools/era/hotfix_kit.py tools/era/kits/test1.json --schema <hotfixes schema.tsv> \
    --dbc data/dbc/enUS --cache <dir> --out sql/everlake/2026_11_07_01_hotfixes_test1_classes.sql
```

Undo: `DELETE FROM hotfix_data WHERE Id BETWEEN 9540010 AND 9540024;`, the `hotfix_blob` DELETE in the classes file, the row DELETEs at the top of each table
block in the two hotfix files, and the UPDATEs in the comment of the world file. Then restart the worldserver.

### Checked on the server (2026-11-07, 01:47-01:52)

- The worldserver loaded all 840 kit rows (25,270 hotfix records, was 24,430) and 288 class requirement rows (was 234).
  Classes 6 and 10 are known: no more "Class 6 ... does not exists" or "Wrong class 6 in `playercreateinfo`". Only
  Demon Hunter and Evoker are still skipped.
- The DK scripts for Death Coil, Death Strike, Howling Blast and Anti-Magic Shell load. Two talent scripts are skipped
  (`spell_dk_vestigial_shell`, `spell_dk_voracious`), as expected without their talents.
- **A Monk was created and logged in** with the console command `.playerbot create Testmonk human monk 1`, which
  runs the core's `Player::Create`. It entered the world at Northshire, with no errors.
- **A Death Knight loaded and played:** the same character as class 6 at level 15. It logged in, got its 6 runes and
  the Death Knight skill line (796, 75/75), ran for a minute of regeneration ticks, logged out and saved. No errors,
  no crash. The bot was deleted afterwards.
- **Appearance:** Forever's customization data has the Death Knight sets: 110 requirements are DK-only (for example
  the glowing eye colour, choice 4535), and others exclude the DK. The core checks them on create and on every
  login. A Monk eye colour on a DK is refused ("wrong Appearance values"), which is why the bot factory's DK roll
  failed: its random appearance broke a DK rule. The real character creator offers only valid choices, so this
  should not hit players.

### Prediction

- **Character creation shows Death Knight and Monk** (fairly sure): the screen lists what the client's class data
  and the server's class list allow, and both now include them. The class icons and DK appearance options ship.
- **Both can be created and played** (fairly sure, after the server-side run above). The Death Knight starts at
  level 8 in Northshire, with no weapon (its TDB start item isn't in Forever).
- **The Runic Power bar shows** (likely); **no rune display** (sure: Blizzard's rune frame doesn't load on Forever);
  the runes work on the server and `/el1 runes` shows them.
- **DK spells are in the spellbook under "Death Knight" and can be cast** (likely). They do damage and use runes and
  Runic Power, but most have **no animation** (their visuals aren't in Forever) and probably **no tooltip text**.
- **Talent frame with the copied tree:** a coin flip. If it opens, a tree the client never shipped works, and era
  trees are only data.
- **Overall: one client looks possible for the Death Knight and the Classic → WotLK ruleset.** The cost lies
  elsewhere:
  - the class data has to be sent;
  - the rune and class-power frames have to be our own addon;
  - WotLK's rune types are core work;
  - the Death Knight start zone (map 609) needs adding like map 530.
- **The retail ruleset is a question of volume, not ability.** Forever lacks about 384,000 spells and their rows (over
  a million). That is far too much to send as hotfixes at every login.
  - **Recommended next step if Test 1 passes:** ship superset DB2 files (Forever's rows plus the missing retail
    rows) through our patched build, as gate 2 does for terrain.
  - Per-realm hotfixes would then only fix the spells whose numbers differ between rulesets.

### Morning checklist (Mac mini, about 20 minutes)

Before starting: if Battle.net has updated the game, the server refuses it. The newest Forever builds on wago.tools
are 70840 and 70862, ours is 70790. The `test1` report prints the build; if it isn't 70790, stop there.

1. Get the Test 1 branch and install the addon into the gate2 test copy (the real install stays untouched):
   ```sh
   git -C ~/everlake fetch
   git -C ~/everlake checkout claude/test1-classes
   ~/everlake/client/macos/everlake-client.sh test1-addon gate2
   ```
   If the gate2 copy doesn't start (it needs the server's CDN on port 80), use `test1-addon` and `play` without
   `gate2`.
2. `~/everlake/client/macos/everlake-client.sh play TEST@TEST.COM gate2`
3. **Character creation:** Create New Character, pick Human. **Screenshot** (Cmd+Shift+3 is fine) of the class row.
   - Are Death Knight and Monk there? Can you click them?
   - Pick Death Knight. In Customize, do the eye colours include a glowing one?
   - Name it, Create. Does it appear in the list as a level 8 Death Knight?
4. **Enter the world** with the Death Knight. The addon prints a line in chat. Screenshot of the player frame.
   - Which bar shows under the portrait?
   - Type `/el1 runes`.
5. **Weapon and spells:** type `.additem 12282` and `.learn 197`, then equip the Worn Battleaxe.
   - Open the spellbook (P). Screenshot.
   - Is there a "Death Knight" tab with Death Coil and Death Strike?
   - Both cost Runic Power and nothing at level 8 makes it, so type `.modify runicpower 100` first. Does the
     bar fill?
   - Put both on the bar and use them on a wolf.
   - Did damage happen? Were there animations? Tooltip text?
6. **Level up:** type `.levelup 7`. You're now level 15.
   - Did "You have learned" lines come for Obliterate, Howling Blast and Anti-Magic Shell?
   - Cast Obliterate (it uses runes) and Howling Blast.
7. **Talents:** press N, or type `/el1 talents`. Screenshot.
   - Does a tree show (the Warrior's talents, copied), with points to spend?
   - Spend 2 points, log out to the character list, log back in. Are the points still spent?
8. Type `/el1`, then log out completely.
9. **Monk:** create a Human Monk, enter the world, type `/el1`. Screenshot of the player frame. Log out.
10. `~/everlake/client/macos/everlake-client.sh test1 gate2` sends the report and screenshots to the server.
11. Afterwards: `git -C ~/everlake checkout claude/gate2` to go back to the gate 2 branch.

**Passes** when steps 3 to 5 work: Death Knight in the creator, created, in the world, a DK spell cast that does
damage. Missing animations, tooltip text or rune display don't fail it (expected, and fixable). The talent step is a
separate result.

**Fails** when the creator doesn't offer the class, creation is refused, the client disconnects or crashes on
entering the world, or the spells can't be cast at all. Then the report's hotfix lines (any non-VALID row) and Lua
errors show where.

### In game (2026-11-07 morning, Mac mini)

- **The creator offers Death Knight**, and a Human Death Knight (Aevise) was created at level 8 and entered the world.
  The client's class list has 11 classes, Monk included. The talent API sees the copied tree (53 nodes); the frame
  itself isn't checked yet. The 6 runes exist in the client API.
- **Lua errors at every login:** `PlayerFrame.lua:688` indexes the missing `RuneFrame` (the mainline player frame
  expects it for a DK), and the micro menu calls a missing `CanShowEncounterJournal` function.
- Fixed on the way, each a kit or world change (commits on `claude/test1-classes`):
  - **"You cannot speak that language":** Forever's SkillRaceClassInfo gives languages, racials, riding, cloth and
    survival to ClassMask 1503 (the nine vanilla classes) and Defense/Unarmed to 1535. The kit sends those 52 rows
    with ClassMask 2047.
  - **Weapons and armor:** Forever's weapon and armor rows list vanilla classes only, so `.learn 197` gave the spell
    without the skill and the axe couldn't be equipped. The kit adds race-wide rows for the WotLK Death Knight's and
    the Monk's weapons and armor, and adds both classes to the proficiency spells.
  - **4,830 health at level 8:** TDB's `player_classlevelstats` for classes 6 and 10 are retail-scale. The Death
    Knight now takes the Warrior's rows and the Monk the Rogue's
    (`sql/everlake/2026_11_07_04_world_test1_class_stats.sql`).
  - **Death Knight spells missing from the spellbook:** the server taught them (`.learn 47541` said "already known")
    but the client dropped them: no "You have learned" line, `IsPlayerSpell` false, while Fireball learned on the
    same character showed at once. The cause was the `Spell` table (name subtext, description, aura text): Forever
    has a row for each of its spells, the kit sent none, and the client keeps no spell without one. The core has
    no hotfix table for it, so the kit now writes those rows to `hotfix_blob` as the client's record bytes. **After
    that, Death Coil is in the spellbook.** Any spell sent to the client needs its `Spell` row.
- The class kit moved from pushes 9540000-9540004 to 9540020-9540024 (the old pushes are deleted), so the client
  fetches every row again. **After that, the skill tab lists the new weapon and armor skills.** Lesson: rows changed
  inside a push the client already has don't reach it; give changed rows a new push.
- Not a bug: no XP in Northshire. The Death Knight starts at level 8, where anything level 3 or below is grey.
- Still open:
  - Health doesn't regenerate out of combat: `Player::OCTRegenHPPerSpirit` has no case for classes 6 and 10 (core).
  - Casting, damage, animations and tooltip text, the talent frame, and the Monk aren't checked yet.

### Follow-ups found on the way

- The bot factory's Death Knight appearance roll breaks the DK customization rules (bots can't be DKs yet).
- Health and mana regeneration and the other vanilla class formulas in `StatSystem.cpp` need Death Knight and Monk
  cases (core).
- A Death Knight rune display (our own addon), and a guard for the `RuneFrame` error in the mainline player frame.
- WotLK rune types (Blood, Frost, Unholy, Death) for the Classic → WotLK ruleset: core work.
- Acherus (map 609) for the DK start, like map 530.
- The client build moves on (70840 and 70862 are out); the server accepts only 70790.
