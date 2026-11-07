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

Nothing here is built or run yet.

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
