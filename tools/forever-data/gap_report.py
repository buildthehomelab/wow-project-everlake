#!/usr/bin/env python3
"""What live WoW Forever has that Everlake's world database lacks or has differently, zone by zone.

    gap_report.py                         every zone
    gap_report.py --zone "Elwynn Forest"  one zone
    gap_report.py --out DIR               where everlake-gaps.md and .json go (default reports/)

Everlake (the Forever realm) runs the TrinityCore `forever` fork with its world release (forever-tdb-2026-10-14),
which load_tc.py keeps in acore_forever as the tc_* tables. Live Forever is every other loaded source (load_sources.py),
weighed by source_weights.py. Reads only; writes the two report files.

What it lists, per zone (the full list is CATEGORIES below):
- quests Forever has and the world release doesn't, split into seen in the live game (EG Link at a live build,
  QuestieTrace, ForeverDB "seen") and known only from client or beta data;
- quests whose name, givers or enders differ from what the sources agree on, and quests with no giver or no text;
- NPCs Forever spawns or uses that have no template, NPCs with a template but no spawn, and extra spawn spots;
- vendors whose stock the world lacks (EG Link's recorded stock against npc_vendor);
- objects missing or never spawned, NPCs whose loot lacks recorded drops, trainers missing spells, quests with no
  objective rows, missing reward items or no progress or completion text.

load_tc.py applies the fork's sql/custom world files on top of the release, as Everlake's worldserver does, and lists
them in tc_updates. A custom file that isn't applied yet (pinned after the last load_tc.py run) is not in tc_* : every gap
whose key rows such a file writes or changes is marked "custom SQL touches it", so it can be checked rather than trusted.
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import candidates  # noqa: E402
import source_weights  # noqa: E402
from load_sources import SOURCES, connect  # noqa: E402

F = candidates.F
WORLD = candidates.WORLD
LIVE_BUILD = 70790           # first live Forever build (launch, 2026-11-04); EG Link rows from it on count as seen live
NEW_SPOT_YARDS = 80          # a Forever spawn this far from every one of the world's spawns of that NPC is a new spot
TEST_NAME = re.compile(r"^\s*<|\[(?:DNT|PH|Never used)\]|zzOLD|\b(?:UNUSED|DEPRECATED|TEST|OLD)\b")   # capitals only: "The Old Ways" is real
LIVE_EVIDENCE = {"eg-link-live", "questietrace", "foreverdb-seen"}
EXAMPLES = 15                # items per category in the Markdown; the JSON has them all

CATEGORIES = [
    ("missing_quests_live", "Quests seen live, not in the world"),
    ("missing_quests_data", "Quests in client/beta data only, not in the world"),
    ("renamed_quests", "Quests named differently"),
    ("quests_no_giver", "Quests with no giver in the world"),
    ("quests_giver_differs", "Quests with other givers"),
    ("quests_no_ender", "Quests with no ender in the world"),
    ("quests_ender_differs", "Quests with other enders"),
    ("quests_no_text", "Quests with no quest text in the world"),
    ("missing_npcs", "NPCs Forever uses, no template in the world"),
    ("npcs_not_spawned", "NPCs with a template, never spawned"),
    ("extra_spots", "Extra spawn spots"),
    ("vendors_no_stock", "Vendors with no stock in the world"),
    ("vendor_items_missing", "Vendors missing some items"),
    ("objects_missing", "Objects Forever spawns or uses, no template in the world"),
    ("objects_not_spawned", "Objects with a template, never spawned"),
    ("npcs_no_loot", "NPCs with recorded drops and no loot table"),
    ("loot_items_missing", "NPCs whose loot table lacks recorded drops"),
    ("trainers_unlinked", "Trainers with no trainer list in the world"),
    ("trainer_spells_missing", "Trainers missing spells"),
    ("quests_no_objectives", "Quests with no objective rows in the world"),
    ("quest_rewards_missing", "Quests missing reward items"),
    ("quests_no_progress_text", "Quests with no progress text in the world"),
    ("quests_no_completion_text", "Quests with no completion text in the world"),
    ("flight_masters_unflagged", "Flight masters not flagged as one"),
]


def j(value):
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def build_no(value):
    try:
        return int(str(value or "0").split(".")[-1])
    except ValueError:
        return 0


def norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


class Zones:
    """Area id -> top zone, and world point -> zone through UiMapAssignment's bounds (smallest box wins)."""

    def __init__(self, cur):
        self.parent, self.names, self.maps = {}, {}, {}
        self.boxes = collections.defaultdict(list)
        for r in candidates.rows(cur, f"SELECT tbl, data FROM {F}.src_wago WHERE tbl IN ('AreaTable', 'Map', 'UiMapAssignment')"):
            d = j(r["data"])
            if r["tbl"] == "AreaTable":
                self.parent[int(d["ID"])] = int(d.get("ParentAreaID") or 0)
                self.names[int(d["ID"])] = d.get("AreaName_lang")
            elif r["tbl"] == "Map":
                self.maps[int(d["ID"])] = d.get("MapName_lang") or d.get("Directory")
        for r in candidates.rows(cur, f"SELECT data FROM {F}.src_wago WHERE tbl = 'UiMapAssignment'"):
            d = j(r["data"])
            area = int(d.get("AreaID") or 0)
            if area:
                x0, y0, x1, y1 = (float(d[f"Region_{i}"]) for i in (0, 1, 3, 4))
                self.boxes[int(d["MapID"])].append(((x1 - x0) * (y1 - y0), x0, y0, x1, y1, area))
        for boxes in self.boxes.values():
            boxes.sort()

    def top(self, area):
        seen = 0
        while area and self.parent.get(area) and seen < 10:
            area, seen = self.parent[area], seen + 1
        return area or 0

    def at(self, map_id, x, y):
        for _, x0, y0, x1, y1, area in self.boxes.get(map_id, ()):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return self.top(area)
        return -map_id - 1          # no zone box: keyed by map instead

    def name(self, zone):
        if not zone:
            return "No zone"
        if zone < 0:
            return f"{self.maps.get(-zone - 1, 'map')} (map {-zone - 1})"
        return self.names.get(zone) or f"area {zone}"

    def main(self, points):
        counts = collections.Counter(self.at(m, x, y) for m, x, y in points)
        return counts.most_common(1)[0][0] if counts else None


KEY_COLUMNS = {"entry", "id", "quest", "questid", "creatureid", "trainerid"}
QUEST_ID_TABLES = {"quest_template", "quest_template_addon", "quest_offer_reward", "quest_request_items", "quest_details",
                   "quest_template_classic_level", "quest_classic_level", "quest_classic_money"}     # tables whose ID is a quest id
FIRST_KEY = {**{t: "id" for t in QUEST_ID_TABLES}, "creature_template": "entry", "creature_template_addon": "entry", "npc_vendor": "entry",
             "creature_template_difficulty": "entry", "creature_template_model": "creatureid"}


def quest_evidence(cur):
    """({quest id: {evidence labels}}, {quest id: area id}): every quest any source names, which sources name it
    (eg-link-live, questietrace, foreverdb-seen ... see LIVE_EVIDENCE), and the area the sources place it in."""
    evidence = collections.defaultdict(set)
    area_hint = {}
    for r in candidates.rows(cur, f"SELECT id, JSON_EXTRACT(data, '$.zone_area') AS area FROM {F}.src_forever_db WHERE tbl = 'quest'"):
        evidence[r["id"]].add("forever-db")
        if (candidates.as_int(r["area"]) or 0) > 0:
            area_hint[r["id"]] = candidates.as_int(r["area"])
    eg_area = {}          # EG Link's zoneAreaId, newest build that has one
    for r in candidates.rows(cur, f"SELECT id, JSON_UNQUOTE(JSON_EXTRACT(data, '$._build')) AS build, "
                                  f"JSON_EXTRACT(data, '$.zoneAreaId') AS area FROM {F}.src_eg_link WHERE tbl = 'quests.enUS'"):
        b = build_no(r["build"])
        evidence[r["id"]].add("eg-link-live" if b >= LIVE_BUILD else "eg-link-beta")
        area = candidates.as_int(r["area"]) or 0
        if area > 0 and (r["id"] not in eg_area or b >= eg_area[r["id"]][0]):
            eg_area[r["id"]] = (b, area)
    for qid, (_, area) in eg_area.items():
        area_hint.setdefault(qid, area)
    for tbl, label in ((candidates.TRACE_QUEST, "questietrace"), (candidates.BASE_QUEST, "questiedb")):
        for r in candidates.rows(cur, f"SELECT DISTINCT id FROM {F}.src_questiedb WHERE tbl = %s AND id IS NOT NULL", (tbl,)):
            evidence[r["id"]].add(label)
    for tbl, label in (("QuestForever.qfQuests", "foreverdb"), ("QuestForever.qfSeen", "foreverdb-seen")):
        for r in candidates.rows(cur, f"SELECT DISTINCT id FROM {F}.src_foreverdb_net WHERE tbl = %s AND id IS NOT NULL", (tbl,)):
            evidence[r["id"]].add(label)
    for r in candidates.rows(cur, f"SELECT id FROM {F}.src_wowhead_tooltips WHERE tbl = 'quest' "
                                  f"AND JSON_UNQUOTE(JSON_EXTRACT(data, '$.status')) = 'ok'"):
        evidence[r["id"]].add("wowhead")
    evidence = {int(k): v for k, v in evidence.items() if k is not None}
    return evidence, area_hint


def custom_sql_mentions(sources, applied=frozenset()):
    """{(table, key column): ids} that the fork's sql/custom world files the release doesn't already hold write or change: the key columns of INSERT and
    REPLACE rows, and `key = N` / `key IN (...)` in UPDATE and DELETE conditions. A hint, not a full SQL parse: an id
    found here means the custom files touch that row, so the gap may already be handled there."""
    with open(os.path.join(sources, "manifest.json")) as handle:
        pin = json.load(handle)["current"].get("tc-forever")
    out = collections.defaultdict(set)
    if not pin:
        return out, None
    folder = os.path.join(sources, pin["folder"], "sql", "custom", "world")
    if not os.path.isdir(folder):
        return out, None
    head = re.compile(r"\b(UPDATE|INSERT\s+(?:IGNORE\s+)?INTO|REPLACE\s+INTO|DELETE\s+FROM)\s+`?(?:\w+`?\.`?)?(\w+)`?\s*", re.I)
    cond = re.compile(r"`?\b(\w+)\b`?\s*(?:=\s*(\d+)\b|IN\s*\(([^)]*)\))", re.I)
    files = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".sql") or name in applied:
            continue
        files.append(name)
        with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as handle:
            text = re.sub(r"--[^\n]*", "", handle.read())
        for statement in text.split(";"):
            m = head.search(statement)
            if not m:
                continue
            verb, table, rest = m.group(1).upper(), m.group(2).lower(), statement[m.end():]
            if verb.startswith(("INSERT", "REPLACE")):
                cols = re.match(r"\(([^)]*)\)\s*VALUES", rest, re.I)
                names = [c.strip(" `").lower() for c in cols.group(1).split(",")] if cols else None
                values = rest[rest.upper().index("VALUES") + 6:] if "VALUES" in rest.upper() else ""
                for row in re.findall(r"\(([^()]*)\)", values):
                    cells = [c.strip() for c in row.split(",")]
                    if names:
                        picks = [(n, cells[k]) for k, n in enumerate(names) if n in KEY_COLUMNS and k < len(cells)]
                    else:       # no column list: only tables whose first column is the key
                        first = FIRST_KEY.get(table)
                        picks = [(first, cells[0])] if first and cells else []
                    for col, v in picks:
                        if re.fullmatch(r"\d+", v):
                            out[(table, col)].add(int(v))
            else:
                where = re.split(r"\bWHERE\b", rest, maxsplit=1, flags=re.I)
                for col, one, many in cond.findall(where[1] if len(where) > 1 else ""):
                    if col.lower() in KEY_COLUMNS:
                        out[(table, col.lower())].update(int(n) for n in re.findall(r"\d+", one or many or ""))
    return out, {"label": pin["label"], "files": files}


def newest_windows(cur, tbl):
    """EG Link's newest vendor or trainer window per NPC that lists anything: {npc: (product, build, data)}. The highest
    build wins; on a tie the live product (wowf) wins over the beta, so the choice doesn't depend on row order.
    import_slice3.py reads the same windows."""
    field = {"vendors": "entries", "trainers": "services"}[tbl]
    out = {}
    for r in candidates.rows(cur, f"SELECT id, data FROM {F}.src_eg_link WHERE tbl = %s AND id IS NOT NULL", (tbl,)):
        d = j(r["data"]) or {}
        listed = d.get(field)
        if not (isinstance(listed, dict) and listed) and not (isinstance(listed, list) and listed):
            continue
        rank = (build_no(d.get("_build")), d.get("_product") == "wowf")
        if int(r["id"]) not in out or rank >= out[int(r["id"])][0]:
            out[int(r["id"])] = (rank, d)
    return {npc: (d.get("_product"), rank[0], d) for npc, (rank, d) in out.items()}


def taught_spell_aliases(cur):
    """Map a trainer's teaching spell to the spell it grants in the pinned Forever client."""
    aliases = collections.defaultdict(set)
    for row in candidates.rows(cur, f"""SELECT
            CAST(data->>'$.SpellID' AS UNSIGNED) AS teacher,
            CAST(data->>'$.EffectTriggerSpell' AS SIGNED) AS learned
        FROM {F}.src_wago
        WHERE tbl = 'SpellEffect' AND data->>'$.Effect' = '36' AND data->>'$.DifficultyID' = '0'"""):
        # Effect 36 is SPELL_EFFECT_LEARN_SPELL. Other triggered spells are not trainer aliases.
        if row["teacher"] and row["learned"] and row["learned"] > 0:
            aliases[row["teacher"]].add(row["learned"])
    return aliases


def set_world(world):
    """Compare another copy of the world: SCHEMA.PREFIX, e.g. acore_world_dryrun.elstep_ (names checked: they go into SQL)."""
    global WORLD
    if not re.fullmatch(r"\w+\.\w*", world):
        raise SystemExit(f"--world {world!r}: expected SCHEMA.PREFIX")
    WORLD = candidates.WORLD = world


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--zone", help="only this top-level zone (AreaTable name)")
    ap.add_argument("--sources", default=SOURCES, help="the pinned sources folder (for the fork's sql/custom files)")
    ap.add_argument("--out", default=os.path.join(HERE, "reports"))
    ap.add_argument("--world", default=WORLD, help="the world's tables as SCHEMA.PREFIX (default acore_forever.tc_, the fork's "
                                                   "world; a dry run's world is acore_world_dryrun.<prefix>)")
    args = ap.parse_args()
    set_world(args.world)
    conn = connect()
    cur = conn.cursor()
    zones = Zones(cur)
    try:
        applied = {r["name"] for r in candidates.rows(cur, f"SELECT name FROM {WORLD}updates")}
    except Exception as error:  # noqa: BLE001
        if "1146" not in str(error) and "doesn't exist" not in str(error):
            raise
        raise SystemExit(f"{WORLD}updates is missing: run load_tc.py --force once so the release's update list is kept")
    mentions, custom = custom_sql_mentions(args.sources, applied)

    def quest_touched(qid):
        return any(qid in ids for (t, col), ids in mentions.items()
                   if (t in QUEST_ID_TABLES and col == "id") or (t.startswith("quest_") and col == "questid")
                   or (t.endswith(("queststarter", "questender")) and col == "quest"))

    def touched(table_cols, i):
        return any(i in mentions.get(tc, ()) for tc in table_cols)

    def npc_touched(nid):
        return any(nid in ids for (t, col), ids in mentions.items()
                   if (t.startswith("creature_template") and col in ("entry", "creatureid")) or (t == "creature" and col == "id")
                   or (t == "npc_vendor" and col == "entry"))

    # ---- live Forever's quests: every id any source names, with what each source says about it
    evidence, area_hint = quest_evidence(cur)

    tc_q = {r["ID"]: r for r in candidates.rows(cur, f"SELECT ID, LogTitle, QuestSortID, QuestDescription FROM {WORLD}quest_template "
                                                     f"WHERE ID IN ({candidates.ids_sql(evidence)})")}

    def tc_rel(tables):
        out = collections.defaultdict(set)
        for table in tables:
            kind = "npc" if table.startswith("creature") else "object"
            for r in candidates.rows(cur, f"SELECT id, quest FROM {WORLD}{table} WHERE quest IN ({candidates.ids_sql(evidence)})"):
                out[r["quest"]].add((kind, r["id"]))
        return out
    tc_start = tc_rel(("creature_queststarter", "gameobject_queststarter"))
    tc_end = tc_rel(("creature_questender", "gameobject_questender"))

    # ---- where Forever's NPCs stand (forever-db spawns, EG Link sightings)
    points = collections.defaultdict(set)
    for r in candidates.rows(cur, f"SELECT data FROM {F}.src_forever_db WHERE tbl = 'spawn' "
                                  f"AND JSON_UNQUOTE(JSON_EXTRACT(data, '$.kind')) = 'npc'"):
        d = j(r["data"])
        if candidates.as_int(d.get("id")) is not None and d.get("map") is not None and d.get("x") is not None:
            points[int(d["id"])].add((int(d["map"]), round(float(d["x"]), 1), round(float(d["y"]), 1)))
    for r in candidates.rows(cur, f"SELECT id, data FROM {F}.src_eg_link WHERE tbl = 'npcs' AND id IS NOT NULL"):
        for p in candidates.as_list(j(r["data"]).get("positions")):
            if isinstance(p, dict) and p.get("worldX") is not None and p.get("instance") is not None:
                points[int(r["id"])].add((int(p["instance"]), round(float(p["worldX"]), 1), round(float(p["worldY"]), 1)))
    print(f"quests: {len(evidence)} known to Forever's sources, {len(tc_q)} of them in the world; voting ...", flush=True)
    qc = candidates.quests(cur, set(evidence))

    def others(cands):
        return [c for c in cands if not c[1].startswith("tc-")]

    def resolve(field, cands, setwise=False):
        return (source_weights.resolve_set if setwise else source_weights.resolve)(field, others(cands))

    found = collections.defaultdict(lambda: collections.defaultdict(list))
    quest_zone, skipped_test, quest_npcs = {}, 0, collections.defaultdict(set)
    for qid in sorted(evidence):
        fields = qc.get(qid, {})
        name = resolve("name", fields.get("name", []))
        title = (name or {}).get("value") or (tc_q.get(qid) or {}).get("LogTitle")
        if title and TEST_NAME.search(str(title)):
            skipped_test += 1
            continue
        givers = resolve("quest_giver", fields.get("quest_giver", []), setwise=True)
        enders = resolve("quest_ender", fields.get("quest_ender", []), setwise=True)
        g_members = {tuple(m) for m in (givers or {}).get("members", []) if isinstance(m, (list, tuple)) and m[0] in ("npc", "object")}
        e_members = {tuple(m) for m in (enders or {}).get("members", []) if isinstance(m, (list, tuple)) and m[0] in ("npc", "object")}
        # zone: forever-db's area, EG Link's, the world's QuestSortID (an area when positive); else where a giver stands
        area = area_hint.get(qid) or (candidates.as_int((tc_q.get(qid) or {}).get("QuestSortID")) or 0)
        zone = zones.top(area) if area > 0 and area in zones.names else 0
        if not zone:
            spots = [p for kind, nid in sorted(g_members | e_members) if kind == "npc" for p in points.get(nid, ())]
            zone = zones.main(spots) or 0
        quest_zone[qid] = zone
        ev = sorted(evidence[qid])
        live = bool(LIVE_EVIDENCE & evidence[qid])
        item_started = any(isinstance(m, (list, tuple)) and m[0] == "item" for m in (givers or {}).get("members", []))
        for kind, nid in g_members | e_members:
            if kind == "npc":
                quest_npcs[nid].add(qid)
        item = {"quest": qid, "name": title, "evidence": ev,
                "custom_sql": quest_touched(qid)}
        if qid not in tc_q:
            item["givers"] = sorted(g_members)
            found[zone]["missing_quests_live" if live else "missing_quests_data"].append(item)
            continue
        tc = tc_q[qid]
        if name and not name["classic_only"] and norm(name["value"]) != norm(tc["LogTitle"]):
            found[zone]["renamed_quests"].append(dict(item, world=tc["LogTitle"], sources=name["sources"], close_call=name["conflict"]))
        for members, world, gone, differs, setv in ((g_members, tc_start.get(qid, set()), "quests_no_giver", "quests_giver_differs", givers),
                                                    (e_members, tc_end.get(qid, set()), "quests_no_ender", "quests_ender_differs", enders)):
            if not members or (gone == "quests_no_giver" and item_started):
                continue
            if not world:
                found[zone][gone].append(dict(item, forever=sorted(members)))
            elif members != world and not setv["classic_only"]:
                found[zone][differs].append(dict(item, forever=sorted(members), world=sorted(world)))
        if not (tc["QuestDescription"] or "").strip() and resolve("quest_text", fields.get("quest_text", [])):
            found[zone]["quests_no_text"].append(item)

    # ---- NPCs Forever spawns, uses as quest givers/enders, or sells from
    stock = {}
    for npc, (_, b, d) in newest_windows(cur, "vendors").items():
        entries = d.get("entries") or {}
        entries = entries.values() if isinstance(entries, dict) else entries if isinstance(entries, list) else []
        items = {candidates.as_int(e.get("itemId")) for e in entries if isinstance(e, dict)} - {None}
        if items:
            stock[npc] = (b, items)
    npc_ids = set(points) | set(quest_npcs) | set(stock)
    tc_npc = {r["entry"]: r["name"] for r in candidates.rows(cur, f"SELECT entry, name FROM {WORLD}creature_template "
                                                                    f"WHERE entry IN ({candidates.ids_sql(npc_ids)})")}
    tc_points = collections.defaultdict(list)
    for r in candidates.rows(cur, f"SELECT id, map, position_x, position_y FROM {WORLD}creature WHERE id IN ({candidates.ids_sql(npc_ids)})"):
        tc_points[r["id"]].append((r["map"], float(r["position_x"]), float(r["position_y"])))
    tc_stock, refs = collections.defaultdict(set), collections.defaultdict(set)
    for r in candidates.rows(cur, f"SELECT entry, item FROM {WORLD}npc_vendor WHERE type = 1"):
        (refs[r["entry"]].add(-r["item"]) if r["item"] < 0 else tc_stock[r["entry"]].add(r["item"]))
    for entry in list(refs):                  # a negative item lists another vendor's stock; follow the chain
        todo, seen = list(refs[entry]), {entry}
        while todo:
            other = todo.pop()
            if other not in seen:
                seen.add(other)
                tc_stock[entry] |= tc_stock.get(other, set())
                todo.extend(refs.get(other, ()))
    print(f"npcs: {len(npc_ids)} Forever spawns, uses or sells from; {len(tc_npc)} have a template in the world; voting ...", flush=True)
    nc = candidates.npcs(cur, npc_ids)

    def npc_zone(nid):
        z = zones.main(points.get(nid) or tc_points.get(nid) or ())
        if z is None:
            z = next((quest_zone[q] for q in sorted(quest_npcs.get(nid, ())) if quest_zone.get(q)), 0)
        return z

    skipped_test_npcs = 0
    for nid in sorted(npc_ids):
        name = resolve("name", nc.get(nid, {}).get("name", []))
        title = (name or {}).get("value") or tc_npc.get(nid)
        if title and TEST_NAME.search(str(title)):
            skipped_test_npcs += 1
            continue
        zone = npc_zone(nid)
        item = {"npc": nid, "name": title, "custom_sql": npc_touched(nid)}
        if nid not in tc_npc:
            found[zone]["missing_npcs"].append(dict(item, spots=len(points.get(nid, ())), quests=sorted(quest_npcs.get(nid, ())),
                                                    sells=len(stock.get(nid, (0, ()))[1])))
            continue
        if points.get(nid) and not tc_points.get(nid):
            found[zone]["npcs_not_spawned"].append(dict(item, spots=len(points[nid])))
        elif points.get(nid):
            far = far_points(points[nid], tc_points[nid], NEW_SPOT_YARDS)
            if far:
                found[zone]["extra_spots"].append(dict(item, spots=len(far), world_spawns=len(tc_points[nid])))
        if nid in stock:
            want = stock[nid][1]
            if not tc_stock.get(nid):
                found[zone]["vendors_no_stock"].append(dict(item, items=len(want), build=stock[nid][0]))
            elif want - tc_stock[nid]:
                found[zone]["vendor_items_missing"].append(dict(item, items=sorted(want - tc_stock[nid]), build=stock[nid][0]))

    # ---- the rest of the world: objects, loot, trainers, quest objectives, rewards and texts, flight masters
    def tc_spawns(table, ids):
        out = collections.defaultdict(list)
        for r in candidates.rows(cur, f"SELECT id, map, position_x, position_y FROM {WORLD}{table} WHERE id IN ({candidates.ids_sql(ids)})"):
            out[r["id"]].append((r["map"], float(r["position_x"]), float(r["position_y"])))
        return out

    def zone_of(own, world, quests=()):
        z = zones.main(own or world or ())
        if z is None:
            z = next((quest_zone[q] for q in sorted(quests) if quest_zone.get(q)), 0)
        return z

    # objects Forever spawns, or uses as quest givers and enders
    obj_points, obj_quests, obj_names = collections.defaultdict(set), collections.defaultdict(set), {}
    for r in candidates.rows(cur, f"SELECT data FROM {F}.src_forever_db WHERE tbl = 'spawn' "
                                  f"AND JSON_UNQUOTE(JSON_EXTRACT(data, '$.kind')) = 'object'"):
        d = j(r["data"])
        if candidates.as_int(d.get("id")) is not None and d.get("map") is not None and d.get("x") is not None:
            obj_points[int(d["id"])].add((int(d["map"]), float(d["x"]), float(d["y"])))
    for r in candidates.rows(cur, f"SELECT id AS quest, JSON_EXTRACT(data, '$.id') AS obj FROM {F}.src_forever_db "
                                  f"WHERE tbl IN ('quest_start', 'quest_end') AND JSON_UNQUOTE(JSON_EXTRACT(data, '$.kind')) = 'object'"):
        if candidates.as_int(r["obj"]) is not None and r["quest"] in quest_zone:
            obj_quests[candidates.as_int(r["obj"])].add(r["quest"])
    obj_ids = set(obj_points) | set(obj_quests)
    for r in candidates.rows(cur, f"SELECT id, JSON_UNQUOTE(JSON_EXTRACT(data, '$.name')) AS name FROM {F}.src_forever_db "
                                  f"WHERE tbl = 'object' AND id IN ({candidates.ids_sql(obj_ids)})"):
        obj_names[r["id"]] = r["name"]
    tc_obj = {r["entry"]: r["name"] for r in candidates.rows(cur, f"SELECT entry, name FROM {WORLD}gameobject_template "
                                                                    f"WHERE entry IN ({candidates.ids_sql(obj_ids)})")}
    tc_obj_points = tc_spawns("gameobject", obj_ids)
    skipped_test_objects = 0
    for oid in sorted(obj_ids):
        title = obj_names.get(oid) or tc_obj.get(oid)
        if title and TEST_NAME.search(str(title)):
            skipped_test_objects += 1
            continue
        zone = zone_of(obj_points.get(oid), tc_obj_points.get(oid), obj_quests.get(oid, ()))
        item = {"object": oid, "name": title, "spots": len(obj_points.get(oid, ())), "quests": sorted(obj_quests.get(oid, ())),
                "custom_sql": touched((("gameobject_template", "entry"), ("gameobject", "id")), oid)}
        if oid not in tc_obj:
            found[zone]["objects_missing"].append(item)
        elif obj_points.get(oid) and not tc_obj_points.get(oid):
            found[zone]["objects_not_spawned"].append(item)

    # NPCs: loot (forever-db drop lists, EG Link kill records), trainers (EG Link), flight masters (EG Link)
    drops = collections.defaultdict(set)
    for r in candidates.rows(cur, f"SELECT JSON_EXTRACT(data, '$.id') AS npc, JSON_EXTRACT(data, '$.item') AS item FROM {F}.src_forever_db "
                                  f"WHERE tbl = 'item_source' AND JSON_UNQUOTE(JSON_EXTRACT(data, '$.kind')) = 'npc'"):
        if candidates.as_int(r["npc"]) is not None and candidates.as_int(r["item"]) is not None:
            drops[candidates.as_int(r["npc"])].add(candidates.as_int(r["item"]))
    for r in candidates.rows(cur, f"SELECT k, JSON_EXTRACT(data, '$.items') AS items FROM {F}.src_eg_link WHERE tbl = 'loot'"):
        m = re.search(r"/npc:(\d+)", r["k"] or "")
        if "|spell:" in (r["k"] or ""):
            continue                     # skinning, gathering or pick-pocketing loot, not what the kill drops
        items = j(r["items"]) if r["items"] else None
        if m and isinstance(items, dict):
            drops[int(m.group(1))] |= {int(i) for i in items if str(i).isdigit()}
    teach = {}
    for npc, (_, b, d) in newest_windows(cur, "trainers").items():
        services = d.get("services")
        spells = {int(k) for k in services if str(k).isdigit()} if isinstance(services, dict) else set()
        if spells:
            teach[npc] = (b, spells)
    flight = {r["id"] for r in candidates.rows(cur, f"SELECT DISTINCT id FROM {F}.src_eg_link WHERE tbl = 'flights' AND id IS NOT NULL")}
    more = (set(drops) | set(teach) | flight) - set(tc_npc) - npc_ids
    tc_npc.update({r["entry"]: r["name"] for r in candidates.rows(cur, f"SELECT entry, name FROM {WORLD}creature_template "
                                                                         f"WHERE entry IN ({candidates.ids_sql(more)})")})
    for nid, pts in tc_spawns("creature", more - set(tc_points)).items():
        tc_points[nid] = pts
    fdb_npc = {r["id"]: r["name"] for r in candidates.rows(cur, f"SELECT id, JSON_UNQUOTE(JSON_EXTRACT(data, '$.name')) AS name "
                                                               f"FROM {F}.src_forever_db WHERE tbl = 'npc' AND id IN ({candidates.ids_sql(more)})")}
    with_tpl = {n for n in set(drops) | set(teach) | flight if n in tc_npc}
    loot_id = {}
    for r in candidates.rows(cur, f"SELECT Entry, DifficultyID, LootID FROM {WORLD}creature_template_difficulty "
                                  f"WHERE LootID > 0 AND Entry IN ({candidates.ids_sql(set(drops) & with_tpl)}) ORDER BY DifficultyID DESC"):
        if r["DifficultyID"] == 0 or r["Entry"] not in loot_id:
            loot_id[r["Entry"]] = r["LootID"]          # the open-world row when there is one, else a dungeon difficulty
    direct, links = collections.defaultdict(set), collections.defaultdict(set)     # loot id -> items / reference ids
    for r in candidates.rows(cur, f"SELECT Entry, ItemType, Item FROM {WORLD}creature_loot_template "
                                  f"WHERE Entry IN ({candidates.ids_sql({v for v in loot_id.values() if v})})"):
        if r["ItemType"] in (0, 1):     # 2 currency, 3 tracking quest: not item drops
            (links if r["ItemType"] == 1 else direct)[r["Entry"]].add(r["Item"])
    ref_items, ref_links, todo = collections.defaultdict(set), collections.defaultdict(set), {x for v in links.values() for x in v}
    loaded = set()
    while todo - loaded:                      # reference lists can name further reference lists
        batch = todo - loaded
        loaded |= batch
        for r in candidates.rows(cur, f"SELECT Entry, ItemType, Item FROM {WORLD}reference_loot_template WHERE Entry IN ({candidates.ids_sql(batch)})"):
            if r["ItemType"] == 1:
                ref_links[r["Entry"]].add(r["Item"])
                todo.add(r["Item"])
            elif r["ItemType"] == 0:
                ref_items[r["Entry"]].add(r["Item"])

    def loot_items(lid):
        got, stack, seen = set(direct.get(lid, ())), list(links.get(lid, ())), set()
        while stack:
            x = stack.pop()
            if x not in seen:
                seen.add(x)
                got |= ref_items.get(x, set())
                stack.extend(ref_links.get(x, ()))
        return got

    trainer_of = collections.defaultdict(set)
    for r in candidates.rows(cur, f"SELECT CreatureID, TrainerID FROM {WORLD}creature_trainer WHERE CreatureID IN ({candidates.ids_sql(teach)})"):
        trainer_of[r["CreatureID"]].add(r["TrainerID"])
    aliases = taught_spell_aliases(cur)
    taught = collections.defaultdict(set)
    for r in candidates.rows(cur, f"SELECT TrainerId, SpellId FROM {WORLD}trainer_spell "
                                  f"WHERE TrainerId IN ({candidates.ids_sql({t for v in trainer_of.values() for t in v})})"):
        taught[r["TrainerId"]].add(r["SpellId"])
        taught[r["TrainerId"]].update(aliases.get(r["SpellId"], ()))
    flags = {r["entry"]: int(r["npcflag"]) for r in candidates.rows(cur, f"SELECT entry, npcflag FROM {WORLD}creature_template "
                                                                       f"WHERE entry IN ({candidates.ids_sql(flight)})")}
    for nid in sorted(with_tpl):
        title = tc_npc.get(nid) or fdb_npc.get(nid)
        if title and TEST_NAME.search(str(title)):
            continue
        zone = zone_of(points.get(nid), tc_points.get(nid), quest_npcs.get(nid, ()))
        item = {"npc": nid, "name": title, "custom_sql": npc_touched(nid)}
        if nid in drops:
            lid = loot_id.get(nid)
            if not lid:
                found[zone]["npcs_no_loot"].append(dict(item, items=sorted(drops[nid])))
            elif drops[nid] - loot_items(lid):
                found[zone]["loot_items_missing"].append(dict(item, items=sorted(drops[nid] - loot_items(lid)), loot_id=lid,
                                                              custom_sql=item["custom_sql"] or touched((("creature_loot_template", "entry"),), lid)))
        if nid in teach:
            lists = trainer_of.get(nid, set())
            touched_trainer = item["custom_sql"] or touched((("creature_trainer", "creatureid"),), nid) \
                or any(touched((("trainer_spell", "trainerid"), ("trainer", "id")), t) for t in lists)
            if not lists:
                found[zone]["trainers_unlinked"].append(dict(item, spells=len(teach[nid][1]), custom_sql=touched_trainer))
            else:
                short = teach[nid][1] - set().union(*(taught[t] for t in lists))
                if short:
                    found[zone]["trainer_spells_missing"].append(dict(item, items=sorted(short), build=teach[nid][0], custom_sql=touched_trainer))
        if nid in flight and not flags.get(nid, 0) & 8192:
            found[zone]["flight_masters_unflagged"].append(item)

    # quests the world has: objectives, reward items, progress and completion text
    world_q = {qid for qid in quest_zone if qid in tc_q}
    with_obj = {r["QuestID"] for r in candidates.rows(cur, f"SELECT DISTINCT QuestID FROM {WORLD}quest_objectives WHERE QuestID IN ({candidates.ids_sql(world_q)})")}
    want_obj = set()
    for r in candidates.rows(cur, f"SELECT id, data FROM {F}.src_eg_link WHERE tbl = 'objectives' AND id IN ({candidates.ids_sql(world_q)})"):
        d = j(r["data"])
        if isinstance(d, dict) and any(k.isdigit() and isinstance(v, dict) and v.get("type") for k, v in d.items()):
            want_obj.add(r["id"])
    want_obj |= {r["id"] for r in candidates.rows(cur, f"SELECT DISTINCT id FROM {F}.src_forever_db WHERE tbl = 'quest_objective' AND id IN ({candidates.ids_sql(world_q)})")}
    rewards = collections.defaultdict(set)
    for r in candidates.rows(cur, f"SELECT id, JSON_EXTRACT(data, '$.id') AS item FROM {F}.src_forever_db WHERE tbl = 'quest_reward' "
                                  f"AND JSON_UNQUOTE(JSON_EXTRACT(data, '$.kind')) IN ('item', 'choice') AND id IN ({candidates.ids_sql(world_q)})"):
        if candidates.as_int(r["item"]):
            rewards[r["id"]].add(candidates.as_int(r["item"]))
    cols = ", ".join([f"RewardItem{i}" for i in range(1, 5)] + [f"RewardChoiceItemID{i}" for i in range(1, 7)])
    world_rewards = {r["ID"]: {v for k, v in r.items() if k != "ID" and v} for r in candidates.rows(
        cur, f"SELECT ID, {cols} FROM {WORLD}quest_template WHERE ID IN ({candidates.ids_sql(rewards)})")}
    text_kinds = collections.defaultdict(set)
    for r in candidates.rows(cur, f"SELECT id, JSON_KEYS(data) AS keys_ FROM {F}.src_eg_link WHERE tbl = 'texts.enUS' AND id IN ({candidates.ids_sql(world_q)})"):
        text_kinds[r["id"]] |= set(j(r["keys_"]) or ())
    progress = {r["ID"]: (r["CompletionText"] or "").strip() for r in candidates.rows(
        cur, f"SELECT ID, CompletionText FROM {WORLD}quest_request_items WHERE ID IN ({candidates.ids_sql(text_kinds)})")}
    completion = {r["ID"]: (r["RewardText"] or "").strip() for r in candidates.rows(
        cur, f"SELECT ID, RewardText FROM {WORLD}quest_offer_reward WHERE ID IN ({candidates.ids_sql(text_kinds)})")}
    names = {qid: tc_q[qid]["LogTitle"] for qid in world_q}
    for qid in sorted(world_q):
        zone = quest_zone[qid]
        item = {"quest": qid, "name": names[qid], "evidence": sorted(evidence[qid]), "custom_sql": quest_touched(qid)}
        if qid in want_obj and qid not in with_obj:
            found[zone]["quests_no_objectives"].append(item)
        if rewards.get(qid) and rewards[qid] - world_rewards.get(qid, set()):
            found[zone]["quest_rewards_missing"].append(dict(item, items=sorted(rewards[qid] - world_rewards.get(qid, set()))))
        if "progress" in text_kinds.get(qid, ()) and not progress.get(qid):
            found[zone]["quests_no_progress_text"].append(item)
        if "complete" in text_kinds.get(qid, ()) and not completion.get(qid):
            found[zone]["quests_no_completion_text"].append(item)

    if candidates.has_dbf(cur):
        dbf_fills(cur, found, aliases)
    has_iv = candidates.has_source(cur, "icyveins")
    if has_iv:
        icyveins_fills(cur, found)

    # ---- write
    labels = {r["source"]: r["label"] for r in candidates.rows(cur, f"SELECT source, label FROM {F}.src_pins")}
    by_name = {}
    for zone, cats in found.items():
        zname = zones.name(zone)
        if args.zone and zname != args.zone:
            continue
        slot = by_name.setdefault(zname, collections.defaultdict(list))
        for cat, items in cats.items():
            slot[cat].extend(items)
    totals = {cat: sum(len(z.get(cat, [])) for z in by_name.values()) for cat, _ in CATEGORIES}
    dbf_totals = {cat: sum(1 for z in by_name.values() for i in z.get(cat, []) if i.get("dbf")) for cat in DBF_CATEGORIES}
    iv_totals = {cat: sum(1 for z in by_name.values() for i in z.get(cat, []) if i.get("icyveins")) for cat in ICYVEINS_CATEGORIES}
    report = {"world": WORLD, "made": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "pins": labels,
              "custom_sql": custom, "skipped_test_quests": skipped_test, "skipped_test_npcs": skipped_test_npcs, "skipped_test_objects": skipped_test_objects, "totals": totals,
              "dbf_totals": dbf_totals if candidates.has_dbf(cur) else None,
              "icyveins_totals": iv_totals if has_iv else None,
              "zones": {z: {c: v for c, v in cats.items()} for z, cats in sorted(by_name.items())}}
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "everlake-gaps.json"), "w") as handle:
        json.dump(report, handle, indent=1, sort_keys=True, default=list)
    with open(os.path.join(args.out, "everlake-gaps.md"), "w") as handle:
        handle.write(markdown(report))
    print(f"wrote {os.path.join(args.out, 'everlake-gaps.md')} and .json")
    for cat, label in CATEGORIES:
        print(f"  {label}: {totals[cat]}")


DBF_CATEGORIES = ("missing_npcs", "npcs_not_spawned", "vendors_no_stock", "vendor_items_missing", "npcs_no_loot", "loot_items_missing",
                  "trainers_unlinked", "trainer_spells_missing", "objects_missing", "objects_not_spawned", "quests_no_giver",
                  "quests_no_ender")


def dbf_fills(cur, found, aliases):
    """Marks each gap that DatabaseForever (load_dbf.py, dbf_* tables) has rows for, as item["dbf"]: what it holds there.
    A mark is a lead to check, not evidence that live Forever has it: its added spawns are placed from map pins."""
    D = candidates.DBF
    items = [(cat, i) for cats in found.values() for cat in DBF_CATEGORIES for i in cats.get(cat, [])]
    npcs = {i["npc"] for _, i in items if "npc" in i}
    objects = {i["object"] for _, i in items if "object" in i}
    quests = {i["quest"] for cat, i in items if "quest" in i}
    ns, os_, qs = candidates.ids_sql(npcs), candidates.ids_sql(objects), candidates.ids_sql(quests)
    q = lambda sql: candidates.rows(cur, sql)      # noqa: E731
    template = {r["entry"]: r["lootid"] for r in q(f"SELECT entry, lootid FROM {D}creature_template WHERE entry IN ({ns})")}
    spawns = {r["id"]: r["n"] for r in q(f"SELECT id, COUNT(*) AS n FROM {D}creature WHERE id IN ({ns}) GROUP BY id")}
    sells, vrefs = collections.defaultdict(set), collections.defaultdict(set)
    pending, seen = set(npcs), set()
    while pending - seen:                     # a negative item lists another vendor's stock; follow the chain
        batch = pending - seen
        seen |= batch
        for r in q(f"SELECT entry, item FROM {D}npc_vendor WHERE type = 1 AND entry IN ({candidates.ids_sql(batch)})"):
            if r["item"] < 0:
                vrefs[r["entry"]].add(-r["item"])
                pending.add(-r["item"])
            else:
                sells[r["entry"]].add(r["item"])
    for nid in npcs:
        stack, done = list(vrefs.get(nid, ())), set()
        while stack:
            x = stack.pop()
            if x not in done:
                done.add(x)
                sells[nid] |= sells.get(x, set()) if x != nid else set()
                stack.extend(vrefs.get(x, ()))
    drops, refs = collections.defaultdict(set), collections.defaultdict(set)    # loot id -> items / reference ids
    for r in q(f"SELECT Entry, ItemType, Item FROM {D}creature_loot_template "
               f"WHERE Entry IN ({candidates.ids_sql({lid for lid in template.values() if lid})})"):
        if r["ItemType"] in (0, 1):      # 2 currency, 3 tracking quest: not item drops
            (refs if r["ItemType"] == 1 else drops)[r["Entry"]].add(r["Item"])
    pending = {x for v in refs.values() for x in v}
    ref_items, ref_links, seen = collections.defaultdict(set), collections.defaultdict(set), set()
    while pending - seen:
        batch = pending - seen
        seen |= batch
        for r in q(f"SELECT Entry, ItemType, Item FROM {D}reference_loot_template WHERE Entry IN ({candidates.ids_sql(batch)})"):
            if r["ItemType"] == 1:
                ref_links[r["Entry"]].add(r["Item"])
                pending.add(r["Item"])
            elif r["ItemType"] == 0:
                ref_items[r["Entry"]].add(r["Item"])
    for lid, links in refs.items():
        stack, done = list(links), set()
        while stack:
            x = stack.pop()
            if x not in done:
                done.add(x)
                drops[lid] |= ref_items.get(x, set())
                stack.extend(ref_links.get(x, ()))
    teaches = collections.defaultdict(set)
    for r in q(f"SELECT c.CreatureID, s.SpellId FROM {D}creature_trainer c JOIN {D}trainer_spell s ON s.TrainerId = c.TrainerID "
               f"WHERE c.CreatureID IN ({ns})"):
        teaches[r["CreatureID"]].add(r["SpellId"])
        teaches[r["CreatureID"]].update(aliases.get(r["SpellId"], ()))
    has_trainer = {r["CreatureID"] for r in q(f"SELECT DISTINCT CreatureID FROM {D}creature_trainer WHERE CreatureID IN ({ns})")}
    obj_template = {r["entry"] for r in q(f"SELECT entry FROM {D}gameobject_template WHERE entry IN ({os_})")}
    obj_spawns = {r["id"]: r["n"] for r in q(f"SELECT id, COUNT(*) AS n FROM {D}gameobject WHERE id IN ({os_}) GROUP BY id")}
    givers = collections.defaultdict(set)
    for table, kind, field in (("creature_queststarter", "npc", "quests_no_giver"), ("gameobject_queststarter", "object", "quests_no_giver"),
                               ("creature_questender", "npc", "quests_no_ender"), ("gameobject_questender", "object", "quests_no_ender")):
        for r in q(f"SELECT id, quest FROM {D}{table} WHERE quest IN ({qs})"):
            givers[(field, r["quest"])].add(f"{kind} {r['id']}")

    def covered(have, want, what="items"):
        return f"{len(have & set(want))} of {len(want)} {what}" if have & set(want) else None

    for cat, i in items:
        nid, oid = i.get("npc"), i.get("object")
        mark = None
        if cat == "missing_npcs" and nid in template:
            mark = f"template, {spawns.get(nid, 0)} spawns"
        elif cat == "npcs_not_spawned" and spawns.get(nid):
            mark = f"{spawns[nid]} spawns"
        elif cat == "vendors_no_stock" and sells.get(nid):
            mark = f"{len(sells[nid])} items"
        elif cat == "vendor_items_missing":
            mark = covered(sells.get(nid, set()), i["items"])
        elif cat in ("npcs_no_loot", "loot_items_missing"):
            mark = covered(drops.get(template.get(nid), set()), i["items"])
        elif cat == "trainers_unlinked" and nid in has_trainer:
            mark = f"trainer list, {len(teaches.get(nid, ()))} spells"
        elif cat == "trainer_spells_missing":
            mark = covered(teaches.get(nid, set()), i["items"], "spells")
        elif cat == "objects_missing" and oid in obj_template:
            mark = f"template, {obj_spawns.get(oid, 0)} spawns"
        elif cat == "objects_not_spawned" and obj_spawns.get(oid):
            mark = f"{obj_spawns[oid]} spawns"
        elif cat in ("quests_no_giver", "quests_no_ender") and givers.get((cat, i["quest"])):
            mark = ", ".join(sorted(givers[(cat, i["quest"])]))
        if mark:
            i["dbf"] = mark


ICYVEINS_CATEGORIES = ("missing_npcs", "npcs_not_spawned", "vendors_no_stock", "vendor_items_missing", "npcs_no_loot",
                       "loot_items_missing", "trainers_unlinked", "trainer_spells_missing", "quests_no_giver", "quests_no_ender")


def icyveins_fills(cur, found):
    """Marks each gap that Icy Veins' NPC data (src_icyveins, pin_sources.py --icyveins-only) has rows for, as
    item["icyveins"]. Its rows are what players' addons recorded on live Forever: map points are where an NPC was seen,
    talked to or looted (a wandering NPC leaves many), not spawn rows."""
    items = [(cat, i) for cats in found.values() for cat in ICYVEINS_CATEGORIES for i in cats.get(cat, [])]
    npcs = {i["npc"] for _, i in items if "npc" in i}
    quests = {i["quest"] for _, i in items if "quest" in i}
    listed, points, maps, players = set(), collections.Counter(), collections.defaultdict(set), collections.Counter()
    sells, drops, teaches = collections.defaultdict(set), collections.defaultdict(set), collections.defaultdict(set)
    trainer = set()
    for r in candidates.rows(cur, f"SELECT tbl, id, ref, data FROM {F}.src_icyveins WHERE id IN ({candidates.ids_sql(npcs)}) "
                                  "AND tbl IN ('npc', 'addon_points', 'addon_sells', 'addon_drops', 'addon_trains')"):
        nid, tbl = r["id"], r["tbl"]
        if tbl == "npc":
            listed.add(nid)
        elif tbl == "addon_points":
            points[nid] += 1
            maps[nid].add(r["ref"])
            players[nid] = max(players[nid], j(r["data"]).get("players") or 0)
        elif tbl == "addon_sells" and r["ref"]:
            sells[nid].add(r["ref"])
        elif tbl == "addon_drops" and r["ref"]:
            drops[nid].add(r["ref"])
        elif tbl == "addon_trains":
            trainer.add(nid)
            if r["ref"]:
                teaches[nid].add(r["ref"])
    givers = collections.defaultdict(set)
    for r in candidates.rows(cur, f"SELECT id, ref, data FROM {F}.src_icyveins WHERE tbl = 'addon_quests' "
                                  f"AND ref IN ({candidates.ids_sql(quests)})"):
        d = j(r["data"])
        for field, flag in (("quests_no_giver", "starts"), ("quests_no_ender", "ends")):
            if d.get(flag):
                givers[(field, r["ref"])].add(f"npc {r['id']}")

    def covered(have, want, what="items"):
        return f"{len(have & set(want))} of {len(want)} {what}" if have & set(want) else None

    def seen(nid):
        n = len(maps[nid])
        return f"{points[nid]} points on {n} map{'s' * (n != 1)}, up to {players[nid]} players" if points[nid] else None

    for cat, i in items:
        nid = i.get("npc")
        mark = None
        if cat == "missing_npcs" and nid in listed:
            mark = "listed" + (f", {seen(nid)}" if points[nid] else "")
        elif cat == "npcs_not_spawned":
            mark = seen(nid)
        elif cat == "vendors_no_stock" and sells.get(nid):
            mark = f"{len(sells[nid])} items"
        elif cat == "vendor_items_missing":
            mark = covered(sells.get(nid, set()), i["items"])
        elif cat in ("npcs_no_loot", "loot_items_missing"):
            mark = covered(drops.get(nid, set()), i["items"])
        elif cat == "trainers_unlinked" and nid in trainer:
            mark = f"trainer list, {len(teaches.get(nid, ()))} spells"
        elif cat == "trainer_spells_missing":
            mark = covered(teaches.get(nid, set()), i["items"], "spells")
        elif cat in ("quests_no_giver", "quests_no_ender") and givers.get((cat, i["quest"])):
            mark = ", ".join(sorted(givers[(cat, i["quest"])]))
        if mark:
            i["icyveins"] = mark


def far_points(points, ours, yards):
    """Points farther than `yards` from every point in `ours` on the same map."""
    grid = collections.defaultdict(list)
    for m, x, y in ours:
        grid[(m, int(x // yards), int(y // yards))].append((x, y))
    far = []
    for m, x, y in points:
        cx, cy = int(x // yards), int(y // yards)
        if not any((x - ox) ** 2 + (y - oy) ** 2 <= yards * yards
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1) for ox, oy in grid.get((m, cx + dx, cy + dy), ())):
            far.append((m, x, y))
    return far


def markdown(report):
    def cell(text):
        return str(text).replace("|", "\\|").replace("\n", " ")

    out = ["# Everlake world vs live Forever", "",
           f"Made by tools/forever-data/gap_report.py at {report['made']}. Everlake's world = the TrinityCore fork's world "
           f"release with the fork's sql/custom world files applied, as Everlake's worldserver does (tc_* tables, "
           f"{cell(report['pins'].get('tc-release', '?'))}). Custom files pinned since then and not yet applied: "
           f"{len((report['custom_sql'] or {}).get('files', []))}; gaps whose rows they touch say so. "
           f"Live Forever = every other source: " + ", ".join(f"{k} {cell(str(v)[:12])}" for k, v in sorted(report["pins"].items())
                                                          if k not in ("tc-release", "databaseforever", "icyveins")) + "."
           + (f" DatabaseForever ({cell(str(report['pins']['databaseforever'])[:12])}) is another emulator's database, not live "
              "Forever: it only marks gaps it has rows for." if "databaseforever" in report["pins"] else ""), "",
           f"{report['skipped_test_quests']} test or unused quests and {report['skipped_test_npcs']} NPCs (names like <UNUSED>, [DNT], "
           "OLD in capitals) are left out. "
           "Seen live = EG Link at build 70790 or later, QuestieTrace, or ForeverDB's seen list.", "",
           "NPCs never spawned include creatures that scripts summon, and extra spots include points along patrol paths "
           "(EG Link records where players saw an NPC): check those before adding spawns.", "", "## Totals", ""]
    for cat, label in CATEGORIES:
        out.append(f"- {label}: {report['totals'][cat]}")
    if report.get("dbf_totals"):
        out += ["", "## What DatabaseForever has rows for", "",
                "EmuForever's world database (dbf_* tables, load_dbf.py) holds rows for these gaps. Its added spawns are placed "
                "from map pins (a grid, all facing 0) and the repository states no licence: leads to check, not rows to copy.", ""]
        labels = dict(CATEGORIES)
        out += [f"- {labels[c]}: {n} of {report['totals'][c]}" for c, n in report["dbf_totals"].items() if report["totals"].get(c)]
    if report.get("icyveins_totals"):
        out += ["", "## What Icy Veins has rows for", "",
                f"Icy Veins' WoW Forever database (src_icyveins, {cell(str(report['pins'].get('icyveins', '?'))[:24])}) holds what "
                "players' addons recorded on live Forever for these gaps. Map points are sightings (seen, talked to, looted), not "
                "spawn rows, and it states no licence: leads to check, not rows to copy.", ""]
        labels = dict(CATEGORIES)
        out += [f"- {labels[c]}: {n} of {report['totals'][c]}" for c, n in report["icyveins_totals"].items() if report["totals"].get(c)]
    short = [("missing_quests_live", "Quests missing (live)"), ("missing_quests_data", "Quests missing (data only)"),
             ("renamed_quests", "Renamed"), ("quests_no_giver", "No giver"), ("quests_giver_differs", "Other givers"),
             ("quests_no_ender", "No ender"), ("quests_ender_differs", "Other enders"),
             ("quests_no_text", "No text"), ("missing_npcs", "NPCs missing"), ("npcs_not_spawned", "NPCs not spawned"),
             ("extra_spots", "Extra spots"), ("vendors_no_stock", "Vendors no stock"), ("vendor_items_missing", "Vendor items")]
    out += ["", "## By zone", "", "| Zone | " + " | ".join(s for _, s in short) + " |", "|---" * (len(short) + 1) + "|"]
    ranked = sorted(report["zones"].items(), key=lambda kv: -sum(len(v) for v in kv[1].values()))
    for zone, cats in ranked:
        out.append(f"| {cell(zone)} | " + " | ".join(str(len(cats.get(c, []))) for c, _ in short) + " |")
    rest = [("objects_missing", "Objects missing"), ("objects_not_spawned", "Objects not spawned"), ("npcs_no_loot", "No loot table"),
            ("loot_items_missing", "Loot short"), ("trainers_unlinked", "Trainer no list"), ("trainer_spells_missing", "Trainer spells"),
            ("quests_no_objectives", "No objectives"), ("quest_rewards_missing", "Rewards short"),
            ("quests_no_progress_text", "No progress text"), ("quests_no_completion_text", "No completion text"),
            ("flight_masters_unflagged", "Flight master flag")]
    out += ["", "The rest of the world:", "", "| Zone | " + " | ".join(s for _, s in rest) + " |", "|---" * (len(rest) + 1) + "|"]
    for zone, cats in sorted(report["zones"].items(), key=lambda kv: -sum(len(kv[1].get(c, [])) for c, _ in rest)):
        if any(cats.get(c) for c, _ in rest):
            out.append(f"| {cell(zone)} | " + " | ".join(str(len(cats.get(c, []))) for c, _ in rest) + " |")
    out += ["", "## Examples", "", f"Up to {EXAMPLES} per kind, live first; everlake-gaps.json has every one.", ""]
    for cat, label in CATEGORIES:
        items = [dict(i, zone=z) for z, cats in report["zones"].items() for i in cats.get(cat, [])]
        if not items:
            continue
        items.sort(key=lambda i: (not (set(i.get("evidence", [])) & LIVE_EVIDENCE), i.get("quest") or i.get("npc") or i.get("object")))
        out += [f"### {label} ({len(items)})", ""]
        for i in items[:EXAMPLES]:
            what = f"quest {i['quest']}" if "quest" in i else f"object {i['object']}" if "object" in i else f"NPC {i['npc']}"
            extra = []
            for key in ("world", "forever", "givers", "spots", "sells", "items", "spells", "loot_id", "evidence"):
                if i.get(key) not in (None, [], 0):
                    v = i[key]
                    extra.append(f"{key}: {len(v)} items" if key == "items" and isinstance(v, list) and len(v) > 6 else f"{key}: {v}")
            if i.get("dbf"):
                extra.append(f"DatabaseForever: {i['dbf']}")
            if i.get("icyveins"):
                extra.append(f"Icy Veins: {i['icyveins']}")
            if i.get("custom_sql"):
                extra.append("custom SQL touches it")
            if i.get("close_call"):
                extra.append("close call between sources")
            out.append(f"- {what} {cell(i.get('name') or '?')} ({cell(i['zone'])}) - " + cell("; ".join(map(str, extra))))
        out.append("")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    main()
