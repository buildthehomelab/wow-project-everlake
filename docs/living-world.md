# A world that feels alive (gate 3)

The goal is not a bot count. It is that a real player never feels alone, and that every bot on their screen looks
and acts like another player. It can be an illusion, as long as it holds up when the player looks closer.

One machine can't run thousands of bots on every realm. So the bots go where real players are, and the rest of the
population sleeps cheaply until someone comes near. This gate finds the "magic number" of bots for each kind of
place, proves the illusion holds, and measures what it costs.

Nothing in this plan is built or run yet, except the first 100-bot test below.

## What PlayerbotV2 already does

Read from `playerbot.conf.dist` on 2026-11-06. Most of the illusion is already there, switched by settings:

| Setting | What it does |
|---|---|
| `World.BotsPerPlayer`, `ActivityRadius` | A bubble of bots around each real player |
| `World.CityBots`, `ZoneBots`, `StartZoneBots` | Bubble size by kind of place (capital or town, levelling zone, start zone) |
| `World.WakeRadius`, `SeedRoster`, `PoolMax` | Lasting residents: a bot nobody is near logs out and sleeps where it stood, and logs back in there when a player comes near |
| `World.Moving.*` | A rider gets bots placed on the road ahead and dropped behind |
| `World.NaturalMoves` | Bots walk in from out of sight and walk away to log out, instead of popping in and out |
| `World.ZoneGraceSec` | A quick dungeon run or hearth doesn't throw away the crowd |
| `World.IdleSec`, `IdleSwap` | A bot standing around for no reason is given something to do |
| `World.DayRhythm`, `TownLife` | Fewer bots at night; bots in town rest at inns, train, duel, sit at campfires |
| `World.ZoneMix` | Contested zones hold a share of the other faction |
| `Behavior.SocialEmotes` | Bots cheer a level-up, bow after a boss kill, and wave back when a player says hi or hello nearby |
| `Behavior.PoliteWorldBots` | Trades, invites and duels from players get a human answer |
| `Chatter.*` | Channel replies, greetings, questions, conversation, with rate limits |
| Activity tiers | Bots far from players run cheaper AI |
| `World.RssBudgetMb` | Stops adding bots over a memory budget |

The config notes already contain one magic number: in a start zone, 50 bots left a new character nothing to
kill, while 8 looked empty.

## What we add

1. **Bots answer emotes, not only words.** `/wave` gets a wave back, `/bow` a bow, `/cheer` a cheer, `/dance`
   sometimes a dance, `/rude` a rude or a turned back, `/hug` or `/kiss` a shy or a laugh. The bot turns to face
   the player first. Chance-based with a cooldown so it doesn't feel mechanical, and only within about 15 yards.
2. **No bot on screen is ever idle without a visible reason.** In view of a real player, a bot is always fighting,
   looting, gathering, travelling somewhere, eating or drinking, at a vendor, or resting at an inn. The idle
   watch gets a much shorter limit while a player can see the bot.
3. **Sleeping bots move on.** When a resident wakes after a long sleep, it has gained levels and gear in line with
   how long it slept, and may have moved on to a zone for its new level. Players meet the same characters again,
   further along, as they would on a real server.
4. **One bot budget across all realms.** Each game mode is its own realm, and most realms are empty most of the
   time. A small coordinator sets each realm's bot budget from where real players are right now.
5. **No bot ever falls out of the sky where a player can see it.** Nothing breaks the illusion faster. A bot is
   only ever placed on a point the navigation mesh says is walkable ground, with the ground height checked
   there, and only out of sight (as `NaturalMoves` already prefers). A bot is never teleported in view. A bot
   that ends up falling or under the ground is moved away while nobody can see it. The server counts every
   bot fall or teleport within sight of a real player, and that count must stay at zero.
6. **Trade chat deals that go through.** PlayerbotV2 already has bots post items for sale in Trade, and a player's
   WTB gets a whisper from a bot that has the item, then "buy 1" and a face-to-face trade. Its mail code can
   already send an item cash on delivery. We add:
   - Replying to or whispering a bot's WTS post gets a price, a little haggling within a set margin, and then
     either a trade if the bot is close or a **COD mail** if it isn't ("sent it COD, check your mailbox").
   - It works with sleeping bots too: the mail is sent from the bot's saved inventory without logging it in.
   - The bot really owns what it sells (from its own farming, professions or loot), so the trade post, the
     whisper and the mail always agree.
   - It goes both ways: a player's WTS in Trade can get a bot offering to buy, paying by COD on the player's mail.
   - Haggling works both ways too, with one price model shared with the AH bot: a bot knows what an item
     usually sells for, opens a little above (selling) or below (buying), meets the player partway, and walks
     away from a lowball. Each bot has its own temper, so some haggle hard and some take the first offer.
7. **A liveliness score per player session,** written to the logs for the command centre: distinct bots seen per
   10 minutes, emotes and chat lines aimed at the player, group invites, minutes spent with no other character in
   sight.

## First numbers (2026-11-06)

100 world bots around one player in Elwynn Forest, 30 minutes, on an Intel i7-9750H Mac with Docker given 12 CPUs:

- worldserver about 1.0 to 1.3 cores, about 0.55 MB per bot
- update time median 2 ms, p90 125 ms, max 557 ms during the 100-bot login burst
- bots fought and looted, but **questing was broken on vanilla data**: about 1,100 `quest_truly_stuck` per minute

## Tests

The Mac mini drives a real client through scripted routes; the server logs what the player experienced.

1. **Questing works first.** `quest_truly_stuck` falls from about 1,100 a minute to under 50 on the same 30-minute
   Elwynn run. Nothing else here is meaningful until bots can quest.
2. **Cost per bot by AI level.** Bots near a player, a zone away and far away, each measured separately: CPU per
   bot and update time. This sets how many active bots one machine holds.
3. **The magic number.** For each kind of place (start zone, levelling zone, quest hub, road, town, capital), run
   the same mini route at several bubble sizes. Record bots seen, mobs left to kill, competition at quest mobs,
   and a screenshot at fixed points. Pick one number per kind of place from the numbers and screenshots.
4. **The illusion holds up close.**
   - The mini waves at 20 bots one by one: at least 15 wave back within 3 seconds, facing the player.
   - Over a 30-minute route, no bot in view stands still longer than the in-view idle limit without a reason.
   - Screenshots show no bots appearing or vanishing in view.
   - **Zero bots falling or teleporting in view** over every run (server count), including rides through hills,
     cliffs, bridges and caves where ground height is easy to get wrong.
   - The mini whispers a bot about its Trade post from another zone: it gets a price, accepts, and the item
     arrives as a COD mail that takes the agreed money.
5. **Residents come back.** The player leaves a zone, its bots sleep. The player returns an hour later and meets
   the same names in the same places. After a longer simulated sleep, they come back higher level.
6. **Scale.** 500, 1,000 and 2,500 active bots in total, with real players (or stand-ins) spread over several
   zones. Update time p90 stays under 100 ms.

## Passes when

- Questing works (test 1).
- Each kind of place has a chosen bot number that looks busy without emptying the mobs (test 3).
- The close-up checks pass (test 4) and residents come back (test 5).
- The cost per bot shows how many players one machine can carry at those numbers (tests 2 and 6).
