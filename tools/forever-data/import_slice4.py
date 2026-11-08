#!/usr/bin/env python3
"""Slice 4 of Everlake's world import (docs/forever-import.md): spawns. NPCs and objects that have a template in the
world but no spawn, and NPCs' spawn spots the world lacks.

    import_slice4.py --maps DIR               Everlake's extracted maps folder (the worldserver's data/maps)
    import_slice4.py --out DIR                write somewhere else (a clone of wow-everlake-world-data)
    import_slice4.py --date 2026_11_08        the update files' date (default: today, UTC)

Works on the gaps gap_report.py lists (npcs_not_spawned, extra_spots, objects_not_spawned), running the report itself
(--gaps FILE reuses one). Writes only files:
- sql/world/YYYY_MM_DD_NN_world_everlake_import_slice4.sql: creature and gameobject rows;
- slices/slice4/manifest.json, review.md and held-back.md.

The user's decisions (2026-11-08):
1. A spawn point comes from forever-db (QuestieDB's points; a height where a CMaNGOS spawn stands within 3 yards), and
   goes in only where a live Forever sighting of that NPC or object lies within 40 yards: EG Link's combat-log
   positions, deaths, loot and windows on live builds. forever-db's points are largely Classic data (holiday and
   invasion NPCs, test NPCs, WotLK ones); a point no live sighting confirms is held back.
2. Only NPCs and objects nothing summons or scripts: one the fork's SmartAI or a client spell summons, or (if the fork
   doesn't spawn it at all) with a script (AIName or ScriptName), is held back; the fork may summon it in a quest or
   event. An NPC the fork already spawns keeps its script on an extra spot (most hostile NPCs have a combat script).
3. A point with no height takes the ground height from Everlake's own extracted maps (terrain.py), unless it is in a
   dungeon or battleground, in water, or a fork spawn within 10 yards stands more than 2 yards off the ground (a
   building, a bridge or a cave the terrain doesn't show): those are held back.
4. A unique NPC (elite, rare or boss, or one that gives or ends quests, sells or trains) that would get more than one
   spawn, or an extra spot next to the spawn it has, goes to the review list: it may be one NPC on a patrol path.
5. Guids count from 900,000,000 (creatures and objects each), far above the fork's (26 and 34 million today, checked);
   the same spawn point gets the same guid on every run of the same file. A later slice takes up after the highest
   guid an earlier slice's manifest uses, and must also look above the live realm's highest guid: the worldserver hands
   a GM's .npc add or .gobject add the highest guid + 1, which is inside this block once these spawns are in (the
   guard then skips a row whose guid is taken, rather than failing).

Values no source has: orientation 0 (an object's rotation (0, 0, 0, 1)); an extra spot copies its phases, difficulty,
equipment, respawn time and wandering from the NPC's nearest fork spawn (standing still where that one walks a path);
a new NPC's respawn and wandering are the commonest of the fork's spawns of NPCs of the same classification on that
map; an object's respawn, animation and state the commonest of the fork's objects of the same type. Each row's note
says which.
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
import import_slice2  # noqa: E402  (the gap report)
import import_sql as isql  # noqa: E402
import terrain  # noqa: E402
from load_sources import SOURCES, connect  # noqa: E402

SLICE = "slice4"
F = candidates.F
OUT = os.path.join(HERE, "world-data")
CATEGORIES = ("npcs_not_spawned", "extra_spots", "objects_not_spawned")
GUID_BASE = 900_000_000
SIGHTING_YARDS = 40
BUILDING_YARDS, BUILDING_OFF = 10, 2.0
SAME_POINT = 10                   # two points closer than this are one spawn
CREATURE_COLUMNS = ["guid", "id", "map", "zoneId", "areaId", "spawnDifficulties", "phaseUseFlags", "PhaseId", "PhaseGroup",
                    "terrainSwapMap", "modelid", "equipment_id", "position_x", "position_y", "position_z", "orientation",
                    "spawntimesecs", "wander_distance", "currentwaypoint", "MovementType", "VerifiedBuild"]
OBJECT_COLUMNS = ["guid", "id", "map", "zoneId", "areaId", "spawnDifficulties", "phaseUseFlags", "PhaseId", "PhaseGroup",
                  "terrainSwapMap", "position_x", "position_y", "position_z", "orientation", "rotation0", "rotation1",
                  "rotation2", "rotation3", "spawntimesecs", "animprogress", "state", "VerifiedBuild"]
UNIQUE_CLASSIFICATION = {1: "elite", 2: "rare elite", 3: "boss", 4: "rare"}
SERVICE_FLAGS = {2: "gives quests", 16: "trains", 128: "sells"}
NPC_SUMMON_EFFECTS = {28}                      # SPELL_EFFECT_SUMMON: EffectMiscValue[0] = creature
OBJECT_SUMMON_EFFECTS = {50, 76, 104, 105, 106, 107, 171}   # trans door, summon object wild and slots, personal object
TEST_NAME = re.compile(r"\b(DND|DNR|DNT|test|TEST)\b|^\[")
LICENCE = ("GPL-3.0, like the rest of wow-everlake-world-data: made from GPL-3.0 forever-db (QuestieDB's spawn points, "
           "CMaNGOS heights) and CC BY 4.0 data from EG Link (Data from Efficient Games, https://efficient.games); heights "
           "without a source from Everlake's own extracted maps. Game names belong to Blizzard Entertainment.")


def key(thing):
    return str(thing)


def dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


class Grid:
    """Points by map and cell, for 'anything within N yards'."""

    def __init__(self, cell=80):
        self.cell = cell
        self.cells = collections.defaultdict(list)

    def add(self, m, x, y, value=None):
        self.cells[(m, int(x // self.cell), int(y // self.cell))].append((x, y, value))

    def near(self, m, x, y, yards):
        cx, cy = int(x // self.cell), int(y // self.cell)
        r = int(yards // self.cell) + 1
        out = []
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for px, py, v in self.cells.get((m, cx + dx, cy + dy), ()):
                    if (px - x) ** 2 + (py - y) ** 2 <= yards * yards:
                        out.append((px, py, v))
        return out


def live_sightings(sources, cur):
    """(kind, id) -> Grid of positions live Forever players recorded: EG Link npcs.json (npcs, objects, approached) and
    creatures.json (deaths, combat log) of every live build, and loot windows."""
    with open(os.path.join(sources, "manifest.json")) as handle:
        folder = os.path.join(sources, json.load(handle)["current"]["eg-link"]["folder"], "data", "wowf")
    seen = collections.defaultdict(Grid)

    def add(kind, i, p):
        if not isinstance(p, dict) or not str(i).isdigit():
            return
        if p.get("worldX") is not None and p.get("instance") is not None:
            seen[(kind, int(i))].add(int(p["instance"]), float(p["worldX"]), float(p["worldY"]))
        elif p.get("map") is not None and p.get("x") is not None:
            seen[(kind, int(i))].add(int(p["map"]), float(p["x"]), float(p["y"]))
    for path in sorted(glob.glob(os.path.join(folder, "*", "npcs.json"))):
        with open(path) as handle:
            d = json.load(handle)
        for kind, sect in (("npc", "npcs"), ("object", "objects"), ("object", "approached")):
            for i, v in (d.get(sect) or {}).items():
                for p in (v or {}).get("positions") or []:
                    add(kind, i, p)
    for path in sorted(glob.glob(os.path.join(folder, "*", "creatures.json"))):
        with open(path) as handle:
            d = json.load(handle)
        for sect in ("creatures", "combatLog"):
            for i, v in (d.get(sect) or {}).items():
                for p in (v or {}).get("positions") or []:
                    add("npc", i, p)
    for r in candidates.rows(cur, f"SELECT k, data FROM {F}.src_eg_link WHERE tbl = 'loot' AND k LIKE %s", ("wowf/%/npc:%",)):
        m = re.search(r"/npc:(\d+)", r["k"])
        if m and "|spell" not in r["k"]:
            for p in (candidates.j(r["data"]) or {}).get("positions") or []:
                add("npc", m.group(1), p)
    return seen


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
    npc_ids = {g["npc"] for c in ("npcs_not_spawned", "extra_spots") for g in gaps[c]}
    obj_ids = {g["object"] for g in gaps["objects_not_spawned"]}

    # ---- the sources: forever-db's points, live sightings; the gap report's own point set (to know what it will say)
    fdb = collections.defaultdict(list)
    for r in rows(cur, f"SELECT data FROM {F}.src_forever_db WHERE tbl = 'spawn'"):
        d = candidates.j(r["data"])
        k = (d.get("kind"), candidates.as_int(d.get("id")))
        if (k[0] == "npc" and k[1] in npc_ids) or (k[0] == "object" and k[1] in obj_ids):
            fdb[k].append((int(d["map"]), float(d["x"]), float(d["y"]), None if d.get("z") is None else float(d["z"])))
    gap_points = collections.defaultdict(set)              # as gap_report.py builds `points` for NPCs
    for (kind, i), ps in fdb.items():
        if kind == "npc":
            gap_points[i] |= {(m, round(x, 1), round(y, 1)) for m, x, y, _ in ps}
    for r in rows(cur, f"SELECT id, data FROM {F}.src_eg_link WHERE tbl = 'npcs' AND id IN ({ids_sql(npc_ids)})"):
        for p in candidates.as_list((candidates.j(r["data"]) or {}).get("positions")):
            if isinstance(p, dict) and p.get("worldX") is not None and p.get("instance") is not None:
                gap_points[int(r["id"])].add((int(p["instance"]), round(float(p["worldX"]), 1), round(float(p["worldY"]), 1)))
    live = live_sightings(args.sources, cur)

    # ---- the world
    tpl = {r["entry"]: r for r in rows(cur, f"SELECT entry, name, npcflag, Classification, AIName, ScriptName FROM {W}creature_template "
                                            f"WHERE entry IN ({ids_sql(npc_ids)})")}
    otpl = {r["entry"]: r for r in rows(cur, f"SELECT entry, name, type, AIName, ScriptName FROM {W}gameobject_template "
                                             f"WHERE entry IN ({ids_sql(obj_ids)})")}
    questy = {r["id"] for t in ("creature_queststarter", "creature_questender")
              for r in rows(cur, f"SELECT DISTINCT id FROM {W}{t} WHERE id IN ({ids_sql(npc_ids)})")}
    equipped = {r["CreatureID"] for r in rows(cur, f"SELECT DISTINCT CreatureID FROM {W}creature_equip_template WHERE CreatureID IN ({ids_sql(npc_ids)})")}
    smart_npc = {r["p"] for r in rows(cur, f"SELECT DISTINCT action_param1 p FROM {W}smart_scripts WHERE action_type = 12")}
    smart_npc |= {r["entry"] for r in rows(cur, f"SELECT DISTINCT entry FROM {W}creature_summon_groups")}
    smart_obj = {r["p"] for r in rows(cur, f"SELECT DISTINCT action_param1 p FROM {W}smart_scripts WHERE action_type = 50")}
    spell_npc, spell_obj = set(), set()
    cur.execute(f"SELECT JSON_EXTRACT(data, '$.data.related.SpellEffect') FROM {F}.src_item_history WHERE tbl = 'spells'")
    for (effects,) in cur.fetchall():
        for e in candidates.j(effects) or []:
            if isinstance(e, dict) and e.get("EffectMiscValue"):
                if e.get("Effect") in NPC_SUMMON_EFFECTS:
                    spell_npc.add(e["EffectMiscValue"][0])
                elif e.get("Effect") in OBJECT_SUMMON_EFFECTS:
                    spell_obj.add(e["EffectMiscValue"][0])
    map_type = {r["id"]: candidates.as_int(candidates.j(r["data"]).get("InstanceType"))
                for r in rows(cur, f"SELECT id, data FROM {F}.src_wago WHERE tbl = 'Map'")}
    maps = {m for ps in fdb.values() for m, *_ in ps}
    spawns = Grid(BUILDING_YARDS * 8)                      # every fork spawn on those maps, with its height
    own = collections.defaultdict(list)                    # npc -> its fork spawns
    for table in ("creature", "gameobject"):
        cur.execute(f"SELECT id, map, position_x, position_y, position_z FROM {W}{table} WHERE map IN ({ids_sql(maps)})")
        for i, m, x, y, z in cur.fetchall():
            spawns.add(m, float(x), float(y), float(z))
    for r in rows(cur, f"SELECT * FROM {W}creature WHERE id IN ({ids_sql(npc_ids)})"):
        own[r["id"]].append(r)
    tops = {}
    for t, col in (("creature", "guid"), ("gameobject", "guid")):
        tops[t] = rows(cur, f"SELECT MAX({col}) AS m FROM {W}{t}")[0]["m"] or 0
        if tops[t] >= GUID_BASE:
            raise SystemExit(f"the fork's {t} guids reach {tops[t]}: they meet our block at {GUID_BASE}")
    # the commonest respawn and wandering of the fork's spawns, by classification and map; of objects, by type
    habits = collections.defaultdict(collections.Counter)
    cur.execute(f"SELECT t.Classification, c.map, c.spawntimesecs, c.wander_distance, c.MovementType FROM {W}creature c "
                f"JOIN {W}creature_template t ON t.entry = c.id WHERE c.map IN ({ids_sql(maps)}) AND c.MovementType IN (0, 1)")
    for cls, m, st, wd, mt in cur.fetchall():
        habits[("npc", cls, m)][(int(st), round(float(wd), 1), int(mt))] += 1
    types = {o["type"] for o in otpl.values()}
    cur.execute(f"SELECT t.type, g.spawntimesecs, g.animprogress, g.state FROM {W}gameobject g JOIN {W}gameobject_template t "
                f"ON t.entry = g.id WHERE t.type IN ({ids_sql(types)})")
    for typ, st, ap, state in cur.fetchall():
        habits[("object", typ)][(int(st), int(ap), int(state))] += 1

    sl = {"adds": collections.defaultdict(list), "review": [], "held": [], "outcomes": collections.defaultdict(dict)}

    def height(m, x, y, z):
        """(z, how) or (None, why)."""
        if z is not None:
            return z, "height forever-db (CMaNGOS)"
        if map_type.get(m) != 0:
            return None, "no height, and the map is a dungeon or battleground (the terrain doesn't hold its floors)"
        if ground.tile(m, x, y) is None:
            return None, "no height, and Everlake's maps have no terrain tile there"
        g = ground.ground(m, x, y)
        if g is None:
            return None, "no height, and the terrain has a hole there (a cave mouth or a building)"
        w = ground.water(m, x, y)
        if w is not None and w > g + 1:
            return None, "no height, and the point is in water"
        off = [round(v - g, 1) for _, _, v in spawns.near(m, x, y, BUILDING_YARDS) if abs(v - g) > BUILDING_OFF]
        if off:
            return None, (f"no height, and a fork spawn within {BUILDING_YARDS} yards stands off the ground (a building, bridge or "
                          f"cave: {off[0]:+} yards)")
        return round(g, 2), "height Everlake terrain"

    def confirmed(kind, i, ps):
        """forever-db points a live sighting confirms, one per spot."""
        grid = live.get((kind, i))
        out = []
        for m, x, y, z in sorted(ps):
            if grid and grid.near(m, x, y, SIGHTING_YARDS) and not any(o[0] == m and dist2(o[1:3], (x, y)) <= SAME_POINT ** 2 for o in out):
                out.append((m, x, y, z))
        return out

    def hold(cat, k, entry, reason, why=None):
        sl["held"].append(dict(entry, category=cat, reason=reason, why=why or reason))
        sl["outcomes"][cat][k] = "held back: " + reason

    def review(cat, k, entry, why):
        sl["review"].append(dict(entry, category=cat, why=why))
        sl["outcomes"][cat][k] = "review: " + why

    def why_held(i, kind, t, summoned_by_spell, summoned_by_smart, scripted_counts=True):
        if t is None:
            return "no template in the world"
        if TEST_NAME.search(str(t.get("name") or "")):
            return "a test or do-not-display one (its name says so)"
        if i in summoned_by_spell:
            return "a client spell summons it"
        if i in summoned_by_smart:
            return "the fork's SmartAI summons it"
        if scripted_counts and (t.get("AIName") or t.get("ScriptName")):
            return "it has a script (AIName or ScriptName)"
        return None

    # ---- NPCs: unspawned ones, and extra spots of spawned ones
    guid = {"creature": GUID_BASE, "gameobject": GUID_BASE}
    added = collections.defaultdict(list)                   # npc -> (map, x, y) of ours
    for cat in ("npcs_not_spawned", "extra_spots"):
        for g in sorted(gaps[cat], key=lambda g: g["npc"]):
            n, t = g["npc"], tpl.get(g["npc"])
            e = {"npc": n, "name": g["name"], "what": f"npc {n} {g['name']}", "points": len(fdb.get(("npc", n), ()))}
            if g.get("custom_sql"):
                hold(cat, key(n), e, "a fork custom file not loaded into the world yet writes this NPC's spawns")
                continue
            # a script only counts against an NPC the fork doesn't spawn: one it spawns already runs its script there
            why = why_held(n, "npc", t, spell_npc, smart_npc, scripted_counts=cat == "npcs_not_spawned")
            if why:
                hold(cat, key(n), e, why)
                continue
            ps = fdb.get(("npc", n), [])
            if cat == "extra_spots":
                far = {p[:3] for p in gap_report.far_points([p[:3] for p in ps], [(r["map"], r["position_x"], r["position_y"]) for r in own[n]],
                                                            gap_report.NEW_SPOT_YARDS)}
                ps = [p for p in ps if p[:3] in far]
            ok = confirmed("npc", n, ps)
            if not ok:
                hold(cat, key(n), e, "no live Forever sighting within 40 yards of its points (Classic data only)",
                     f"forever-db lists {len(ps)} point(s); no EG Link live sighting lies within {SIGHTING_YARDS} yards of any")
                continue
            unique = [UNIQUE_CLASSIFICATION[t["Classification"]]] if t["Classification"] in UNIQUE_CLASSIFICATION else []
            unique += [w for f, w in SERVICE_FLAGS.items() if int(t["npcflag"] or 0) & f]
            if n in questy and "gives quests" not in unique:
                unique.append("gives or ends quests")
            if unique and (cat == "extra_spots" or len(ok) > 1):
                review(cat, key(n), dict(e, points=[list(p) for p in ok]),
                       f"a unique NPC ({', '.join(unique)}) with {len(ok)} confirmed point(s)"
                       + (" next to the spawn it has" if cat == "extra_spots" else "") + ": it may be one NPC on a patrol path")
                continue
            rows_n, held_pts = [], []
            for m, x, y, z in ok:
                hz, how = height(m, x, y, z)
                if hz is None:
                    held_pts.append(how)
                    continue
                same_map = [r for r in own[n] if r["map"] == m]
                if cat == "extra_spots" and not same_map:
                    held_pts.append("the fork spawns this NPC only on another map, whose phases and difficulties don't carry over")
                    continue
                if cat == "npcs_not_spawned" and map_type.get(m) != 0:
                    held_pts.append("a new NPC in a dungeon or battleground needs its difficulties, which no source records")
                    continue
                if cat == "extra_spots":
                    near = min(same_map, key=lambda r: dist2((r["position_x"], r["position_y"]), (x, y)))
                    walks = int(near["MovementType"]) == 2
                    vals = {c: near[c] for c in ("spawnDifficulties", "phaseUseFlags", "PhaseId", "PhaseGroup", "terrainSwapMap",
                                                 "modelid", "equipment_id", "spawntimesecs")}
                    vals.update(wander_distance=0.0 if walks else round(float(near["wander_distance"]), 1),
                                MovementType=0 if walks else int(near["MovementType"]))
                    habit = f"as its fork spawn {near['guid']}" + (" (standing: that one walks a path)" if walks else "")
                else:
                    common = habits.get(("npc", t["Classification"], m))
                    st, wd, mt = common.most_common(1)[0][0] if common else (300, 0.0, 0)
                    vals = {"spawnDifficulties": "0", "phaseUseFlags": 0, "PhaseId": 0, "PhaseGroup": 0, "terrainSwapMap": -1,
                            "modelid": 0, "equipment_id": 1 if n in equipped else 0, "spawntimesecs": st, "wander_distance": wd,
                            "MovementType": mt}
                    habit = ("respawn and wandering as the fork's commonest for its classification on the map" if common
                             else "respawn 300 (no fork spawn of its classification on the map)")
                rows_n.append(dict(vals, id=n, map=m, zoneId=0, areaId=0, position_x=round(x, 2), position_y=round(y, 2),
                                   position_z=hz, orientation=0.0, currentwaypoint=0, VerifiedBuild=0,
                                   note=f"forever-db point; eg-link live sighting within {SIGHTING_YARDS} yd; {how}; {habit}"[:255],
                                   why=f"{g['name']} ({cat.replace('_', ' ')})"))
            if not rows_n:
                hold(cat, key(n), dict(e, points=[list(p) for p in ok]), held_pts[0].split(" (")[0] if "stands off" in held_pts[0]
                     else held_pts[0], "; ".join(dict.fromkeys(held_pts)))
                continue
            for r in rows_n:
                sl["adds"]["creature"].append(r)
                added[n].append((r["map"], r["position_x"], r["position_y"]))
            sl["outcomes"][cat][key(n)] = "added"
            if held_pts:
                sl["held"].append(dict(e, what=e["what"] + ": some points", category=cat, reason="some of its points have no usable height",
                                       why="; ".join(dict.fromkeys(held_pts))))

    # what the gap report will say afterwards: an NPC with our spawns may still have spots far from all of them
    for cat in ("npcs_not_spawned", "extra_spots"):
        for g in gaps[cat]:
            n = g["npc"]
            if not sl["outcomes"][cat].get(key(n), "").startswith("added"):
                continue
            ours = [(r["map"], r["position_x"], r["position_y"]) for r in own[n]] + added[n]
            far = gap_report.far_points(sorted(gap_points.get(n, ())), ours, gap_report.NEW_SPOT_YARDS)
            if far:
                why = (f"{len(far)} more spot(s) far from every spawn: no live sighting confirms them, or only players' positions "
                       "(EG Link) show them")
                sl["held"].append({"npc": n, "name": g["name"], "what": f"npc {n} {g['name']}: further spots", "category": "extra_spots",
                                   "reason": "further spots no live sighting confirms", "why": why})
                if cat == "npcs_not_spawned":
                    sl["outcomes"]["extra_spots"][key(n)] = "held back: further spots no live sighting confirms"
                    sl["outcomes"][cat][key(n)] = "added"
                else:
                    sl["outcomes"][cat][key(n)] = "held back: further spots no live sighting confirms"

    # ---- objects
    for g in sorted(gaps["objects_not_spawned"], key=lambda g: g["object"]):
        o, t = g["object"], otpl.get(g["object"])
        e = {"npc": o, "object": o, "name": g["name"], "what": f"object {o} {g['name']}", "points": len(fdb.get(("object", o), ()))}
        if g.get("custom_sql"):
            hold("objects_not_spawned", key(o), e, "a fork custom file not loaded into the world yet writes this object's spawns")
            continue
        why = why_held(o, "object", t, spell_obj, smart_obj)
        if why:
            hold("objects_not_spawned", key(o), e, why)
            continue
        ok = confirmed("object", o, fdb.get(("object", o), []))
        if not ok:
            hold("objects_not_spawned", key(o), e, "no live Forever sighting within 40 yards of its points (Classic data only)")
            continue
        common = habits.get(("object", t["type"]))
        st, anim, state = common.most_common(1)[0][0] if common else (300, 255, 1)
        rows_o, held_pts = [], []
        for m, x, y, z in ok:
            if map_type.get(m) != 0:
                held_pts.append("an object in a dungeon or battleground needs its difficulties, which no source records")
                continue
            hz, how = height(m, x, y, z)
            if hz is None:
                held_pts.append(how)
                continue
            rows_o.append({"id": o, "map": m, "zoneId": 0, "areaId": 0, "spawnDifficulties": "0", "phaseUseFlags": 0, "PhaseId": 0,
                           "PhaseGroup": 0, "terrainSwapMap": -1, "position_x": round(x, 2), "position_y": round(y, 2), "position_z": hz,
                           "orientation": 0.0, "rotation0": 0.0, "rotation1": 0.0, "rotation2": 0.0, "rotation3": 1.0,
                           "spawntimesecs": st, "animprogress": anim, "state": state, "VerifiedBuild": 0,
                           "note": f"forever-db point; eg-link live sighting within {SIGHTING_YARDS} yd; {how}; respawn, animation "
                                   "and state as the fork's commonest for its type"[:255], "why": g["name"]})
        if not rows_o:
            hold("objects_not_spawned", key(o), e, held_pts[0].split(" (")[0] if "stands off" in held_pts[0] else held_pts[0],
                 "; ".join(dict.fromkeys(held_pts)))
            continue
        sl["adds"]["gameobject"] += rows_o
        sl["outcomes"]["objects_not_spawned"][key(o)] = "added"
        rest = len(fdb.get(("object", o), ())) - len(rows_o)
        if rest > 0:      # objects have no "extra spots" gap: list the rest here so they aren't lost
            sl["held"].append(dict(e, what=e["what"] + ": its other points", category="objects_not_spawned",
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
    for r in rows(cur, "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE FROM information_schema.columns "
                       "WHERE table_schema = %s AND table_name IN (%s, %s) ORDER BY ORDINAL_POSITION", (schema, prefix + "creature", prefix + "gameobject")):
        col_info[r["TABLE_NAME"][len(prefix):]][r["COLUMN_NAME"]] = {
            "type": r["DATA_TYPE"], "ddl": r["COLUMN_TYPE"] + ("" if r["IS_NULLABLE"] == "YES" else " NOT NULL")}
    write(args, name, sl, pins, world_label, col_info, {c: len(v) for c, v in gaps.items()}, guid, ground.build(), tops)


def file_name(args):
    """Slice 4's file follows every other slice's file already in the folder for this date."""
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
    out = isql.file_header("Everlake world import, slice 4: spawns live Forever players saw that the world lacks", name, pins,
                           world_label, LICENCE)
    out += [isql.IMPORT_ROWS_DDL, ""]
    for table, cols in (("creature", CREATURE_COLUMNS), ("gameobject", OBJECT_COLUMNS)):
        guard = (f"NOT EXISTS (SELECT 1 FROM `{isql.IMPORT_ROWS}` r WHERE r.`tbl` = {isql.lit(table)} AND r.`k1` = s.`guid`) "
                 f"AND NOT EXISTS (SELECT 1 FROM `{table}` c WHERE c.`id` = s.`id` AND c.`map` = s.`map` "
                 f"AND (c.`position_x` - s.`position_x`) * (c.`position_x` - s.`position_x`) + (c.`position_y` - s.`position_y`) "
                 f"* (c.`position_y` - s.`position_y`) <= {SIGHTING_YARDS * SIGHTING_YARDS} AND NOT EXISTS (SELECT 1 FROM "
                 f"`{isql.IMPORT_ROWS}` o WHERE o.`tbl` = {isql.lit(table)} AND o.`k1` = c.`guid`))")
        out += isql.stage_block(
            table, cols, ["guid"], [{k: v for k, v in r.items() if k in cols + ["note", "why"]} for r in sl["adds"][table]], name, guard,
            f"{table}: spawns at points a live sighting confirms (while the fork has no spawn of the same {'NPC' if table == 'creature' else 'object'} "
            f"within {SIGHTING_YARDS} yards but ours, and never again once added: a spawn the fork removes stays removed)",
            col_info[table])
    text = "\n".join(out).rstrip() + "\n"
    path = os.path.join(sql_dir, name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            if handle.read() != text and not args.replace:
                raise SystemExit(f"{path} exists with other content. A deployed update file is never changed; if this one "
                                 "was never deployed, run again with --replace")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    manifest = {"slice": SLICE, "pins": pins, "world": world_label, "gaps": gap_counts, "maps_build": maps_build,
                "guid_base": GUID_BASE, "guids_used": {t: [GUID_BASE, guid[t] - 1] if guid[t] > GUID_BASE else None for t in guid},
                "fork_guid_top": tops,
                "files": [{"name": name, "kind": "import", "sha1": hashlib.sha1(text.encode()).hexdigest().upper()}],
                "adds": {t: [{k: v for k, v in r.items() if k != "why"} for r in rs] for t, rs in sorted(sl["adds"].items())},
                "fixes": [], "review": sl["review"], "held_back": sl["held"],
                "outcomes": {c: dict(sorted(v.items())) for c, v in sorted(sl["outcomes"].items())}}
    with open(os.path.join(meta_dir, "manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True)
    with open(os.path.join(meta_dir, "review.md"), "w") as handle:
        handle.write(listing("Slice 4: for a person (not in the files)", "Unique NPCs with several confirmed points, or an "
                             "extra spot next to the spawn they have: one NPC on a patrol path, or really several?", sl["review"]))
    with open(os.path.join(meta_dir, "held-back.md"), "w") as handle:
        handle.write(listing("Slice 4: held back", "Spawns that need something we don't have, and why. Nothing here was guessed.",
                             sl["held"]))
    print(f"wrote {path}: {len(sl['adds']['creature'])} creature and {len(sl['adds']['gameobject'])} gameobject spawns; "
          f"{len(sl['review'])} for review, {len(sl['held'])} held back (in {meta_dir})")


def listing(title, intro, items):
    out = [f"# {title}", "", intro, ""]
    groups = collections.defaultdict(list)
    for i in items:
        groups[i.get("reason") or i["category"]].append(i)
    for group, its in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out += [f"## {group} ({len(its)})", ""]
        for i in sorted(its, key=lambda x: (x["npc"], x["category"])):
            why = f": {i['why']}" if i.get("why") and i["why"] != group else ""
            pts = f", {i['points']} point(s)" if isinstance(i.get("points"), int) else ""
            out.append(f"- {i['what']} ({i['category']}{pts}){why}".replace("\n", " "))
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    main()
