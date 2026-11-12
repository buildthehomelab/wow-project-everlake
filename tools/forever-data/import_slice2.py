#!/usr/bin/env python3
"""Slice 2 of Everlake's world import (docs/forever-import.md): loot. Drops live Forever shows that the world's loot
tables lack, added to the creature's loot table, and new loot tables for creatures that have none.

    import_slice2.py                          write the slice into world-data/ (gitignored, see below)
    import_slice2.py --out DIR                write somewhere else (a clone of wow-everlake-world-data)
    import_slice2.py --date 2026_11_08        the update files' date (default: today, UTC)
    import_slice2.py --classic-only add|hold  drops that only forever-db's Classic tables show (default add, marked classic)
    import_slice2.py --world SCHEMA.PREFIX    compare with another copy of the fork world (default acore_forever.tc_)

Reads acore_forever (the pinned sources and the fork world, tc_*) and the gap report (run here, so the slice works on
exactly the gaps gap_report.py lists: loot_items_missing and npcs_no_loot); writes only files:
- sql/world/YYYY_MM_DD_NN_world_everlake_import_slice2.sql: the drops, each with a note of its sources and chance;
- sql/world/YYYY_MM_DD_NN+1_world_everlake_import_slice2_corrections.sql: a new loot table linked to its creature
  (creature_template_difficulty.LootID, a fork row), each only while the creature's LootID is still 0 as written against;
- slices/slice2/manifest.json (every decision, for import_dryrun.py), review.md (drops seen once, not in the files) and
  held-back.md (drops without a usable chance or with something missing, and why).

Which drops go in (the user's decisions of 2026-11-08):
1. Only where a Forever source shows the NPC drops it: EG Link's loot records (kills, not skinning, gathering or
   pick-pocketing: `|spell` keys) or a QuestieTrace sighting. forever-db's item_source rows are pfQuest (VMaNGOS) and
   CMaNGOS rows (Polestar builds them from those two alone): Classic data, not Forever's. The user chose (2026-11-08) to
   add a drop only they show anyway, with its Classic chance and "classic" in the row's note, so a later Forever
   recording can replace it (--classic-only hold holds them back instead).
2. The chance is EG Link's (drops / loot windows, summed over every build, beta included) when the NPC has 50 or more
   recorded kills; else forever-db's Classic chance, marked "classic".
3. A drop EG Link saw only once goes to the review list, not into the files.
4. A drop without a usable chance is held back, with why.

Loot rows are ItemType 0 (an item), GroupId 0 (rolled on its own, so the fork's groups keep their odds), LootMode 1, and
1 of the item: a drop whose stacks EG Link saw larger than one is held back, since no source records the stack range.
QuestRequired is 1 for a drop EG Link saw only while the looter was on a quest (`|quest`) and for a Classic drop of an
item a quest in the world asks for; such a drop is held back when no quest in the world asks for the item (it would
never drop). A loot table several creatures share gets a drop only when every one of them shows it.

New loot tables take the id NEW_LOOT_BASE + the creature's entry: the fork's loot ids follow creature entries (below
10 million), so ours can't collide with one, a re-run reuses the same id, and should the fork link its own table later
(the correction then no longer matches) ours is simply left unused.

The generated SQL is GPL-3.0 data (forever-db and QuestieDB are GPL-3.0; EG Link is CC BY 4.0), so it does not go into
this GPL-2.0 repository: it goes to wow-everlake-world-data.
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import candidates  # noqa: E402
import gap_report  # noqa: E402
import import_sql as isql  # noqa: E402
from load_sources import SOURCES, connect  # noqa: E402

SLICE = "slice2"
F = candidates.F
OUT = os.path.join(HERE, "world-data")
MIN_KILLS = 50
NEW_LOOT_BASE = 900_000_000
FORK_ID_LIMIT = 10_000_000          # the fork's creature entries and loot ids stay below this (checked)
LOOT = "creature_loot_template"
DIFF = "creature_template_difficulty"
LOOT_COLUMNS = ["Entry", "ItemType", "Item", "Chance", "QuestRequired", "LootMode", "GroupId", "MinCount", "MaxCount", "Comment"]
LOOT_KEY = ["Entry", "ItemType", "Item"]
CATEGORIES = ("loot_items_missing", "npcs_no_loot")
TRACE_ITEM = "src/corrections/Forever/traces/foreverItemTraces.lua:ForeverItemTraces:Load"
CUSTOM_FILE = "a fork custom file not loaded into the world yet writes this creature's loot"
LICENCE = ("GPL-3.0: made from GPL-3.0 sources (forever-db's tables, QuestieDB's QuestieTrace corrections) and CC BY 4.0 data "
           "from EG Link (Data from Efficient Games, https://efficient.games). Game names belong to Blizzard Entertainment.")


def key_of(npc, item):
    return f"{npc}/{item}"


def egl_loot(cur):
    """EG Link's kill loot: per NPC its loot windows (all, and while on a quest) and per drop its counts."""
    kills = collections.defaultdict(lambda: {"all": 0, "quest": 0, "builds": set()})
    seen = collections.defaultdict(lambda: {"drops": 0, "quest_drops": 0, "quantity": 0, "builds": set()})
    for r in candidates.rows(cur, f"SELECT k, data FROM {F}.src_eg_link WHERE tbl = 'loot' AND k LIKE %s", ("%/npc:%",)):
        m = re.fullmatch(r"([^/]+)/([^/]+)/npc:(\d+)((?:\|[^|]*)*)", r["k"] or "")
        if not m:
            continue
        flags = m.group(4).split("|")[1:]
        if any(f.startswith("spell") for f in flags):
            continue                # skinning, gathering or pick-pocketing: not what the kill drops
        d = candidates.j(r["data"]) or {}
        npc, quest, build = int(m.group(3)), "quest" in flags, f"{m.group(1)}@{m.group(2).rsplit('.', 1)[-1]}"
        windows = int(d.get("windows") or 0)
        kills[npc]["all"] += windows
        kills[npc]["builds"].add(build)
        if quest:
            kills[npc]["quest"] += windows
        for item, v in (d.get("items") or {}).items():
            if not str(item).isdigit() or not isinstance(v, dict):
                continue
            s = seen[(npc, int(item))]
            s["drops"] += int(v.get("drops") or 0)
            s["quantity"] += int(v.get("quantity") or v.get("drops") or 0)
            s["builds"].add(build)
            if quest:
                s["quest_drops"] += int(v.get("drops") or 0)
    return kills, seen


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--date", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y_%m_%d"))
    ap.add_argument("--classic-only", choices=("add", "hold"), default="add",
                    help="drops only forever-db's Classic tables show: add them with their Classic chance, or hold them back")
    ap.add_argument("--world", default=candidates.WORLD, help="the fork world as SCHEMA.PREFIX (default acore_forever.tc_)")
    ap.add_argument("--sources", default=SOURCES, help="the pinned sources folder (for the gap report)")
    ap.add_argument("--gaps", help="a gap report JSON to use instead of running gap_report.py (made against --world)")
    ap.add_argument("--replace", action="store_true", help="overwrite update files that differ (only before they are deployed)")
    args = ap.parse_args()
    if not re.fullmatch(r"\d{4}_\d{2}_\d{2}", args.date):
        raise SystemExit("--date: YYYY_MM_DD")
    gap_report.set_world(args.world)
    W = candidates.WORLD
    names = file_names(args)
    conn = connect()
    cur = conn.cursor()
    rows, ids_sql = candidates.rows, candidates.ids_sql
    pins = isql.public_pins({r["source"]: r["label"] for r in rows(cur, f"SELECT source, label FROM {F}.src_pins")})
    world_label = pins.get("tc-release", "?") if W == f"{F}.tc_" else W

    # ---- the gaps, as the gap report lists them
    report = load_gaps(args)
    gaps = {}                                   # (npc, item) -> gap
    for zone, cats in report["zones"].items():
        for cat in CATEGORIES:
            for g in cats.get(cat, []):
                for item in g["items"]:
                    gaps[(g["npc"], item)] = {"npc": g["npc"], "name": g["name"], "item": item, "category": cat,
                                              "loot_id": g.get("loot_id"), "custom_sql": g.get("custom_sql")}
    npcs = {n for n, _ in gaps}
    items = {i for _, i in gaps}
    print(f"{len(gaps)} drops missing on {len(npcs)} NPCs; reading the sources ...", flush=True)

    # ---- the sources
    kills, seen = egl_loot(cur)
    traced = set()
    for r in rows(cur, f"SELECT id, data FROM {F}.src_questiedb WHERE tbl = %s", (TRACE_ITEM,)):
        for n in candidates.as_list((candidates.j(r["data"]) or {}).get("npcDrops_add")):
            if candidates.as_int(n) is not None:
                traced.add((int(n), int(r["id"])))
    classic = {}
    for r in rows(cur, f"SELECT data FROM {F}.src_forever_db WHERE tbl = 'item_source' AND JSON_UNQUOTE(JSON_EXTRACT(data, '$.kind')) = 'npc' "
                       f"AND JSON_EXTRACT(data, '$.id') IN ({ids_sql(npcs)})"):
        d = candidates.j(r["data"])
        classic[(int(d["id"]), int(d["item"]))] = d.get("chance")
    item_info = {}
    for r in rows(cur, f"SELECT id, data FROM {F}.src_forever_db WHERE tbl = 'item' AND id IN ({ids_sql(items)})"):
        d = candidates.j(r["data"])
        item_info[r["id"]] = {"name": d.get("name") or "", "quest_item": bool(d.get("quest_item"))}

    # ---- the world: loot tables, who uses them, quests that ask for the items
    diff = collections.defaultdict(dict)
    for r in rows(cur, f"SELECT Entry, DifficultyID, LootID, VerifiedBuild FROM {W}{DIFF} WHERE Entry IN ({ids_sql(npcs)})"):
        diff[r["Entry"]][r["DifficultyID"]] = r
    loot_ids = {g["loot_id"] for g in gaps.values() if g["loot_id"]}
    users = collections.defaultdict(set)
    for r in rows(cur, f"SELECT DISTINCT Entry, LootID FROM {W}{DIFF} WHERE LootID IN ({ids_sql(loot_ids)})"):
        users[r["LootID"]].add(r["Entry"])
    asked = collections.defaultdict(set)        # item -> quests in the world whose objectives ask for it
    for r in rows(cur, f"SELECT QuestID, ObjectID FROM {W}quest_objectives WHERE Type = 1 AND ObjectID IN ({ids_sql(items)})"):
        asked[r["ObjectID"]].add(r["QuestID"])
    top = rows(cur, f"SELECT (SELECT MAX(entry) FROM {W}creature_template) AS c, (SELECT MAX(Entry) FROM {W}{LOOT}) AS l, "
                    f"(SELECT MAX(Entry) FROM {W}reference_loot_template) AS r, (SELECT MAX(LootID) FROM {W}{DIFF}) AS d")[0]
    if max(v or 0 for v in top.values()) >= FORK_ID_LIMIT:
        raise SystemExit(f"the fork's ids reach {top}: new loot ids at {NEW_LOOT_BASE} + entry may collide; pick another base")

    def is_quest_item(item):
        return item_info.get(item, {}).get("quest_item", False)

    sl = {"adds": [], "fixes": [], "review": [], "held": [], "outcomes": collections.defaultdict(dict)}

    def label(g):
        return f"npc {g['npc']} {g['name']}: item {g['item']} {item_info.get(g['item'], {}).get('name') or '?'}"

    def entry(g, **extra):
        e = {"npc": g["npc"], "name": g["name"], "item": g["item"], "item_name": item_info.get(g["item"], {}).get("name"),
             "category": g["category"], "what": label(g), "loot_id": g["loot_id"]}
        e.update(extra)
        return e

    # ---- 1. decide each drop on its own evidence
    decided = {}                                # (npc, item) -> row to add (before the table checks)
    for (npc, item), g in sorted(gaps.items()):
        s, k = seen.get((npc, item)), kills.get(npc, {"all": 0, "quest": 0, "builds": set()})
        # a quest drop: a quest item (the client's, as forever-db lists it) seen only while the looter was on a quest, that
        # a quest in the world asks for. One no quest in the world asks for is held back below. Any other item seen only
        # on quests (cloth, water) is an ordinary drop: EG Link files the whole kill under |quest.
        only_on_quest = bool(s and s["drops"] and s["drops"] == s["quest_drops"])
        quest_only = only_on_quest and is_quest_item(item) and bool(asked.get(item))
        windows = (k["quest"] if quest_only else k["all"]) if s else (k["quest"] if is_quest_item(item) else k["all"])
        has_classic = (npc, item) in classic
        c_chance = classic.get((npc, item))
        evidence = {"eg_link": {"drops": s["drops"], "quest_drops": s["quest_drops"], "quantity": s["quantity"],
                                "kills": k["all"], "quest_kills": k["quest"], "builds": sorted(s["builds"])} if s else None,
                    "eg_link_kills_without": None if s else {"kills": k["all"], "quest_kills": k["quest"]},
                    "questietrace": (npc, item) in traced, "classic_chance": c_chance, "classic_row": has_classic}
        e = entry(g, evidence=evidence)

        def hold(reason, why=None):
            sl["held"].append(dict(e, reason=reason, why=why or reason))
            sl["outcomes"][g["category"]][key_of(npc, item)] = "held back: " + reason

        def review(why):
            sl["review"].append(dict(e, why=why))
            sl["outcomes"][g["category"]][key_of(npc, item)] = "review: " + why

        if g["custom_sql"]:
            hold(CUSTOM_FILE)
            continue
        forever = bool(s and s["drops"]) or (npc, item) in traced
        if not forever:
            if not has_classic:
                hold("no source shows it (gap report entry without a drop record)")
            elif c_chance is None:
                hold("only Classic data shows it (forever-db: pfQuest/CMaNGOS), with no chance")
            elif args.classic_only == "hold":
                hold("only Classic data shows it (forever-db: pfQuest/CMaNGOS); no Forever source has seen it drop")
            elif windows >= MIN_KILLS:
                hold("EG Link recorded the NPC's kills without it", f"only Classic data shows it, and EG Link recorded {windows} "
                     f"{'kills made on a quest' if is_quest_item(item) else 'kills'} with no drop of it")
            else:
                decided[(npc, item)] = dict(e, chance=float(c_chance), basis="classic",
                                            note=f"classic forever-db {c_chance}% (pfQuest/CMaNGOS)"
                                            + (f"; eg-link 0/{windows}" if windows else ""))
            continue
        if not s:
            # QuestieTrace alone: a sighting with no count (does not happen in the pins of 2026-11-08)
            if has_classic and c_chance is not None:
                decided[(npc, item)] = dict(e, chance=float(c_chance), basis="classic",
                                            note=f"questietrace; classic forever-db {c_chance}% (pfQuest/CMaNGOS)")
            else:
                hold("no usable chance: only a QuestieTrace sighting, no kill count")
            continue
        if s["drops"] == 1:
            review(f"EG Link saw it drop once in {windows} {'kills made on a quest' if quest_only else 'kills'}"
                   + ("; QuestieTrace also lists it" if (npc, item) in traced else ""))
            continue
        if windows >= MIN_KILLS:
            chance, basis = round(100.0 * s["drops"] / windows, 2), "eg-link"
            note = f"eg-link {s['drops']}/{windows}" + (" on quest" if quest_only else "")
        elif has_classic and c_chance is not None:
            chance, basis = float(c_chance), "classic"
            note = f"eg-link {s['drops']}/{windows}; classic forever-db {c_chance}% (pfQuest/CMaNGOS)"
        else:
            hold(f"no usable chance: EG Link has under {MIN_KILLS} kills, no Classic chance",
                 f"no usable chance: EG Link saw {s['drops']} drops in {windows} {'kills made on a quest' if quest_only else 'kills'} "
                 f"(under {MIN_KILLS}), and forever-db has no Classic chance")
            continue
        if (npc, item) in traced:
            note += "; questietrace"
        decided[(npc, item)] = dict(e, chance=chance, basis=basis, note=note, quest_only=quest_only, only_on_quest=only_on_quest)

    # ---- 2. what each row needs: the item, the quest that asks for it, a stack of one, the table
    accepted = {}
    for (npc, item), d in sorted(decided.items()):
        g = gaps[(npc, item)]
        s = seen.get((npc, item))
        problems = []
        if item not in item_info:
            problems.append(("the item isn't in Forever's client item list (forever-db)", None))
        quest_required = 0
        if d.get("quest_only"):
            quest_required = 1
        elif d.get("only_on_quest") and is_quest_item(item):
            problems.append(("a quest item no quest in the world asks for", "EG Link saw this quest item drop only while the "
                             "looter was on a quest, and no quest in the world asks for it: with QuestRequired it would never "
                             "drop, without it everyone would get it"))
        elif d["basis"] == "classic" and not s:
            if is_quest_item(item) and asked.get(item):
                quest_required = 1
            elif is_quest_item(item):
                problems.append(("a quest item no quest in the world asks for", None))
        if s and s["quantity"] > s["drops"]:
            problems.append(("stack sizes over one; no source records the range",
                             f"EG Link saw {s['quantity']} of it in {s['drops']} drops; no source records the stack range"))
        if problems:
            reason, why = problems[0]
            sl["held"].append(dict(d, reason=reason, why="; ".join(w or r for r, w in problems)))
            sl["outcomes"][g["category"]][key_of(npc, item)] = "held back: " + reason
            continue
        accepted[(npc, item)] = dict(d, quest_required=quest_required)

    # shared loot tables: a drop goes in only when every creature using the table shows it
    for (npc, item), d in sorted(accepted.items()):
        g = gaps[(npc, item)]
        if g["category"] != "loot_items_missing":
            continue
        others = sorted(users.get(g["loot_id"], set()) - {npc})
        lacking = [o for o in others if (o, item) not in accepted]
        if not lacking and len({accepted[(o, item)]["quest_required"] for o in others + [npc]}) > 1:
            reason = "the loot table is shared with creatures whose drops differ (on a quest or not)"
            sl["held"].append(dict(d, reason=reason, why=f"loot table {g['loot_id']}'s creatures {', '.join(map(str, others + [npc]))} "
                                   "show it drop on a quest for some and not others"))
            sl["outcomes"][g["category"]][key_of(npc, item)] = "held back: " + reason
            continue
        if lacking:
            reason = "the loot table is shared with other creatures that don't show the drop"
            sl["held"].append(dict(d, reason=reason, why=f"loot table {g['loot_id']} is also creature {', '.join(map(str, lacking[:8]))}"
                                   + ("..." if len(lacking) > 8 else "") + "'s, which would drop it too"))
            sl["outcomes"][g["category"]][key_of(npc, item)] = "held back: " + reason
    accepted = {k: v for k, v in accepted.items() if not sl["outcomes"][gaps[k]["category"]].get(key_of(*k), "").startswith("held")}

    # ---- 3. rows: existing tables get the drops; creatures with none get a new table, linked by a correction
    by_table = collections.defaultdict(list)
    for (npc, item), d in sorted(accepted.items()):
        g = gaps[(npc, item)]
        new = g["category"] == "npcs_no_loot"
        if new:
            row0 = diff.get(npc, {}).get(0)
            if not row0 or row0["LootID"] != 0:
                reason = "the creature has no open-world creature_template_difficulty row to link a loot table to"
                sl["held"].append(dict(d, reason=reason, why=reason))
                sl["outcomes"][g["category"]][key_of(npc, item)] = "held back: " + reason
                continue
        lid = NEW_LOOT_BASE + npc if new else g["loot_id"]
        # a shared table gets the drop once, from the lowest creature; every user's gap closes with it
        if any(r["Item"] == item for r in by_table[lid]):
            sl["outcomes"][g["category"]][key_of(npc, item)] = "added"
            continue
        by_table[lid].append({"Entry": lid, "ItemType": 0, "Item": item, "Chance": d["chance"], "QuestRequired": d["quest_required"],
                              "LootMode": 1, "GroupId": 0, "MinCount": 1, "MaxCount": 1,
                              "Comment": (d["item_name"] or "")[:255], "note": d["note"][:255],
                              "why": f"{d['name']}: {d['item_name']} {d['chance']}%", "new_table": new, "npc": npc,
                              "basis": d["basis"], "verified_build": diff[npc][0]["VerifiedBuild"] if new else None})
        sl["outcomes"][g["category"]][key_of(npc, item)] = "added"
    for lid, rs in sorted(by_table.items()):
        sl["adds"].extend(rs)
        if lid >= NEW_LOOT_BASE:
            npc = lid - NEW_LOOT_BASE
            row0 = diff[npc][0]
            sl["fixes"].append({"fix": len(sl["fixes"]) + 1, "kind": "update", "table": DIFF, "npc": npc,
                                "name": gaps[(npc, rs[0]["Item"])]["name"], "category": "npcs_no_loot",
                                "key": {"Entry": npc, "DifficultyID": 0},
                                "against": {"LootID": 0, "VerifiedBuild": row0["VerifiedBuild"]}, "set": {"LootID": lid},
                                "what": f"npc {npc} {gaps[(npc, rs[0]['Item'])]['name']}: link its new loot table {lid} "
                                        f"({len(rs)} drops)", "sources": sorted({r["basis"] for r in rs})})
    # an NPC with no loot that gets a table: its drops held back or on review then show as "loot short"
    for (npc, item), g in gaps.items():
        if g["category"] == "npcs_no_loot" and NEW_LOOT_BASE + npc in by_table:
            o = sl["outcomes"]["npcs_no_loot"].get(key_of(npc, item), "")
            if not o.startswith("added"):
                sl["outcomes"]["loot_items_missing"][key_of(npc, item)] = o
                sl["outcomes"]["npcs_no_loot"][key_of(npc, item)] = "moved to loot_items_missing: " + o

    col_info = collections.defaultdict(dict)
    schema, prefix = W.split(".")
    for r in rows(cur, "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE FROM information_schema.columns "
                       "WHERE table_schema = %s AND table_name IN (%s, %s) ORDER BY ORDINAL_POSITION", (schema, prefix + LOOT, prefix + DIFF)):
        col_info[r["TABLE_NAME"][len(prefix):]][r["COLUMN_NAME"]] = {
            "type": r["DATA_TYPE"], "ddl": r["COLUMN_TYPE"] + ("" if r["IS_NULLABLE"] == "YES" else " NOT NULL")}
    write(args, names, sl, pins, world_label, col_info, len(gaps), len(npcs))


def file_names(args):
    """Slice 2's files follow every file already in the folder for this date (slice 1's 00 and 01)."""
    folder = os.path.join(args.out, "sql", "world")
    taken = []
    if os.path.isdir(folder):
        for n in os.listdir(folder):
            m = re.match(rf"{args.date}_(\d\d)_world_everlake_import_(\w+?)(?:_corrections)?\.sql$", n)
            if m and m.group(2) != SLICE:
                taken.append(int(m.group(1)))
    first = max(taken) + 1 if taken else 0
    if first + 1 > 99:
        raise SystemExit("no file numbers left for this date")
    return {"import": isql.check_name(f"{args.date}_{first:02d}_world_everlake_import_{SLICE}.sql"),
            "corrections": isql.check_name(f"{args.date}_{first + 1:02d}_world_everlake_import_{SLICE}_corrections.sql")}


def load_gaps(args):
    if args.gaps:
        with open(args.gaps) as handle:
            return json.load(handle)
    with tempfile.TemporaryDirectory() as out:
        print("running the gap report ...", flush=True)
        subprocess.run([sys.executable, os.path.join(HERE, "gap_report.py"), "--world", candidates.WORLD, "--out", out,
                        "--sources", args.sources], check=True, stdout=subprocess.DEVNULL)
        with open(os.path.join(out, "everlake-gaps.json")) as handle:
            return json.load(handle)


def write(args, names, sl, pins, world_label, col_info, n_gaps, n_npcs):
    sql_dir = os.path.join(args.out, "sql", "world")
    meta_dir = os.path.join(args.out, "slices", SLICE)
    os.makedirs(sql_dir, exist_ok=True)
    os.makedirs(meta_dir, exist_ok=True)
    types = {c: v["type"] for c, v in col_info[DIFF].items()}
    loot_types = col_info[LOOT]

    # ---- the import file
    name = names["import"]
    out = isql.file_header("Everlake world import, slice 2: loot (drops live Forever shows that the world's loot tables lack)",
                           name, pins, world_label, LICENCE)
    out += [isql.IMPORT_ROWS_DDL, ""]
    never_again = (f"NOT EXISTS (SELECT 1 FROM `{isql.IMPORT_ROWS}` r WHERE r.`tbl` = {isql.lit(LOOT)} AND r.`k1` = s.`Entry` "
                   "AND r.`k2` = s.`ItemType` AND r.`k3` = s.`Item`)")
    via_refs = (f"NOT EXISTS (SELECT 1 FROM `{LOOT}` t JOIN `reference_loot_template` x ON x.`Entry` = t.`Item` WHERE t.`Entry` = s.`Entry` "
                "AND t.`ItemType` = 1 AND x.`ItemType` = 0 AND x.`Item` = s.`Item`) AND NOT EXISTS (SELECT 1 FROM `"
                f"{LOOT}` t JOIN `reference_loot_template` x ON x.`Entry` = t.`Item` JOIN `reference_loot_template` y ON y.`Entry` = x.`Item` "
                "WHERE t.`Entry` = s.`Entry` AND t.`ItemType` = 1 AND x.`ItemType` = 1 AND y.`ItemType` = 0 AND y.`Item` = s.`Item`)")
    existing = [r for r in sl["adds"] if not r["new_table"]]
    new = [r for r in sl["adds"] if r["new_table"]]
    out += isql.stage_block(
        LOOT, LOOT_COLUMNS, LOOT_KEY, [{k: v for k, v in r.items() if k in LOOT_COLUMNS + ["note", "why"]} for r in existing], name,
        f"{never_again} AND {via_refs} AND EXISTS (SELECT 1 FROM `{DIFF}` d WHERE d.`LootID` = s.`Entry`)",
        f"{LOOT}: drops the creature's loot table lacks (not where the item drops through one of its reference lists, while "
        "a creature still uses the table, and never again once added: a row the fork removes stays removed)", loot_types)
    # one block per VerifiedBuild of the creatures' rows: the rows go in only while the creature's open-world row is
    # still as the correction that links them was written against (LootID 0, that build), or already ours
    builds = collections.defaultdict(list)
    for r in new:
        builds[r["verified_build"]].append(r)
    for vb, rs in sorted(builds.items()):
        out += isql.stage_block(
            LOOT, LOOT_COLUMNS, LOOT_KEY, [{k: v for k, v in r.items() if k in LOOT_COLUMNS + ["note", "why"]} for r in rs], name,
            f"{never_again} AND EXISTS (SELECT 1 FROM `{DIFF}` d WHERE d.`Entry` = s.`Entry` - {NEW_LOOT_BASE} AND d.`DifficultyID` = 0 "
            f"AND ((d.`LootID` = 0 AND d.`VerifiedBuild` = {int(vb)}) OR d.`LootID` = s.`Entry`))",
            f"{LOOT}: new loot tables ({NEW_LOOT_BASE} + the creature's entry) for creatures that have none, VerifiedBuild {vb} "
            "(only while the creature has still no loot table but ours; the corrections file links them)", loot_types)
    files = {name: "\n".join(out).rstrip() + "\n"}

    # ---- the corrections file: link each new table to its creature
    name = names["corrections"]
    out = isql.file_header("Everlake world import, slice 2 corrections: new loot tables linked to their creatures, each only "
                           "while the creature's row is still as written against", name, pins, world_label, LICENCE)
    out += [isql.IMPORT_ROWS_DDL, "",
            "-- Every correction's guard is checked first, against the world as it is before any of them acts.",
            f"DROP TEMPORARY TABLE IF EXISTS `{isql.FIX_OK}`;",
            f"CREATE TEMPORARY TABLE `{isql.FIX_OK}` (`fix` int NOT NULL, PRIMARY KEY (`fix`)) ENGINE=InnoDB;"]
    if sl["fixes"]:
        out.append(f"INSERT INTO `{isql.FIX_OK}` (`fix`) VALUES " + ", ".join(f"({f['fix']})" for f in sl["fixes"]) + ";")
    for f in sl["fixes"]:
        key = " AND ".join(f"t.{isql.ident(k)} = {isql.lit(v)}" for k, v in f["key"].items())
        lid = f["set"]["LootID"]
        out.append(f"-- fix {f['fix']}: {isql.comment(f['what'])}")
        # the value it changes and the row's VerifiedBuild (a fork re-sniff changes it), and our table is there
        out.append(f"DELETE FROM `{isql.FIX_OK}` WHERE `fix` = {f['fix']} AND NOT (EXISTS (SELECT 1 FROM `{DIFF}` t WHERE {key} AND "
                   f"{isql.row_guard('t', f['against'], types)}) AND EXISTS (SELECT 1 FROM `{LOOT}` l WHERE l.`Entry` = {lid}));")
    out.append("")
    for f in sl["fixes"]:
        key = " AND ".join(f"t.{isql.ident(k)} = {isql.lit(v)}" for k, v in f["key"].items())
        sets = ", ".join(f"t.{isql.ident(c)} = {isql.lit(v)}" for c, v in f["set"].items())
        out.append(f"UPDATE `{DIFF}` t JOIN `{isql.FIX_OK}` ok ON ok.`fix` = {f['fix']} SET {sets} WHERE {key}; -- fix {f['fix']}")
    out += ["", f"DROP TEMPORARY TABLE `{isql.FIX_OK}`;"]
    files[name] = "\n".join(out).rstrip() + "\n"

    for fname, text in files.items():
        path = os.path.join(sql_dir, fname)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                old = handle.read()
            if old != text and not args.replace:
                raise SystemExit(f"{path} exists with other content. A deployed update file is never changed; if this one "
                                 "was never deployed, run again with --replace")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    basis = collections.Counter(r["basis"] for r in sl["adds"])
    manifest = {"slice": SLICE, "pins": pins, "world": world_label, "classic_only": args.classic_only, "min_kills": MIN_KILLS,
                "new_loot_base": NEW_LOOT_BASE, "gaps": {"drops": n_gaps, "npcs": n_npcs},
                "files": [{"name": n, "kind": k, "sha1": hashlib.sha1(files[n].encode()).hexdigest().upper()} for k, n in names.items()],
                "adds": {LOOT: [{k: v for k, v in r.items() if k != "why"} for r in sl["adds"]]},
                "fixes": sl["fixes"], "review": sl["review"], "held_back": sl["held"],
                "outcomes": {c: dict(sorted(v.items())) for c, v in sorted(sl["outcomes"].items())}}
    with open(os.path.join(meta_dir, "manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True, default=sorted_default)
    with open(os.path.join(meta_dir, "review.md"), "w") as handle:
        handle.write(listing("Slice 2: drops seen once (not in the files)", "EG Link saw each of these drop once. A person "
                             "decides them; one sighting gives no chance worth writing.", sl["review"]))
    with open(os.path.join(meta_dir, "held-back.md"), "w") as handle:
        handle.write(listing("Slice 2: held back", "Drops without a usable chance, or that need something we don't have, and "
                             "why. Nothing here was guessed.", sl["held"], by_reason=True))
    print(f"wrote {sql_dir}: {len(sl['adds'])} drops ({', '.join(f'{n} {b}' for b, n in sorted(basis.items()))}) in "
          f"{len({r['Entry'] for r in sl['adds']})} loot tables, {len(sl['fixes'])} new tables linked; {len(sl['review'])} seen "
          f"once (review), {len(sl['held'])} held back (in {meta_dir})")


def sorted_default(value):
    return sorted(value) if isinstance(value, set) else str(value)


def listing(title, intro, items, by_reason=False):
    out = [f"# {title}", "", intro, ""]
    groups = collections.defaultdict(list)
    for i in items:
        groups[i.get("reason") if by_reason else i["category"]].append(i)
    for group, its in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out += [f"## {group} ({len(its)})", ""]
        for i in sorted(its, key=lambda x: (x["npc"], x["item"])):
            ev = i.get("evidence") or {}
            eg = ev.get("eg_link")
            bits = []
            if eg:
                bits.append(f"EG Link {eg['drops']} drops in {eg['kills']} kills ({eg['quest_drops']} in {eg['quest_kills']} on a quest)")
            elif (ev.get("eg_link_kills_without") or {}).get("kills"):
                bits.append(f"EG Link {ev['eg_link_kills_without']['kills']} kills without it")
            if ev.get("questietrace"):
                bits.append("QuestieTrace")
            if ev.get("classic_row"):
                bits.append(f"Classic {ev['classic_chance']}%" if ev.get("classic_chance") is not None else "Classic, no chance")
            line = f"- {i['what']} ({i['category']}): {i['why']}" + (f". Seen: {'; '.join(bits)}" if bits else "")
            out.append(line.replace("\n", " "))
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    main()
