#!/usr/bin/env python3
"""Slice 5 of Everlake's world import (docs/forever-import.md): new NPCs and objects. Templates Forever uses that the
world lacks, with their spawns.

    import_slice5.py --maps DIR               Everlake's extracted maps folder (the worldserver's data/maps)
    import_slice5.py --out DIR                write somewhere else (a clone of wow-everlake-world-data)
    import_slice5.py --date 2026_11_08        the update files' date (default: today, UTC)

Works on the gaps gap_report.py lists (missing_npcs, objects_missing), running the report itself (--gaps FILE reuses
one). Writes only files:
- sql/world/YYYY_MM_DD_NN_world_everlake_import_slice5.sql: the templates, their models, levels, loot and stock, and
  their spawns;
- slices/slice5/manifest.json, review.md and held-back.md.

The user's decisions (2026-11-08):
1. Only NPCs and objects that also get a spawn, by slice 4's rule: a forever-db point a live Forever sighting (EG Link)
   confirms within 40 yards, with a height (slice 4's Heights). The rest (mostly beta, Classic or event data) are held
   back; slice 6 brings in the NPCs its quests need. A unique NPC (elite, rare or boss, titled, offering a service, or
   with every point within 60 yards of the others) with several points goes to the review list: it may be one NPC
   wandering or on a patrol (slice 4's rule 4, widened after review).
2. An NPC's faction: no public source records it. It is the commonest faction of the fork's NPCs spawned within 60 yards
   whose reaction to a player of the side EG Link's players were (Horde or Alliance) is what they saw (attacks on sight
   or not, both as the player sees it and as the NPC sees the player), preferring ones whose name starts with the same word, then an exact reaction (neutral, friendly). An NPC no
   such fork NPC stands near is held back. The fork NPC of that faction nearest the point (of the same creature type
   where there is one) lends the values no source has: walk and run speed, attack times and variance, and whether it
   is immune to players and NPCs (unit_flags 0x100, 0x200). Each row's note names it.
3. Services: the flags EG Link players saw (merchant, quest giver, auctioneer, flight master, banker, innkeeper, stable
   master, repairs), and the stock EG Link recorded, by slice 3's rules (import_slice3.vendors). Gossip only when
   nothing else (a vendor with the gossip flag and no gossip menu opens a greeting, not its window). Training needs a
   trainer list and a gossip option to open it (hand work): the trainer flag is left off and the NPC goes on the
   review list.

Template values (EG Link's creature details: the client's own query data of a live build, or of a beta build when no
live one recorded it, said so): name, title, type, family, classification, class, models, health and power
multipliers, type flags, CreatureDifficultyID, movement, kill credits (proxy creatures), mouse cursor, health scaling
expansion. A model must be in Forever's client (wago.tools' CreatureDisplayInfo of the pinned build). Levels go in the
fork's creature_classic_level (as the fork does for its own Forever NPCs): EG Link's live levels, else forever-db's;
damage and armour modifiers 1, unit_flags2 2048 (regenerates power), like the fork's own Forever NPCs. No equipment,
script or loot yet: loot comes with a slice 2 run once the template is in.

Objects: EG Link's object details are the whole template (type, model, size, data); quest items go in
gameobject_questitem. A chest's loot (its Data1) comes from EG Link's openings when the fork has none: a quest item at
100% for players on the quest (as the fork's quest chests), any other item at its recorded share once the chest was
opened 50 times (live and beta windows summed); fewer goes on the review list. Only types that work without a script
or link no source has: quest givers (2), chests (3), generic (5), spell focus (8).

Spawns as slice 4 for new NPCs (respawn and wandering as the fork's commonest for the classification on the map; an
object's as the fork's commonest for its type). Guids continue after the highest an earlier slice's manifest uses.

Every row goes in only while the template is ours (everlake_import_rows names it under this file, and it still has
VerifiedBuild 0 as written; the build the details came from is in the note), and never again once added: if the fork
adds the NPC or object first, or takes it over with its own sniffed template, nothing of ours goes in next to it.
"""
import argparse
import collections
import datetime
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import candidates  # noqa: E402
import gap_report  # noqa: E402
import import_slice2  # noqa: E402
import import_slice3  # noqa: E402
import import_slice4 as s4  # noqa: E402
import import_sql as isql  # noqa: E402
import terrain  # noqa: E402
from load_sources import SOURCES, connect  # noqa: E402

SLICE = "slice5"
F = candidates.F
OUT = os.path.join(HERE, "world-data")
CATEGORIES = ("missing_npcs", "objects_missing")
LIVE = "wowf"
FACTION_YARDS = 60
MIN_OPENS = 50
GUID_BASE = s4.GUID_BASE
OPEN_SPELL = "|spell:22810"          # "Opening": what EG Link files a chest's loot under
OBJECT_TYPES = {2: "quest giver", 3: "chest", 5: "generic", 8: "spell focus"}
# EG Link's interactions -> npcflag (TrinityCore NPCFlags)
SERVICE = {"QuestGiver": 2, "Merchant": 128, "Auctioneer": 2097152, "TaxiNode": 8192, "Banker": 131072,
           "Innkeeper": 65536, "StableMaster": 4194304}
GOSSIP, REPAIR, TRAINER, VENDOR = 1, 4096, 16, 128
CRITTER = 8                          # creature type
HOSTILE_BY_DEFAULT = 0x2000          # FACTION_TEMPLATE_FLAG_HOSTILE_BY_DEFAULT
UNIT_CLASSES = {1, 2, 4, 8}
CLUSTER_YARDS = 60                   # points all this close may be one NPC wandering
IMMUNE = 0x100 | 0x200              # UNIT_FLAG_IMMUNE_TO_PC | UNIT_FLAG_IMMUNE_TO_NPC
PLAYER_TEMPLATE = {"Horde": (2, 2), "Alliance": (1, 1)}        # side -> (faction template, race) of a player
RANKS = ((-6000, 1), (-3000, 2), (0, 3), (3000, 4), (9000, 5), (21000, 6), (42000, 7))   # rep below -> reaction code

CT_COLUMNS = ["entry", "KillCredit1", "KillCredit2", "name", "femaleName", "subname", "TitleAlt", "IconName", "RequiredExpansion",
              "VignetteID", "faction", "npcflag", "speed_walk", "speed_run", "scale", "Classification", "dmgschool",
              "BaseAttackTime", "RangeAttackTime", "BaseVariance", "RangeVariance", "unit_class", "unit_flags", "unit_flags2",
              "unit_flags3", "family", "trainer_class", "type", "VehicleId", "AIName", "MovementType", "ExperienceModifier",
              "RacialLeader", "movementId", "WidgetSetID", "WidgetSetUnitConditionID", "RegenHealth", "CreatureImmunitiesId",
              "flags_extra", "ScriptName", "StringId", "VerifiedBuild"]
CTD_COLUMNS = ["Entry", "DifficultyID", "LevelScalingDeltaMin", "LevelScalingDeltaMax", "ContentTuningID", "HealthScalingExpansion",
               "HealthModifier", "ManaModifier", "ArmorModifier", "DamageModifier", "CreatureDifficultyID", "TypeFlags",
               "TypeFlags2", "TypeFlags3", "LootID", "PickPocketLootID", "SkinLootID", "GoldMin", "GoldMax", "StaticFlags1",
               "StaticFlags2", "StaticFlags3", "StaticFlags4", "StaticFlags5", "StaticFlags6", "StaticFlags7", "StaticFlags8",
               "VerifiedBuild"]
CTM_COLUMNS = ["CreatureID", "Idx", "CreatureDisplayID", "DisplayScale", "Probability", "VerifiedBuild"]
CCL_COLUMNS = ["entry", "level_min", "level_max"]
GOT_COLUMNS = ["entry", "type", "displayId", "name", "IconName", "castBarCaption", "unk1", "size"] + \
              [f"Data{i}" for i in range(35)] + ["ContentTuningId", "RequiredLevel", "AIName", "ScriptName", "StringId", "VerifiedBuild"]
GOQ_COLUMNS = ["GameObjectEntry", "Idx", "ItemId", "VerifiedBuild"]
GLT_COLUMNS = ["Entry", "ItemType", "Item", "Chance", "QuestRequired", "LootMode", "GroupId", "MinCount", "MaxCount", "Comment"]
TABLES = {  # table -> (columns, key, what the rows hang on: (column, template table))
    "creature_template": (CT_COLUMNS, ["entry"], None),
    "creature_template_difficulty": (CTD_COLUMNS, ["Entry", "DifficultyID"], ("Entry", "creature_template")),
    "creature_template_model": (CTM_COLUMNS, ["CreatureID", "Idx"], ("CreatureID", "creature_template")),
    "creature_classic_level": (CCL_COLUMNS, ["entry"], ("entry", "creature_template")),
    "gameobject_template": (GOT_COLUMNS, ["entry"], None),
    "gameobject_questitem": (GOQ_COLUMNS, ["GameObjectEntry", "Idx"], ("GameObjectEntry", "gameobject_template")),
    "creature": (s4.CREATURE_COLUMNS, ["guid"], ("id", "creature_template")),
    "gameobject": (s4.OBJECT_COLUMNS, ["guid"], ("id", "gameobject_template")),
    "npc_vendor": (import_slice3.NV_COLUMNS, import_slice3.NV_KEY, ("entry", "creature_template")),
}
LICENCE = ("GPL-3.0, like the rest of wow-everlake-world-data: made from GPL-3.0 forever-db (QuestieDB's spawn points, "
           "CMaNGOS heights and NPC levels) and CC BY 4.0 data from EG Link (Data from Efficient Games, https://efficient.games, "
           "licensed under CC BY 4.0: creature and object details, sightings, levels, reactions, services, stock and chest loot).")


def j(value):
    return candidates.j(value) or {}


def newest(records):
    """The newest live record, else the newest beta one: (product, build, data) or None."""
    if not records:
        return None
    return max(records, key=lambda r: (r[0] == LIVE, gap_report.build_no(r[1])))


def source_label(product, build):
    return f"eg-link@{gap_report.build_no(build)}" + ("" if product == LIVE else " (Forever beta)")


class Reactions:
    """Reactions between a player of a side and a creature of a faction template, as TrinityCore works them out (1 hated
    ... 8 exalted; 2 and below attack on sight), with the reputation every player starts with:
    - seen(): how the player sees the creature, as the client colours it and EG Link records it (a reputation faction
      by the player's standing, red when at war);
    - aggro(): how the creature sees the player, which decides whether it attacks (Unit::GetFactionReactionTo: a
      reputation faction by the standing, no better than neutral when at war; else FactionTemplateEntry's checks)."""

    def __init__(self, cur):
        self.ft = {r["id"]: j(r["data"]) for r in candidates.rows(cur, f"SELECT id, data FROM {F}.src_wago WHERE tbl = 'FactionTemplate'")}
        self.fa = {r["id"]: j(r["data"]) for r in candidates.rows(cur, f"SELECT id, data FROM {F}.src_wago WHERE tbl = 'Faction'")}

    @staticmethod
    def ints(row, name, n):
        return [int(row.get(f"{name}_{i}") or 0) for i in range(n)]

    def friendly(self, a, b):
        """FactionTemplateEntry::IsFriendlyTo (a's view of b)."""
        if a is b:
            return True
        if int(b["Faction"]):
            if int(b["Faction"]) in self.ints(a, "Enemies", 8):
                return False
            if int(b["Faction"]) in self.ints(a, "Friend", 8):
                return True
        return bool(int(a["FriendGroup"]) & int(b["FactionGroup"]) or int(a["FactionGroup"]) & int(b["FriendGroup"]))

    def hostile(self, a, b):
        """FactionTemplateEntry::IsHostileTo (a's view of b)."""
        if a is b:
            return False
        if int(b["Faction"]):
            if int(b["Faction"]) in self.ints(a, "Enemies", 8):
                return True
            if int(b["Faction"]) in self.ints(a, "Friend", 8):
                return False
        return bool(int(a["EnemyGroup"]) & int(b["FactionGroup"]))

    def by_groups(self, a, b):
        """Unit::GetFactionReactionTo's common check: a's reaction to b."""
        if self.hostile(a, b):
            return 2
        if self.friendly(a, b) or self.friendly(b, a):
            return 5
        return 2 if int(a["Flags"]) & HOSTILE_BY_DEFAULT else 4

    def standing(self, side, t):
        """(code, at war) from the player's starting reputation with the template's faction, or None (no reputation)."""
        f = self.fa.get(int(t["Faction"]))
        index = candidates.as_int((f or {}).get("ReputationIndex"))
        if index is None or index < 0:
            return None
        race = PLAYER_TEMPLATE[side][1]
        for i in range(4):
            mask = int(f.get(f"ReputationRaceMasks{i}_0") or 0)
            if mask & (1 << (race - 1)):
                base = int(f.get(f"ReputationBase_{i}") or 0)
                return next((c for limit, c in RANKS if base < limit), 8), bool(int(f.get(f"ReputationFlags_{i}") or 0) & 0x2)
        return 4, False

    def seen(self, side, template):
        t, p = self.ft.get(template), self.ft[PLAYER_TEMPLATE[side][0]]
        if t is None:
            return None
        rep = self.standing(side, t)
        if rep:
            return 2 if rep[1] else rep[0]
        return self.by_groups(p, t)

    def aggro(self, side, template):
        t, p = self.ft.get(template), self.ft[PLAYER_TEMPLATE[side][0]]
        if t is None:
            return None
        rep = self.standing(side, t)
        if rep:
            return min(4, rep[0]) if rep[1] else rep[0]
        return self.by_groups(t, p)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--maps", required=True, help="Everlake's extracted maps folder (.map tiles, version 10)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--date", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y_%m_%d"))
    ap.add_argument("--world", default=candidates.WORLD, help="the fork world as SCHEMA.PREFIX (default acore_forever.tc_)")
    ap.add_argument("--sources", default=SOURCES)
    ap.add_argument("--gaps", help="a gap report JSON to use instead of running gap_report.py (made against --world)")
    ap.add_argument("--replace", action="store_true", help="overwrite update files that differ (only before they are deployed)")
    args = ap.parse_args()
    if not re.fullmatch(r"\d{4}_\d{2}_\d{2}", args.date):
        raise SystemExit("--date: YYYY_MM_DD")
    gap_report.set_world(args.world)
    W = candidates.WORLD
    name = file_name(args)
    ground = terrain.Terrain(args.maps)
    conn = connect()
    cur = conn.cursor()
    rows, ids_sql = candidates.rows, candidates.ids_sql
    pins = {r["source"]: r["label"] for r in rows(cur, f"SELECT source, label FROM {F}.src_pins")}
    world_label = pins.get("tc-release", "?") if W == f"{F}.tc_" else W
    report = import_slice2.load_gaps(args)
    gaps = collections.defaultdict(list)
    for zone, cats in report["zones"].items():
        for cat in CATEGORIES:
            gaps[cat] += cats.get(cat, [])
    print(", ".join(f"{len(v)} {c}" for c, v in gaps.items()) + "; reading the sources ...", flush=True)
    npc_ids = {g["npc"] for g in gaps["missing_npcs"]}
    obj_ids = {g["object"] for g in gaps["objects_missing"]}

    # ---- the sources
    fdb = collections.defaultdict(list)
    for r in rows(cur, f"SELECT data FROM {F}.src_forever_db WHERE tbl = 'spawn'"):
        d = j(r["data"])
        k = (d.get("kind"), candidates.as_int(d.get("id")))
        if (k[0] == "npc" and k[1] in npc_ids) or (k[0] == "object" and k[1] in obj_ids):
            fdb[k].append((int(d["map"]), float(d["x"]), float(d["y"]), None if d.get("z") is None else float(d["z"])))
    gap_points = collections.defaultdict(set)              # as gap_report.py builds `points` for NPCs
    for (kind, i), ps in fdb.items():
        if kind == "npc":
            gap_points[i] |= {(m, round(x, 1), round(y, 1)) for m, x, y, _ in ps}
    eg = collections.defaultdict(list)                      # (tbl, id) -> [(product, build, data)]
    for tbl in ("creature_details.enUS", "object_details.enUS", "npcs", "creatures"):
        wanted = obj_ids if tbl.startswith("object") else npc_ids
        for r in rows(cur, f"SELECT id, data FROM {F}.src_eg_link WHERE tbl = %s AND id IN ({ids_sql(wanted)})", (tbl,)):
            d = j(r["data"])
            eg[(tbl, r["id"])].append((d.get("_product"), d.get("_build"), d))
            if tbl == "npcs":
                for p in candidates.as_list(d.get("positions")):
                    if isinstance(p, dict) and p.get("worldX") is not None and p.get("instance") is not None:
                        gap_points[int(r["id"])].add((int(p["instance"]), round(float(p["worldX"]), 1), round(float(p["worldY"]), 1)))
    fdb_npc = {r["id"]: j(r["data"]) for r in rows(cur, f"SELECT id, data FROM {F}.src_forever_db WHERE tbl = 'npc' AND id IN ({ids_sql(npc_ids)})")}
    live = s4.live_sightings(args.sources, cur)
    displays = {r["id"] for r in rows(cur, f"SELECT id FROM {F}.src_wago WHERE tbl = 'CreatureDisplayInfo'")}
    obj_displays = {r["id"] for r in rows(cur, f"SELECT id FROM {F}.src_wago WHERE tbl = 'GameObjectDisplayInfo'")}
    item_known = {r["id"] for r in rows(cur, f"SELECT id FROM {F}.src_forever_db WHERE tbl = 'item'")}
    chest_loot = collections.defaultdict(list)              # object -> [(product, build, data)] of its openings
    for r in rows(cur, f"SELECT k, data FROM {F}.src_eg_link WHERE tbl = 'loot' AND k LIKE %s", ("%/object:%",)):
        m = re.search(r"/object:(\d+)(\|.*)?$", r["k"])
        if m and int(m.group(1)) in obj_ids and (m.group(2) or "") == OPEN_SPELL:
            d = j(r["data"])
            chest_loot[int(m.group(1))].append((d.get("_product"), d.get("_build"), d))
    reactions = Reactions(cur)

    # ---- the world
    smart_obj = {r["p"] for r in rows(cur, f"SELECT DISTINCT action_param1 p FROM {W}smart_scripts WHERE action_type = 50")}
    spell_npc, spell_obj = set(), set()
    cur.execute(f"SELECT JSON_EXTRACT(data, '$.data.related.SpellEffect') FROM {F}.src_item_history WHERE tbl = 'spells'")
    for (effects,) in cur.fetchall():
        for e in candidates.j(effects) or []:
            if isinstance(e, dict) and e.get("EffectMiscValue"):
                if e.get("Effect") in s4.NPC_SUMMON_EFFECTS:
                    spell_npc.add(e["EffectMiscValue"][0])
                elif e.get("Effect") in s4.OBJECT_SUMMON_EFFECTS:
                    spell_obj.add(e["EffectMiscValue"][0])
    map_type = {r["id"]: candidates.as_int(j(r["data"]).get("InstanceType"))
                for r in rows(cur, f"SELECT id, data FROM {F}.src_wago WHERE tbl = 'Map'")}
    maps = {m for ps in fdb.values() for m, *_ in ps}
    spawns = s4.Grid(s4.BUILDING_YARDS * 8)
    for table in ("creature", "gameobject"):
        cur.execute(f"SELECT id, map, position_x, position_y, position_z FROM {W}{table} WHERE map IN ({ids_sql(maps)})")
        for i, m, x, y, z in cur.fetchall():
            spawns.add(m, float(x), float(y), float(z))
    height = s4.Heights(ground, spawns, map_type)
    # the fork's NPCs by place, with what this slice borrows from them
    fork_tpl = {}
    cur.execute(f"SELECT t.entry, t.name, t.faction, t.type, t.speed_walk, t.speed_run, t.BaseAttackTime, t.RangeAttackTime, "
                f"t.BaseVariance, t.RangeVariance, t.unit_flags FROM {W}creature_template t WHERE t.faction <> 0")
    cols = [c[0] for c in cur.description]
    for r in cur.fetchall():
        fork_tpl[r[0]] = dict(zip(cols, r))
    near_npcs = s4.Grid(FACTION_YARDS * 2)
    cur.execute(f"SELECT guid, id, map, position_x, position_y FROM {W}creature WHERE map IN ({ids_sql(maps)})")
    for guid, i, m, x, y in cur.fetchall():
        t = fork_tpl.get(i)
        if t and not s4.TEST_NAME.search(t["name"] or ""):
            near_npcs.add(m, float(x), float(y), (guid, i))
    icon_names = collections.defaultdict(collections.Counter)  # the fork's spelling of each mouse cursor
    for r in rows(cur, f"SELECT IconName, COUNT(*) n FROM {W}creature_template WHERE IconName <> '' GROUP BY IconName"):
        icon_names[r["IconName"].lower()][r["IconName"]] += int(r["n"])
    habits = collections.defaultdict(collections.Counter)
    cur.execute(f"SELECT t.Classification, c.map, c.spawntimesecs, c.wander_distance, c.MovementType FROM {W}creature c "
                f"JOIN {W}creature_template t ON t.entry = c.id WHERE c.map IN ({ids_sql(maps)}) AND c.MovementType IN (0, 1)")
    for cls, m, st, wd, mt in cur.fetchall():
        habits[("npc", cls, m)][(int(st), round(float(wd), 1), int(mt))] += 1
    cur.execute(f"SELECT t.type, g.spawntimesecs, g.animprogress, g.state FROM {W}gameobject g JOIN {W}gameobject_template t "
                f"ON t.entry = g.id WHERE t.type IN ({ids_sql(OBJECT_TYPES)})")
    for typ, st, ap, state in cur.fetchall():
        habits[("object", typ)][(int(st), int(ap), int(state))] += 1
    fork_loot = {r["Entry"] for r in rows(cur, f"SELECT DISTINCT Entry FROM {W}gameobject_loot_template")}
    fork_spawned = collections.Counter(r["id"] for r in rows(cur, f"SELECT id FROM {W}creature WHERE id IN ({ids_sql(npc_ids)})"))
    fork_obj_spawned = collections.Counter(r["id"] for r in rows(cur, f"SELECT id FROM {W}gameobject WHERE id IN ({ids_sql(obj_ids)})"))
    for t in ("creature_template", "gameobject_template"):
        top = rows(cur, f"SELECT MAX(entry) AS m FROM {W}{t}")[0]["m"]
        print(f"the fork's highest {t} entry: {top}")
    tops = {t: rows(cur, f"SELECT MAX(guid) AS m FROM {W}{t}")[0]["m"] or 0 for t in ("creature", "gameobject")}
    guid = guid_start(args.out, tops)

    sl = {"adds": collections.defaultdict(list), "review": [], "held": [], "outcomes": collections.defaultdict(dict)}

    def hold(cat, k, entry, reason, why=None):
        sl["held"].append(dict(entry, category=cat, reason=reason, why=why or reason))
        sl["outcomes"][cat][k] = "held back: " + reason

    def review(cat, k, entry, why):
        sl["review"].append(dict(entry, category=cat, why=why))
        sl["outcomes"][cat][k] = "review: " + why

    def confirmed(kind, i):
        grid = live.get((kind, i))
        out = []
        for m, x, y, z in sorted(fdb.get((kind, i), [])):
            if grid and grid.near(m, x, y, s4.SIGHTING_YARDS) and not any(o[0] == m and s4.dist2(o[1:3], (x, y)) <= s4.SAME_POINT ** 2 for o in out):
                out.append((m, x, y, z))
        return out

    def place(kind, ok, common_key):
        """Spawn rows at the confirmed points that have a height, and why the others have none."""
        got, held_pts = [], []
        for m, x, y, z in ok:
            if map_type.get(m) != 0:
                held_pts.append(f"a new {kind} in a dungeon or battleground needs its difficulties, which no source records")
                continue
            hz, how = height(m, x, y, z)
            if hz is None:
                held_pts.append(how)
                continue
            common = habits.get(common_key(m))
            got.append((m, x, y, hz, how, common.most_common(1)[0][0] if common else None))
        return got, held_pts

    # ---- NPCs
    added_npcs = {}
    for g in sorted(gaps["missing_npcs"], key=lambda g: g["npc"]):
        n = g["npc"]
        e = {"npc": n, "name": g["name"], "what": f"npc {n} {g['name']}", "points": len(fdb.get(("npc", n), ()))}
        k = s4.key(n)
        if g.get("custom_sql"):
            hold("missing_npcs", k, e, "a fork custom file not loaded into the world yet writes this NPC")
            continue
        if n in spell_npc:
            hold("missing_npcs", k, e, "a client spell summons it")
            continue
        ok = confirmed("npc", n)
        if not ok:
            hold("missing_npcs", k, e, "no live Forever sighting within 40 yards of a known point (beta or Classic data only)",
                 f"forever-db lists {e['points']} point(s); no EG Link live sighting lies within {s4.SIGHTING_YARDS} yards of any")
            continue
        det = newest(eg.get(("creature_details.enUS", n)))
        if not det:
            hold("missing_npcs", k, e, "EG Link has no creature details for it (its template's client data)")
            continue
        product, build, d = det
        src = source_label(product, build)
        models = [x for x in candidates.as_list(d.get("displays")) if isinstance(x, dict) and x.get("displayId")]
        unknown = [x["displayId"] for x in models if x["displayId"] not in displays]
        if not models or unknown:
            hold("missing_npcs", k, e, "a model isn't in Forever's client (CreatureDisplayInfo)", f"models {unknown or 'none'} ({src})")
            continue
        if candidates.as_int(d.get("unitClass")) not in UNIT_CLASSES:
            hold("missing_npcs", k, e, "its class isn't one a creature can have (warrior, paladin, rogue, mage)", f"unitClass {d.get('unitClass')} ({src})")
            continue
        if n in fork_spawned:
            hold("missing_npcs", k, e, "the fork already has spawns of it, with no template", f"fork spawns: {fork_spawned[n]}")
            continue
        live_recs = [r for tbl in ("npcs", "creatures") for r in eg.get((tbl, n), []) if r[0] == LIVE]
        levels = set()
        for _, _, x in live_recs:
            lv = x.get("levels")
            levels |= {int(v) for v in (lv.keys() if isinstance(lv, dict) else candidates.as_list(lv)) if str(v).isdigit()}
        f = fdb_npc.get(n, {})
        fdb_lv = (candidates.as_int(f.get("level_min")), candidates.as_int(f.get("level_max")) or candidates.as_int(f.get("level_min")))
        if levels:
            lv, lv_src = (min(levels), max(levels)), "levels eg-link live"
        elif fdb_lv[0]:
            lv, lv_src = fdb_lv, "levels forever-db"
        else:
            hold("missing_npcs", k, e, "no level: neither EG Link's live records nor forever-db have one")
            continue
        seen = collections.defaultdict(set)                  # side -> reaction codes live players saw
        services = set()
        for _, _, x in sorted(live_recs, key=lambda r: gap_report.build_no(r[1])):
            for side, codes in (x.get("reactions") or {}).items():
                if side in PLAYER_TEMPLATE:
                    seen[side] |= {int(c) for c in candidates.as_list(codes) if str(c).isdigit()}
            if x.get("interactions"):
                services = set(x["interactions"])            # the newest live record's
        if not seen:
            hold("missing_npcs", k, e, "no live reaction recorded (whether it attacks players), so no faction can be chosen")
            continue
        want = {side: min(codes) for side, codes in seen.items()}
        if any((min(c) <= 2) != (max(c) <= 2) for c in seen.values()):
            hold("missing_npcs", k, e, "players saw it both hostile and not", json.dumps({s: sorted(c) for s, c in seen.items()}))
            continue
        pick = choose_faction(n, d, ok, want, near_npcs, fork_tpl, reactions)
        if not pick:
            hold("missing_npcs", k, e, f"no fork NPC within {FACTION_YARDS} yards reacts to players as it does, so no faction can be chosen",
                 json.dumps(want))
            continue
        faction, model, how_faction = pick
        # services
        flags, svc_notes = 0, []
        for s in sorted(services):
            if s in SERVICE:
                flags |= SERVICE[s]
            elif s == "Trainer":
                svc_notes.append("trains (left off: a trainer list and a gossip option to open it are hand work)")
            elif s not in ("Gossip",):
                svc_notes.append(f"{s} (no flag for it here)")
        if not flags and "Gossip" in services:
            flags = GOSSIP
        unique = [s4.UNIQUE_CLASSIFICATION[d.get("classification")]] if d.get("classification") in s4.UNIQUE_CLASSIFICATION else []
        unique += [w for fl, w in s4.SERVICE_FLAGS.items() if flags & fl]
        if flags and not any(flags & fl for fl in s4.SERVICE_FLAGS):
            unique.append("offers a service")
        if d.get("title"):
            unique.append(f"titled {d['title']}")
        if len(ok) > 1 and all(a[0] == b[0] and s4.dist2(a[1:3], b[1:3]) <= CLUSTER_YARDS ** 2 for a in ok for b in ok):
            unique.append(f"every point within {CLUSTER_YARDS} yards of the others")
        if unique and len(ok) > 1:
            review("missing_npcs", k, dict(e, points=[list(p) for p in ok]),
                   f"a unique NPC ({', '.join(unique)}) with {len(ok)} confirmed points: it may be one NPC on a patrol path")
            continue
        placed, held_pts = place("npc", ok, lambda m, c=d.get("classification") or 0: ("npc", c, m))
        if not placed:
            hold("missing_npcs", k, dict(e, points=[list(p) for p in ok]), held_pts[0].split(" (")[0] if "stands off" in held_pts[0]
                 else held_pts[0], "; ".join(dict.fromkeys(held_pts)))
            continue
        flags_d = (candidates.as_list(d.get("flags")) + [0, 0, 0])[:3]
        proxies = (candidates.as_list(d.get("proxyCreatureIds")) + [0, 0])[:2]
        cursor = d.get("cursor") or ""
        icon = icon_names[cursor.lower()].most_common(1)[0][0] if cursor and icon_names.get(cursor.lower()) else cursor
        borrowed = f"faction {how_faction}; speeds, attack times, immunity as fork NPC {model['entry']} {model['name']}"
        note = f"{src}; {lv_src} {lv[0]}-{lv[1]}; {borrowed}"
        why = f"{d.get('name')} ({g['name']})"
        sl["adds"]["creature_template"].append({
            "entry": n, "KillCredit1": int(proxies[0] or 0), "KillCredit2": int(proxies[1] or 0), "name": d.get("name") or g["name"],
            "femaleName": d.get("femaleName") or "", "subname": d.get("title") or None, "TitleAlt": None, "IconName": icon or None,
            "RequiredExpansion": 0, "VignetteID": 0, "faction": faction, "npcflag": flags, "speed_walk": float(model["speed_walk"]),
            "speed_run": float(model["speed_run"]), "scale": 1.0, "Classification": int(d.get("classification") or 0), "dmgschool": 0,
            "BaseAttackTime": int(model["BaseAttackTime"]), "RangeAttackTime": int(model["RangeAttackTime"]),
            "BaseVariance": float(model["BaseVariance"]), "RangeVariance": float(model["RangeVariance"]),
            "unit_class": int(d["unitClass"]), "unit_flags": int(model["unit_flags"]) & IMMUNE, "unit_flags2": 2048,
            "unit_flags3": 0, "family": int(d.get("family") or 0), "trainer_class": 0, "type": int(d.get("type") or 0),
            "VehicleId": 0, "AIName": "", "MovementType": 0, "ExperienceModifier": 1.0, "RacialLeader": 0,
            "movementId": int(d.get("movementInfoId") or 0), "WidgetSetID": 0, "WidgetSetUnitConditionID": 0, "RegenHealth": 1,
            "CreatureImmunitiesId": 0, "flags_extra": 0, "ScriptName": "", "StringId": None,
            "VerifiedBuild": 0, "note": note[:255], "why": why})
        sl["adds"]["creature_template_difficulty"].append({
            "Entry": n, "DifficultyID": 0, "LevelScalingDeltaMin": 0, "LevelScalingDeltaMax": 0, "ContentTuningID": 0,
            "HealthScalingExpansion": int(d.get("healthScalingExpansion") or 0), "HealthModifier": float(d.get("hpMultiplier") or 1),
            "ManaModifier": float(d.get("energyMultiplier") or 1), "ArmorModifier": 1.0, "DamageModifier": 1.0,
            "CreatureDifficultyID": int(d.get("creatureDifficultyId") or 0), "TypeFlags": int(flags_d[0]), "TypeFlags2": int(flags_d[1]),
            "TypeFlags3": int(flags_d[2]), "LootID": 0, "PickPocketLootID": 0, "SkinLootID": 0, "GoldMin": 0, "GoldMax": 0,
            **{f"StaticFlags{i}": 0 for i in range(1, 9)}, "VerifiedBuild": 0, "note": src, "why": why})
        for idx, x in enumerate(models):
            sl["adds"]["creature_template_model"].append({
                "CreatureID": n, "Idx": idx, "CreatureDisplayID": int(x["displayId"]), "DisplayScale": float(x.get("scale") or 1),
                "Probability": float(x.get("probability") if x.get("probability") is not None else 1), "VerifiedBuild": 0,
                "note": src, "why": why})
        sl["adds"]["creature_classic_level"].append({"entry": n, "level_min": lv[0], "level_max": lv[1],
                                                     "note": lv_src + (f" (forever-db says {fdb_lv[0]}-{fdb_lv[1]})" if lv_src.startswith("levels eg")
                                                                       and fdb_lv[0] and fdb_lv != lv else ""), "why": why})
        for m, x, y, hz, how, common in placed:
            st, wd, mt = common or (300, 0.0, 0)
            if flags:                       # someone players come to for a service stands still
                wd, mt = 0.0, 0
            sl["adds"]["creature"].append({
                "id": n, "map": m, "zoneId": 0, "areaId": 0, "spawnDifficulties": "0", "phaseUseFlags": 0, "PhaseId": 0, "PhaseGroup": 0,
                "terrainSwapMap": -1, "modelid": 0, "equipment_id": 0, "position_x": round(x, 2), "position_y": round(y, 2),
                "position_z": hz, "orientation": 0.0, "spawntimesecs": st, "wander_distance": wd, "currentwaypoint": 0,
                "MovementType": mt, "VerifiedBuild": 0,
                "note": (f"forever-db point; eg-link live sighting within {s4.SIGHTING_YARDS} yd; {how}; "
                         + ("respawn" + ("" if flags else " and wandering") + " as the fork's commonest for its classification on the map"
                            if common else "respawn 300 (no fork spawn of its classification on the map)")
                         + ("; standing still (it offers a service)" if flags else ""))[:255],
                "why": g["name"]})
        added_npcs[n] = {"name": d.get("name"), "flags": flags, "points": [(m, round(x, 2), round(y, 2)) for m, x, y, *_ in placed]}
        sl["outcomes"]["missing_npcs"][k] = "added"
        if held_pts:
            sl["held"].append(dict(e, what=e["what"] + ": some points", category="missing_npcs", reason="some of its points have no usable height",
                                   why="; ".join(dict.fromkeys(held_pts))))
        for s in svc_notes:
            sl["review"].append(dict(e, category="missing_npcs", why=f"added; EG Link players saw it {s}"))
        if "Trainer" in services:
            sl["outcomes"]["trainers_unlinked"][k] = "review: a new NPC that trains: its trainer list and gossip option are hand work"
        # after this slice the gap report knows the NPC: its loot, further spots and stock show up there
        sl["outcomes"]["npcs_no_loot"][f"{n}/*"] = "held back: a new NPC's loot comes with a slice 2 run once its template is in"
        far = gap_report.far_points(sorted(gap_points.get(n, ())), added_npcs[n]["points"], gap_report.NEW_SPOT_YARDS)
        if far:
            sl["outcomes"]["extra_spots"][k] = "held back: further spots no live sighting confirms"
            sl["held"].append({"npc": n, "name": g["name"], "what": f"npc {n} {g['name']}: further spots", "category": "extra_spots",
                               "reason": "further spots no live sighting confirms",
                               "why": f"{len(far)} more spot(s) far from every spawn: no live sighting confirms them, or only players' positions (EG Link) show them"})

    # stock of the new vendors, by slice 3's rules
    vend_pick = gap_report.newest_windows(cur, "vendors")
    vgaps = collections.defaultdict(list)
    for n, a in sorted(added_npcs.items()):
        if a["flags"] & VENDOR and n in vend_pick:
            _, _, d = vend_pick[n]
            items = {candidates.as_int(v.get("itemId")) for v in (d.get("entries") or {}).values() if isinstance(v, dict)} - {None}
            vgaps["vendors_no_stock"].append({"npc": n, "name": a["name"], "items": len(items), "custom_sql": False})
            if d.get("repairs"):
                next(r for r in sl["adds"]["creature_template"] if r["entry"] == n)["npcflag"] |= REPAIR
                a["flags"] |= REPAIR
        elif a["flags"] & VENDOR:
            review("vendors_no_stock", s4.key(n), {"npc": n, "name": a["name"], "what": f"npc {n} {a['name']}: stock"},
                   "a new merchant EG Link has no stock window for")
    vsl = {"adds": collections.defaultdict(list), "review": [], "held": [], "outcomes": collections.defaultdict(dict)}

    def vhold(cat, k, entry, reason, why=None):
        vsl["held"].append(dict(entry, category=cat, reason=reason, why=why or reason))
        vsl["outcomes"][cat][k] = "held back: " + reason
    import_slice3.vendors(cur, W, vgaps, vend_pick, vsl, vhold, flags={n: a["flags"] for n, a in added_npcs.items()})
    sl["adds"]["npc_vendor"] = vsl["adds"]["npc_vendor"]
    sl["held"] += [dict(h, points=None) for h in vsl["held"]]
    for c, v in vsl["outcomes"].items():
        sl["outcomes"][c].update(v)

    # ---- objects
    for g in sorted(gaps["objects_missing"], key=lambda g: g["object"]):
        o = g["object"]
        e = {"npc": o, "object": o, "name": g["name"], "what": f"object {o} {g['name']}", "points": len(fdb.get(("object", o), ()))}
        k = s4.key(o)
        if g.get("custom_sql"):
            hold("objects_missing", k, e, "a fork custom file not loaded into the world yet writes this object")
            continue
        if o in spell_obj or o in smart_obj:
            hold("objects_missing", k, e, "a client spell or the fork's SmartAI summons it")
            continue
        ok = confirmed("object", o)
        if not ok:
            hold("objects_missing", k, e, "no live Forever sighting within 40 yards of a known point (beta or Classic data only)")
            continue
        if o in fork_obj_spawned:
            hold("objects_missing", k, e, "the fork already has spawns of it, with no template", f"fork spawns: {fork_obj_spawned[o]}")
            continue
        det = newest(eg.get(("object_details.enUS", o)))
        if not det:
            hold("objects_missing", k, e, "EG Link has no object details for it (its template's client data)")
            continue
        product, build, d = det
        src = source_label(product, build)
        typ = int(d.get("type") or 0)
        if typ not in OBJECT_TYPES:
            hold("objects_missing", k, e, "a type that needs a script or a link no source records", f"type {typ} ({src})")
            continue
        if int(d.get("displayId") or 0) and int(d["displayId"]) not in obj_displays:
            hold("objects_missing", k, e, "its model isn't in Forever's client (GameObjectDisplayInfo)", f"model {d['displayId']} ({src})")
            continue
        data = [candidates.as_int(x) or 0 for x in (candidates.as_list(d.get("data")) + [0] * 35)[:35]]
        quest_items = [int(x) for x in candidates.as_list(d.get("questItems")) if str(x).isdigit()]
        loot_rows, loot_review = [], []
        if typ == 3 and data[1] and data[1] not in fork_loot:
            loot_rows, loot_review, loot_held = chest_rows(o, data[1], chest_loot.get(o, []), quest_items, item_known)
            if not loot_rows:
                hold("objects_missing", k, e, "a chest with no loot a source records well enough",
                     "; ".join(loot_held + loot_review) or f"no EG Link opening of it ({src})")
                continue
        placed, held_pts = place("object", ok, lambda m, t=typ: ("object", t))
        if not placed:
            hold("objects_missing", k, dict(e, points=[list(p) for p in ok]), held_pts[0].split(" (")[0] if "stands off" in held_pts[0]
                 else held_pts[0], "; ".join(dict.fromkeys(held_pts)))
            continue
        why = d.get("name") or g["name"]
        sl["adds"]["gameobject_template"].append(dict(
            {"entry": o, "type": typ, "displayId": int(d.get("displayId") or 0), "name": d.get("name") or g["name"], "IconName": "",
             "castBarCaption": "", "unk1": "", "size": float(d.get("size") or 1)},
            **{f"Data{i}": data[i] for i in range(35)},
            ContentTuningId=0, RequiredLevel=0, AIName="", ScriptName="", StringId=None, VerifiedBuild=0,
            note=src, why=why))
        for idx, item in enumerate(quest_items):
            sl["adds"]["gameobject_questitem"].append({"GameObjectEntry": o, "Idx": idx, "ItemId": item, "VerifiedBuild": 0,
                                                      "note": src, "why": why})
        have = {(r["Entry"], r["ItemType"], r["Item"]) for r in sl["adds"]["gameobject_loot_template"]}
        sl["adds"]["gameobject_loot_template"] += [r for r in loot_rows if (r["Entry"], r["ItemType"], r["Item"]) not in have]
        for r in loot_review:
            sl["review"].append(dict(e, category="objects_missing", why=f"added; chest loot left out: {r}"))
        for m, x, y, hz, how, common in placed:
            st, anim, state = common or (300, 255, 1)
            sl["adds"]["gameobject"].append({
                "id": o, "map": m, "zoneId": 0, "areaId": 0, "spawnDifficulties": "0", "phaseUseFlags": 0, "PhaseId": 0,
                "PhaseGroup": 0, "terrainSwapMap": -1, "position_x": round(x, 2), "position_y": round(y, 2), "position_z": hz,
                "orientation": 0.0, "rotation0": 0.0, "rotation1": 0.0, "rotation2": 0.0, "rotation3": 1.0,
                "spawntimesecs": st, "animprogress": anim, "state": state, "VerifiedBuild": 0,
                "note": (f"forever-db point; eg-link live sighting within {s4.SIGHTING_YARDS} yd; {how}; respawn, animation "
                         "and state as the fork's commonest for its type")[:255], "why": why})
        sl["outcomes"]["objects_missing"][k] = "added"
        rest = len(fdb.get(("object", o), ())) - len(placed)
        if rest > 0:
            sl["held"].append(dict(e, what=e["what"] + ": its other points", category="objects_missing",
                                   reason="an object's other points: no live sighting confirms them, or no usable height",
                                   why=f"{rest} more point(s): " + ("; ".join(dict.fromkeys(held_pts)) if held_pts else
                                                                    "no live sighting within 40 yards")))

    # guids: in a fixed order, so the same pins give the same file
    for table in ("creature", "gameobject"):
        for r in sorted(sl["adds"][table], key=lambda r: (r["id"], r["map"], r["position_x"], r["position_y"])):
            r["guid"] = guid[table]
            guid[table] += 1
        sl["adds"][table].sort(key=lambda r: r["guid"])

    col_info = collections.defaultdict(dict)
    schema, prefix = W.split(".")
    names = [prefix + t for t in list(TABLES) + ["gameobject_loot_template"]]
    cur.execute("SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE FROM information_schema.columns "
                f"WHERE table_schema = %s AND table_name IN ({', '.join(['%s'] * len(names))}) ORDER BY ORDINAL_POSITION", [schema] + names)
    for tn, cn, dt, ct, nullable in cur.fetchall():
        col_info[tn[len(prefix):]][cn] = {"type": dt, "ddl": ct + ("" if nullable == "YES" else " NOT NULL")}
    for t, (cols_t, _, _) in list(TABLES.items()) + [("gameobject_loot_template", (GLT_COLUMNS, None, None))]:
        if [c for c in cols_t if c not in col_info[t]]:
            raise SystemExit(f"{t}: the world lacks columns this slice writes: {[c for c in cols_t if c not in col_info[t]]}")
    write(args, name, sl, pins, world_label, col_info, {c: len(v) for c, v in gaps.items()}, guid, ground.build(), tops)


def choose_faction(n, d, points, want, near_npcs, fork_tpl, reactions):
    """(faction, model fork template, how) or None: rule 2. Fork NPCs of the same creature type first; a hostile one may
    also take the faction of another type's (never a critter's: critters are friendly to everyone)."""
    first = (d.get("name") or "").split(" ")[0].lower()
    typ = int(d.get("type") or 0)
    hostile = all(c <= 2 for c in want.values())
    votes = collections.Counter()
    nearest = collections.defaultdict(list)              # faction -> [(other type, distance², entry, template)]
    for m, x, y, _ in points:
        for px, py, (guid, i) in near_npcs.near(m, x, y, FACTION_YARDS):
            t = fork_tpl[i]
            other = int(t["type"]) != typ
            if i == n or (other and (not hostile or int(t["type"]) == CRITTER)):
                continue
            codes = {side: reactions.seen(side, t["faction"]) for side in want}
            attacks = {side: reactions.aggro(side, t["faction"]) for side in want}
            if any(codes[side] is None or (codes[side] <= 2) != (want[side] <= 2) or (attacks[side] <= 2) != (want[side] <= 2)
                   for side in want):
                continue
            family = (t["name"] or "").split(" ")[0].lower() == first
            exact = all(c == want[side] for side, c in codes.items())
            votes[(t["faction"], not other, family, exact)] += 1
            nearest[t["faction"]].append((other, s4.dist2((px, py), (x, y)), i, t))
    if not votes:
        return None
    (faction, same_type, family, exact), count = max(votes.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][3], kv[1], -kv[0][0]))
    _, _, _, model = min(nearest[faction], key=lambda v: (v[0], v[1], v[2]))
    how = (f"{faction} from {count} fork spawn(s) within {FACTION_YARDS} yd" + ("" if same_type else " of another type")
           + (" sharing its first name" if family else "") + (", same reaction" if exact else ", same attack-on-sight")
           + f" ({', '.join(f'{s} {c}' for s, c in sorted(want.items()))})")
    return faction, model, how


def chest_rows(o, loot_id, records, quest_items, item_known):
    """(rows, review notes, held notes) for a chest's loot table, from EG Link's openings (live and beta summed)."""
    opens, drops = 0, collections.Counter()
    quest, builds = set(), set()
    for product, build, d in records:
        opens += int(d.get("windows") or 0)
        builds.add(source_label(product, build))
        for item, v in (d.get("items") or {}).items():
            if str(item).isdigit() and isinstance(v, dict):
                drops[int(item)] += int(v.get("drops") or 0)
                if v.get("quest"):
                    quest.add(int(item))
    rows, rev, held = [], [], []
    src = ", ".join(sorted(builds, key=lambda b: (gap_report.build_no(b.split("@")[1].split(" ")[0]), b)))
    for item in sorted(set(drops) | set(quest_items)):
        if item not in item_known:
            held.append(f"item {item} isn't in Forever's client item list")
            continue
        if item in quest or item in quest_items:
            chance, qr, how = 100.0, 1, "quest item: 100% for players on the quest"
        elif opens >= MIN_OPENS:
            chance, qr, how = round(100.0 * drops[item] / opens, 3), 0, f"{drops[item]} of {opens} openings"
        else:
            rev.append(f"item {item}: {drops[item]} of only {opens} openings")
            continue
        rows.append({"Entry": loot_id, "ItemType": 0, "Item": item, "Chance": chance, "QuestRequired": qr, "LootMode": 1, "GroupId": 0,
                     "MinCount": 1, "MaxCount": 1, "Comment": None,
                     "note": f"{src or 'no eg-link opening recorded'}; {how}" + (" (a quest item its details name)" if item in quest_items and item not in quest else ""),
                     "why": f"object {o}: item {item}"})
    return rows, rev, held


def guid_start(out, tops):
    """After the highest guid an earlier slice's manifest uses (and above the fork's)."""
    start = {"creature": GUID_BASE, "gameobject": GUID_BASE}
    for path in glob.glob(os.path.join(out, "slices", "*", "manifest.json")):
        with open(path) as handle:
            m = json.load(handle)
        if m.get("slice") == SLICE:
            continue
        for t, used in (m.get("guids_used") or {}).items():
            if used:
                start[t] = max(start[t], used[1] + 1)
    for t, top in tops.items():
        if top >= GUID_BASE:
            raise SystemExit(f"the fork's {t} guids reach {top}: they meet the import's block at {GUID_BASE}")
    return start


def file_name(args):
    """Slice 5's file follows every other slice's file already in the folder for this date."""
    folder = os.path.join(args.out, "sql", "world")
    taken = []
    if os.path.isdir(folder):
        for n in os.listdir(folder):
            m = re.match(rf"{args.date}_(\d\d)_world_everlake_import_(\w+?)(?:_corrections)?\.sql$", n)
            if m and m.group(2) != SLICE:
                taken.append(int(m.group(1)))
    return isql.check_name(f"{args.date}_{(max(taken) + 1 if taken else 0):02d}_world_everlake_import_{SLICE}.sql")


def write(args, name, sl, pins, world_label, col_info, gap_counts, guid, maps_build, tops):
    sql_dir = os.path.join(args.out, "sql", "world")
    meta_dir = os.path.join(args.out, "slices", SLICE)
    os.makedirs(sql_dir, exist_ok=True)
    os.makedirs(meta_dir, exist_ok=True)

    def never_again(table, key):
        on = " AND ".join(f"r.`k{n + 1}` = s.{isql.ident(k)}" for n, k in enumerate(key))
        return f"NOT EXISTS (SELECT 1 FROM `{isql.IMPORT_ROWS}` r WHERE r.`tbl` = {isql.lit(table)} AND {on})"

    def ours(col, template):
        """The template is ours: this file added it, and it is still as we wrote it (VerifiedBuild 0: a fork file that takes
        the entry over with a sniffed template makes it the fork's)."""
        return (f"EXISTS (SELECT 1 FROM `{isql.IMPORT_ROWS}` t0 JOIN {isql.ident(template)} c0 ON c0.`entry` = t0.`k1` "
                f"WHERE t0.`tbl` = {isql.lit(template)} AND t0.`k1` = s.{isql.ident(col)} AND t0.`file` = {isql.lit(name)} "
                "AND c0.`VerifiedBuild` = 0)")

    def clean(rows, cols):
        return [{k: v for k, v in r.items() if k in cols + ["note", "why"]} for r in rows]

    out = isql.file_header("Everlake world import, slice 5: NPCs and objects live Forever players saw that the world has no "
                           "template for, with their spawns", name, pins, world_label, LICENCE)
    out += [isql.IMPORT_ROWS_DDL, ""]
    headers = {
        "creature_template": "creature_template: NPCs the world has no template for (never again once added: one the fork removes stays removed)",
        "creature_template_difficulty": "creature_template_difficulty: their health, power and type flags (EG Link's client data)",
        "creature_template_model": "creature_template_model: their models",
        "creature_classic_level": "creature_classic_level: their levels",
        "gameobject_template": "gameobject_template: objects the world has no template for",
        "gameobject_questitem": "gameobject_questitem: the quest items they hold",
        "creature": f"creature: spawns of the new NPCs at points a live sighting confirms (not where the fork spawns the NPC within "
                    f"{s4.SIGHTING_YARDS} yards)",
        "gameobject": f"gameobject: spawns of the new objects (not where the fork spawns the object within {s4.SIGHTING_YARDS} yards)",
        "npc_vendor": "npc_vendor: what the new merchants sell (EG Link's stock, slice 3's rules)",
    }
    for table, (cols, key, hangs) in TABLES.items():
        guard = never_again(table, key)
        if hangs:
            guard += " AND " + ours(*hangs)
        if table in ("creature", "gameobject"):
            guard += (f" AND NOT EXISTS (SELECT 1 FROM `{table}` c WHERE c.`id` = s.`id` AND c.`map` = s.`map` AND (c.`position_x` - "
                      f"s.`position_x`) * (c.`position_x` - s.`position_x`) + (c.`position_y` - s.`position_y`) * (c.`position_y` - "
                      f"s.`position_y`) <= {s4.SIGHTING_YARDS * s4.SIGHTING_YARDS} AND NOT EXISTS (SELECT 1 FROM `{isql.IMPORT_ROWS}` o "
                      f"WHERE o.`tbl` = {isql.lit(table)} AND o.`k1` = c.`guid`))")
        if table == "npc_vendor":
            guard += (" AND NOT EXISTS (SELECT 1 FROM `npc_vendor` o WHERE o.`entry` = s.`entry` AND o.`item` = s.`item` "
                      "AND o.`type` = s.`type`)")
        out += isql.stage_block(table, cols, key, clean(sl["adds"][table], cols), name, guard, headers[table], col_info[table])
        if table == "gameobject_questitem":         # a chest's loot: only while no one else's rows stand in its loot table
            loot = "gameobject_loot_template"
            out += isql.stage_block(
                loot, GLT_COLUMNS, ["Entry", "ItemType", "Item"], clean(sl["adds"][loot], GLT_COLUMNS), name,
                f"{never_again(loot, ['Entry', 'ItemType', 'Item'])} AND EXISTS (SELECT 1 FROM `{isql.IMPORT_ROWS}` t0 JOIN "
                f"`gameobject_template` g ON g.`entry` = t0.`k1` WHERE t0.`tbl` = 'gameobject_template' AND t0.`file` = {isql.lit(name)} "
                f"AND g.`type` = 3 AND g.`Data1` = s.`Entry` AND g.`VerifiedBuild` = 0) AND NOT EXISTS (SELECT 1 FROM `{loot}` o WHERE o.`Entry` = s.`Entry` "
                f"AND NOT EXISTS (SELECT 1 FROM `{isql.IMPORT_ROWS}` r2 WHERE r2.`tbl` = {isql.lit(loot)} AND r2.`k1` = o.`Entry` "
                "AND r2.`k2` = o.`ItemType` AND r2.`k3` = o.`Item`))",
                "gameobject_loot_template: the new chests' loot (while the chest is ours and no one else's rows stand in its loot table)",
                col_info[loot])
    text = "\n".join(out).rstrip() + "\n"
    path = os.path.join(sql_dir, name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            if handle.read() != text and not args.replace:
                raise SystemExit(f"{path} exists with other content. A deployed update file is never changed; if this one "
                                 "was never deployed, run again with --replace")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    first = {t: (min(r["guid"] for r in sl["adds"][t]) if sl["adds"][t] else None) for t in ("creature", "gameobject")}
    manifest = {"slice": SLICE, "pins": pins, "world": world_label, "gaps": gap_counts, "maps_build": maps_build,
                "guid_base": GUID_BASE, "guids_used": {t: [first[t], guid[t] - 1] if first[t] else None for t in guid},
                "fork_guid_top": tops,
                "files": [{"name": name, "kind": "import", "sha1": hashlib.sha1(text.encode()).hexdigest().upper()}],
                "adds": {t: [{k: v for k, v in r.items() if k != "why"} for r in rs] for t, rs in sorted(sl["adds"].items())},
                "fixes": [], "review": sl["review"], "held_back": sl["held"],
                "outcomes": {c: dict(sorted(v.items())) for c, v in sorted(sl["outcomes"].items())}}
    with open(os.path.join(meta_dir, "manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True)
    with open(os.path.join(meta_dir, "review.md"), "w") as handle:
        handle.write(s4.listing("Slice 5: for a person (not in the files)", "Unique NPCs with several confirmed points (one NPC on a "
                                "patrol path?), services no flag here covers, and chest loot seen too few times.", sl["review"]))
    with open(os.path.join(meta_dir, "held-back.md"), "w") as handle:
        handle.write(s4.listing("Slice 5: held back", "NPCs and objects that need something we don't have, and why. Nothing here "
                                "was guessed.", sl["held"]))
    a = sl["adds"]
    print(f"wrote {path}: {len(a['creature_template'])} NPCs ({len(a['creature'])} spawns, {len(a['npc_vendor'])} vendor items), "
          f"{len(a['gameobject_template'])} objects ({len(a['gameobject'])} spawns, {len(a['gameobject_loot_template'])} loot rows); "
          f"{len(sl['review'])} for review, {len(sl['held'])} held back (in {meta_dir})")


if __name__ == "__main__":
    main()
