# Game modes next to the rulesets (future idea)

Status: research only, 2026-11-07. Nothing built, nothing tested in game. Not a gate.

The question: can Everlake offer extra **game modes** the way retail does (Plunderstorm, Remix), on the Forever
client 1.60.1.70790 and the TrinityCore `forever` fork? Short answer: **yes, and the cheapest way is the picker the
Forever client already has.** The Forever client still carries retail's whole game-mode system, but hides it.

## 1. How retail does it

**The modes.**
- **Plunderstorm** ran 19 March 2024 (patch 10.2.6) and again 14 January to 25 February 2025. It is a 60-player
  battle royale on Plunderstorm-only realms inside the normal retail client. You pick it at character select, or
  queue from the PvP tab. You play a new, classless character, not your own.
  ([warcraft.wiki.gg](https://warcraft.wiki.gg/wiki/Plunderstorm))
- **WoW Remix (Timerunning)**: Mists of Pandaria (10.2.7, May 2024), Legion (October 2025), Wrath of the Lich King
  (planned). These are not separate realms. Timerunner characters are made at normal character create on normal
  realms, carry a season flag, are locked to the event zones, can't group with normal characters, and turn into
  normal characters when the event ends. ([warcraft.wiki.gg](https://warcraft.wiki.gg/wiki/WoW_Remix))
- **WoWHack**: a third mode in the client's enum (`Enum.GameMode`: 1 Standard, 2 Plunderstorm, 3 WoWHack). It has
  its own UI folders and store front, but nothing public says what it is.
  ([Enum.GameMode](https://warcraft.wiki.gg/wiki/Enum.GameMode))

**Client data (DB2).**
- `GameMode`: one row per mode. Retail 12.1.5 has two: `8 standard` and `9 ps` (Plunderstorm, season 5, a logo,
  promo string `LIMITED_TIME_EVENT`). A class mask column limits classes: 8191 for standard, 8192 for Plunderstorm,
  which is class 14 "Adventurer". ([wago.tools](https://wago.tools/db2/GameMode?build=12.1.5.70783))
- `Map`: Plunderstorm needs its own map and a "Plunderstorm" game type.
- `Cfg_GameRules`, `Cfg_Configs`, `Cfg_Categories`: realm rules, the same in retail and Forever.

**Glue UI** ([Gethe/wow-ui-source](https://github.com/Gethe/wow-ui-source/tree/live), 12.1.5):
- `Blizzard_GameModeSelect` draws the mode buttons; `Blizzard_CharacterSelectNavBar` puts a "Mode" button on
  character select that opens it.
- The Lua API is `C_GameRules`: `GetNumDisplayedGameModes`, `GetDisplayedGameModeRecordIDAtIndex`,
  `IsGameModeEnabled`, `GetActiveGameMode`, `IsPlunderstorm`, and `AutoConnectToGameModeRealm(gameModeRecordID)`.
- Picking a mode calls `AutoConnectToGameModeRealm`: **a mode is a set of realms.** The client reconnects to a
  realm of that mode and reloads the UI with that mode's addons.
- Plunderstorm's own UI (`Blizzard_Plunderstorm`, `Blizzard_PlunderstormPrematchUI`, the `WoWLabs` folders) only
  loads when the game type is `plunderstorm` (`## AllowLoadGameType: plunderstorm` in the `.toc`).
- In-game queueing goes through `C_LobbyMatchmakerInfo` (EnterQueue, RespondToQueuePop).

**Packets** ([TrinityCore master](https://github.com/TrinityCore/TrinityCore/blob/master/src/server/game/Server/Packets/SystemPackets.h)):
- `SMSG_FEATURE_SYSTEM_STATUS_GLUE_SCREEN` carries `AvailableGameModeIDs` (GameMode rows the selector shows),
  `DisabledGameModes` and `GameRules` (rule 13 is `GameMode`). Upstream always sends only `8` (standard).
- The same packet carries `ActiveTimerunningSeasonID`; each character in the enum carries `TimerunningSeasonID`;
  character create sends one.
- `SMSG_LOGOUT_COMPLETE` has an optional `SwitchGameMode` block (current and new mode, map, customizations) for
  switching modes from in game.

**Keeping characters apart.** Plunderstorm: separate realms, so separate character lists. Remix: same realm, a
season ID on the character, and server rules (zones, grouping, mail) keep them apart.

## 2. What the Forever client carries

Checked on [wago.tools](https://wago.tools/db2/GameMode?build=1.60.1.70790), and in the client's own glue files read
from Blizzard's CDN with `tools/tact/tact.py --product wowf` (build 1.60.1.70790, not committed).

**The ruleset picker is a cousin of the mode system, and both use the same season numbers.**

| Table | Forever 1.60.1.70790 | Retail 12.1.5 |
|---|---|---|
| `GameMode` | 6 rows, **same layout as retail 12.x** | 2 rows |
| `AvailableSuperDistrict` (picker cards) | PvP, Normal, Roleplay, Hardcore, Roleplay PvP, CN Beta Event | none (appears on the 12.1.7 PTR) |
| `Cfg_SuperDistrict` (card to season) | 1→136, 2→137, 3→138, 4→140, 5→13, 7→156, 14→136, 15→139 | none (12.1.7 PTR) |
| `SuperDistrictSet*` | which cards a region shows | none (12.1.7 PTR) |
| `ChrClasses` | 9 classes | 15, incl. 14 Adventurer |
| `Map` | 73 maps | 1187 maps |

Forever's `GameMode` rows: `4 wfhc` (Hardcore, season 140, own logo), `8 standard`, and `14`-`18 wf` for seasons
136-139. Those seasons are the same content sets the picker cards point at. So each ruleset card already has a
matching game mode row. The class mask on the `wf` rows is 1503 (the nine Forever classes).

The cards' text, icon, order and background art all come from `AvailableSuperDistrict`, so a new card is data, not
code.

**Glue UI.** Forever ships retail's mode code almost whole:
- `Blizzard_GameModeSelect` (same Lua as retail), `Blizzard_Plunderstorm`, `Blizzard_PlunderstormPrematchUI`,
  `Blizzard_PlunderstormBasics`, the `WoWLabs` glue files, `Blizzard_TimerunningCharacterCreate`.
- `C_GameRules` in Forever is retail's list **plus** Forever extras: `GetForeverExperiencePreset` /
  `SetForeverExperiencePreset*` (enum Classic 0 / Enhanced 1), SD/HD model toggles, `IsHardcoreActive`,
  `IsSelfFoundAllowed`.
- But Forever's own nav bar template (`camelot/CharacterSelectNavTemplates.xml`) sets
  `gameModeButtonAvailable = false` and `realmsButtonAvailable = false`, and turns on
  `superDistrictsButtonAvailable`. **The Mode button is hidden; the ruleset picker takes its place.**
- Forever's character create (`camelot/Blizzard_CharacterCreate.lua`) still has the Timerunning branch.
  Timerunning seasons in the client: 1 Pandaria, 2 Legion.

**What Forever lacks for a real Plunderstorm:** class 14, the Plunderstorm map, its spells and items. All are
retail content, so they would come over the gate 2 route (custom files plus hotfix rows), like Sunstrider Isle did.

## 3. What the server needs

Read at the pinned fork commit
[`6ac7bece`](https://github.com/advocaite/TrinityCore/tree/6ac7bece2e7a6b3f75599f20d62235985ea78a7d) and
TrinityCore master `bb3d6fd5`.

**Already in the `forever` fork:**
- Realms carry a season: `realmlist.contentSetId`, sent as `cfgContentSetID` plus `superDistrictID` in the realm
  JSON (`src/server/shared/Realm/RealmList.cpp`).
- bnetserver answers `Command_SuperDistrictListRequest_v1` (which cards can log in) and
  `Command_LastCharPlayedRequest_v1` with `Param_ContentSetIDFilter` (the realm for a picked card)
  (`src/server/bnetserver/Services/GameUtilitiesService.cpp`).
- Per-realm game rules, e.g. `Classic.Hardcore` turns on rule 10 (`World.cpp`).
- Packet fields for `AvailableGameModeIDs`, `DisabledGameModes`, `ActiveTimerunningSeasonID` and the character's
  `TimerunningSeasonID`.

**Hard-coded today, would need changing:**
- The card-to-season map is a C++ `switch` with four entries (136 PvP, 137 Normal, 138 RP, 140 Hardcore), and the
  card list loops over IDs 1-5 only (`src/server/shared/Realm/Realm.cpp`, `RealmList.cpp`). A new card needs this
  made data-driven (a small change: a table or config list).
- `AvailableGameModeIDs` is always `{8}`.
- Character create refuses any `TimerunningSeasonID` (`CHAR_CREATE_TIMERUNNING`).

**Would have to be written, per mode:**
- **Ruleset-style mode:** a realm (worldserver) with its own config and rules. That's all the core work.
- **Remix-style mode:** accept and store the season on create, send it in the character enum, then the rules:
  zone lock, no grouping or mail with normal characters, faster XP and gear, and the end-of-event conversion.
- **Plunderstorm-style battle royale:** none of it exists anywhere in TrinityCore. Lobby and matchmaking
  (`C_LobbyMatchmakerInfo` packets), match instances, the shrinking storm, spell pickups, a classless class, and the
  `plunderstorm` game type switch. This is a whole game.

## 4. Options, ranked

### 1st. A: modes as more ruleset cards (recommended)

A mode is one more card in Forever's picker, pointing at its own realm with its own rules. This is exactly how
Forever already splits PvP, Normal, RP and Hardcore, and how the Everlake plan already adds Classic → WotLK and
retail.

- **Costs:** three DB2 rows per card (`AvailableSuperDistrict`, `Cfg_SuperDistrict`, `SuperDistrictSetXAvailableSD`),
  delivered by hotfix or by the gate 2 local-storage route; making the fork's card list data-driven; one more
  worldserver per mode. Characters stay apart because realms do.
- **Can't do:** no mode-specific glue UI beyond the card's text, icon and background. No queueing into a mode from
  in game. A mode that is a match (battle royale) still needs C's server work inside that realm.
- **Smallest experiment:** see the end of this page.

### 2nd. D: Remix-style season on a realm

A Timerunning season flag on characters of a normal or event realm, using the Timerunning create UI the client
already ships.

- **Costs:** server sends `ActiveTimerunningSeasonID`; accept and store the season on create; the event rules
  (zone lock, grouping, mail); the end-of-event conversion. The client's season art and strings exist only for
  Pandaria (1) and Legion (2): reuse those IDs, or override the Lua.
- **Can't do:** our own season name and art without a client UI change.
- **Smallest experiment:** set `ActiveTimerunningSeasonID = 2` in the glue status packet on a test build and open
  character create. Passes if the Timerunning choice appears. If the server is then let through, the new character
  shows the hourglass in the list.

### 3rd. C: a mode as an instance inside a normal realm

A battle-royale or event scenario run as an instance map with its own server rules, entered by NPC, command or
queue.

- **Costs:** all server work (instance per match, storm ring as an area aura, loot spells, scoring). No client work
  if it uses a map Forever already has (Arathi Basin 529, Alterac Valley 30, a cut of an open-world zone).
- **Can't do:** Plunderstorm's own UI (loadout bar, prematch, spectating) only loads in the `plunderstorm` game
  type, so the mode uses the normal UI. Retail itself never did Plunderstorm this way: it used its own realms.
- **Smallest experiment:** server-only. A GM command puts two test characters into a fresh instance of map 529 with
  a script that shrinks a damage ring every 30 seconds. Passes if two matches run side by side without mixing.

### 4th. B: turn on retail's Mode selector

Show the hidden Mode button and switch modes with `AutoConnectToGameModeRealm`, as retail does.

- **Costs:** a changed Forever glue file (the nav bar template) through the gate 2 route, never tried for Lua or XML;
  `GameMode` rows plus `AvailableGameModeIDs` from the server; finding out which bnet request
  `AutoConnectToGameModeRealm` sends and answering it. Retail's own Plunderstorm content on top.
- **Can't do (yet):** it is a second picker next to the one Forever already has, so it only pays off for a real
  retail-style match mode with its own game type and UI.
- **Smallest experiment:** two steps. First, with no client change, send `AvailableGameModeIDs = {8, 14}` and check
  whether anything reacts (it shouldn't: the button is hidden). Then write a nav bar template with
  `gameModeButtonAvailable = true` into local storage and see whether the Mode button appears, and what bnetserver
  logs (`session.rpc` at debug) when a second mode is clicked.

## Recommended first experiment (option A, no server code)

**Does the picker show a card we wrote, and does it lead to our realm?** Run on the Mac mini later, as one
`everlake-client.sh` subcommand.

1. Write a new `DisplayName`, `Description` and icon on the **Roleplay** card (`AvailableSuperDistrict` ID 4,
   season 138), e.g. "Remix (test)". Deliver it by hotfix first (a raw hotfix row, if the fork can push one for this table); if the picker doesn't pick it up (it shows before
   world login), write the changed DB2 into local storage the way gate 2 did.
2. Set the test realm's `realmlist.contentSetId` to 138 and restart bnetserver.
3. Log in, open the picker.

**Passes when:** the picker shows "Remix (test)" with our icon and text, picking it lists our realm, and a character
made there logs in. Picking Normal no longer lands on that realm, which shows the realm really follows the card.

**If it passes:** make the fork's card list data-driven, add a sixth card with its own season ID, and a mode is
"one card, one realm, one rules config". **If it fails:** the picker reads only shipped data before login, and
every mode change needs the local-storage route.

## Sources

- [warcraft.wiki.gg: Plunderstorm](https://warcraft.wiki.gg/wiki/Plunderstorm),
  [WoW Remix](https://warcraft.wiki.gg/wiki/WoW_Remix),
  [Enum.GameMode](https://warcraft.wiki.gg/wiki/Enum.GameMode),
  [C_GameRules.AutoConnectToGameModeRealm](https://warcraft.wiki.gg/wiki/API_C_GameRules.AutoConnectToGameModeRealm),
  [patch 10.2.6 API changes](https://warcraft.wiki.gg/wiki/Patch_10.2.6/API_changes)
- wago.tools DB2 for 1.60.1.70790 and 12.1.5.70783:
  [GameMode](https://wago.tools/db2/GameMode?build=1.60.1.70790),
  [AvailableSuperDistrict](https://wago.tools/db2/AvailableSuperDistrict?build=1.60.1.70790),
  [Cfg_SuperDistrict](https://wago.tools/db2/Cfg_SuperDistrict?build=1.60.1.70790),
  [ChrClasses](https://wago.tools/db2/ChrClasses?build=12.1.5.70783),
  [Map](https://wago.tools/db2/Map?build=1.60.1.70790)
- [wowdev/WoWDBDefs](https://github.com/wowdev/WoWDBDefs): `GameMode.dbd` shows one layout for 1.60.1 and 12.x;
  the `*SuperDistrict*` tables exist only in 1.60.1 and the 12.1.7 PTR.
- [Gethe/wow-ui-source](https://github.com/Gethe/wow-ui-source/tree/live) at 12.1.5 (70783): `Blizzard_GameModeSelect`,
  `GameRulesDocumentation.lua`, `LobbyMatchmakerInfoDocumentation.lua`, `Blizzard_Plunderstorm*`.
- Forever glue files by FileDataID (read, not committed): 6796716/6796722 `Blizzard_GameModeSelect`, 7373118
  `camelot/CharacterSelectNavTemplates.xml`, 5096353 `GameRulesDocumentation.lua`, 8209459
  `camelot/Blizzard_CharacterCreate.lua`, 5756312 `Blizzard_TimerunningCharacterCreate.toc`.
- [advocaite/TrinityCore `forever` @ 6ac7bece](https://github.com/advocaite/TrinityCore/tree/6ac7bece2e7a6b3f75599f20d62235985ea78a7d)
  and [TrinityCore master](https://github.com/TrinityCore/TrinityCore): `SystemPackets.h`, `CharacterPackets.h`,
  `AuthHandler.cpp`, `RealmList.cpp`, `GameUtilitiesService.cpp`, `DBCEnums.h`.
