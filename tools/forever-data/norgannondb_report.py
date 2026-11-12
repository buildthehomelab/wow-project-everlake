#!/usr/bin/env python3
"""What NorgannonDB adds: how far it agrees with QuestieDB and Wowhead, which of the world's gaps it fills, and who else
backs each fill.

    norgannondb_report.py                              reads the pinned NorgannonDB files and acore_forever (read only)
    norgannondb_report.py --norgannondb DIR            a NorgannonDB checkout instead of the pin
    norgannondb_report.py --world SCHEMA.PREFIX        the world to measure gaps in (default acore_forever.tc_; the dry
                                                       run's acore_world_dryrun.elstep_ has the world-data files on top)
    norgannondb_report.py --data DIR                   a wow-everlake-world-data clone: mark fills its files already name
    norgannondb_report.py --tracker FILE               a Forever Tracker work list (To add > Export CSV) to measure against
    norgannondb_report.py --write DIR --name FILE      also write the vendor stock it can back into a world-data clone

Writes reports/norgannondb-coverage.md and .json. Nothing is written to a database.

--write takes only vendor rows NorgannonDB lists and ForeverDB.net shows for a vendor its players saw on Forever, where
the world's vendor (spawned, with the vendor flag) lacks the item at any price, no world-data file names the pair yet,
EG Link's live windows of that vendor (if any) show the item, the stock is unlimited and the price is money. With
--icy-veins (the user's decision of 2026-11-12) Icy Veins counts as that second source too, its price and stock flags
apply, and drops are written as well: a NorgannonDB drop of an item the world has no source for, that Icy Veins
recorded on the same NPC over at least MIN_KILLS kills, at Icy Veins' chance, while the NPC is spawned and alone on its
own loot table; quest drops and stacks are held back.

NorgannonDB (https://github.com/zmarotrix/NorgannonDB, GPL-3.0) is compiled from QuestieDB (with every correction,
QuestieTrace's player recordings included), pfQuest, DungeonJournal by Exehn, cmangos classic-db and its own Collector.
So a NorgannonDB row agreeing with QuestieDB, QuestieTrace or forever-db (which Polestar builds from pfQuest and CMaNGOS)
is the same evidence twice, not a second witness. The witnesses counted here are the ones built from other recordings:
EG Link's loot and vendor windows and ForeverDB.net's loot and stock. Icy Veins agreement is counted, but Icy Veins is
reference only (import_sql.REFERENCE_ONLY) until its owners agree.
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import candidates  # noqa: E402
import import_sql as isql  # noqa: E402
from load_sources import SOURCES, connect, read_norgannondb  # noqa: E402

F = candidates.F
QUESTIE = "data/Forever/foreverQuestDB.lua:QuestieDB.questData"
Q_NPC = "data/Forever/foreverNpcDB.lua:QuestieDB.npcData"
Q_ITEM = "data/Forever/foreverItemDB.lua:QuestieDB.itemData"
Q_OBJECT = "data/Forever/foreverObjectDB.lua:QuestieDB.objectData"
TRACE_ITEM = "src/corrections/Forever/traces/foreverItemTraces.lua:ForeverItemTraces:Load"
REWARD_COLUMNS = [f"RewardItem{i}" for i in range(1, 5)] + [f"RewardChoiceItemID{i}" for i in range(1, 7)]
ITEM_LOOT = ("creature_loot_template", "reference_loot_template", "gameobject_loot_template", "item_loot_template",
             "pickpocketing_loot_template", "skinning_loot_template", "fishing_loot_template", "disenchant_loot_template",
             "prospecting_loot_template", "milling_loot_template", "spell_loot_template", "mail_loot_template")


def norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def pct(a, b):
    return f"{a:,} of {b:,} ({100 * a / b:.1f}%)" if b else "0 of 0"


def load_norgannondb(folder):
    norg = collections.defaultdict(dict)
    norg["products"] = {}
    for tbl, _k, rid, _ref, row in read_norgannondb({}, folder):
        if tbl in ("quests", "npcs", "objects", "items", "instances"):
            norg[tbl][rid if tbl != "instances" else _k] = row
        elif tbl == "recipes" and row.get("item"):
            norg["products"][row["item"]] = _k
        elif tbl == "info":
            norg["info"] = row
    return norg


def agreement(norg, cur):
    """Names and links NorgannonDB shares with the pinned QuestieDB files and Wowhead's tooltips."""
    rows, j = candidates.rows, candidates.j
    out = {}
    questie = {}
    for kind, tbl in (("quests", QUESTIE), ("npcs", Q_NPC), ("items", Q_ITEM), ("objects", Q_OBJECT)):
        questie[kind] = {r["id"]: j(r["data"]) or [] for r in rows(cur, f"SELECT id, data FROM {F}.src_questiedb WHERE tbl = %s", (tbl,))}
    for kind, data in questie.items():
        both = [i for i in norg[kind] if i in data]
        same = sum(norm(norg[kind][i].get("name")) == norm((data[i] or [None])[0]) for i in both)
        out[f"questie {kind}"] = {"norg": len(norg[kind]), "questie": len(data), "both": len(both), "same name": same,
                                  "only norg": len(set(norg[kind]) - set(data)), "only questie": len(set(data) - set(norg[kind]))}
    # links: a quest's starter NPCs, an NPC's spawn zones, an item's dropping NPCs (QuestieDB's base file, before the
    # corrections NorgannonDB applies, so differences are corrections, pfQuest or DungeonJournal additions)
    def ids(v):
        return {int(x) for x in candidates.as_list(v) if candidates.as_int(x) is not None}
    link = collections.Counter()
    for i, q in questie["quests"].items():
        n = norg["quests"].get(i)
        if n and len(q) > 1 and q[1] and q[1][0]:
            link["quest starters compared"] += 1
            link["quest starters same"] += ids(q[1][0]) == set((n.get("starters") or {}).get("npcs") or [])
    for i, q in questie["npcs"].items():
        n = norg["npcs"].get(i)
        if n and len(q) > 6 and isinstance(q[6], dict) and q[6]:
            link["npc spawn zones compared"] += 1
            link["npc spawn zones same"] += {int(z) for z in q[6]} == {int(z) for z in (n.get("spawns") or {})}
    for i, q in questie["items"].items():
        n = norg["items"].get(i)
        if n and len(q) > 1 and q[1]:
            link["item drop NPCs compared"] += 1
            mine = {int(x) for x in ((n.get("drops") or {}).get("npcs") or {})}
            link["item drop NPCs same"] += ids(q[1]) == mine
            link["item drop NPCs norg adds"] += bool(mine - ids(q[1]))
    out["questie links"] = dict(link)
    for kind, wkind in (("quests", "quest"), ("npcs", "npc"), ("items", "item"), ("objects", "object")):
        wh = {}
        for r in rows(cur, f"SELECT id, data FROM {F}.src_wowhead_tooltips WHERE tbl = %s", (wkind,)):
            d = j(r["data"]) or {}
            if d.get("status") == "ok" and (d.get("data") or {}).get("name"):
                wh[r["id"]] = d["data"]["name"]
        both = [i for i in norg[kind] if i in wh]
        out[f"wowhead {kind}"] = {"both": len(both), "same name": sum(norm(norg[kind][i].get("name")) == norm(wh[i]) for i in both),
                                  "wowhead": len(wh), "only norg": len(set(norg[kind]) - set(wh))}
    return out


def world_state(cur, W):
    rows = candidates.rows
    src = collections.defaultdict(set)
    for t in ITEM_LOOT:
        try:
            for r in rows(cur, f"SELECT DISTINCT Item FROM {W}{t} WHERE ItemType = 0"):
                src[r["Item"]].add(t)
        except Exception:                                    # pylint: disable=broad-except
            pass                                             # a world without that table
    for r in rows(cur, f"SELECT DISTINCT item FROM {W}npc_vendor WHERE type = 1"):
        src[r["item"]].add("vendor")
    for c in REWARD_COLUMNS:
        for r in rows(cur, f"SELECT DISTINCT {c} AS i FROM {W}quest_template WHERE {c} > 0"):
            src[r["i"]].add("quest reward")
    st = {"item_sources": src,
          "spawned": {r["id"] for r in rows(cur, f"SELECT DISTINCT id FROM {W}creature")},
          "templates": {r["entry"]: r["npcflag"] for r in rows(cur, f"SELECT entry, npcflag FROM {W}creature_template")},
          "quests": {r["ID"] for r in rows(cur, f"SELECT ID FROM {W}quest_template")},
          "vendor": {(r["entry"], r["item"]) for r in rows(cur, f"SELECT entry, item FROM {W}npc_vendor WHERE type = 1")},
          "last_slot": {r["entry"]: r["s"] for r in rows(cur, f"SELECT entry, MAX(slot) AS s FROM {W}npc_vendor GROUP BY entry")},
          "loot_id": {r["Entry"]: r["LootID"] for r in rows(cur, f"SELECT Entry, LootID FROM {W}creature_template_difficulty WHERE DifficultyID = 0")}}
    st["loot_users"] = collections.Counter(v for v in st["loot_id"].values() if v)
    return st


def witnesses(cur):
    """(npc, item) pairs other recordings show: EG Link loot and vendor windows, ForeverDB.net boss loot and stock,
    QuestieDB's base drops and QuestieTrace (NorgannonDB's own origin), Icy Veins (reference only)."""
    rows, j = candidates.rows, candidates.j
    w = collections.defaultdict(lambda: collections.defaultdict(set))
    for r in rows(cur, f"SELECT k, data FROM {F}.src_eg_link WHERE tbl = 'loot' AND k LIKE %s", ("%/npc:%",)):
        m = re.fullmatch(r"([^/]+)/([^/]+)/npc:(\d+)((?:\|[^|]*)*)", r["k"] or "")
        if not m or any(f.startswith("spell") for f in m.group(4).split("|")[1:]):
            continue
        for item, v in ((j(r["data"]) or {}).get("items") or {}).items():
            if str(item).isdigit() and isinstance(v, dict) and v.get("drops"):
                w["drop"][(int(m.group(3)), int(item))].add("eg-link")
    w["live_stock"] = collections.defaultdict(set)      # NPC -> what EG Link saw it sell on a live build (wowf/...)
    for r in rows(cur, f"SELECT k, data FROM {F}.src_eg_link WHERE tbl = 'vendors'"):
        m = re.fullmatch(r"([^/]+)/[^/]+/(\d+)", r["k"] or "")
        if not m:
            continue
        npc = int(m.group(2))
        if m.group(1) == "wowf":
            w["live_stock"].setdefault(npc, set())
        for e in ((j(r["data"]) or {}).get("entries") or {}).values():
            if e.get("itemId"):
                w["sell"][(npc, int(e["itemId"]))].add("eg-link")
                if m.group(1) == "wowf":
                    w["live_stock"][npc].add(int(e["itemId"]))
    for r in rows(cur, f"SELECT data FROM {F}.src_foreverdb_net WHERE tbl = 'Loot.lootDB' AND k = 'inst'"):
        for inst in j(r["data"]) or []:
            for boss in inst.get("bosses") or []:
                if str(boss.get("npc", "")).isdigit():
                    for part in (boss.get("loot") or "").split(";"):
                        f = part.split(":")
                        if f[0].isdigit():
                            # item:percent:flag:quality:kills; flag c = Classic data, not seen on Forever
                            w["drop"][(int(boss["npc"]), int(f[0]))].add("foreverdb-net" if f[2:3] != ["c"] else "foreverdb-net classic")
    # ForeverDB.net's stock is Classic until its players see the vendor on Forever: NPCs.npcs ends with that flag
    seen = {}
    for r in rows(cur, f"SELECT id, data FROM {F}.src_foreverdb_net WHERE tbl = 'NPCs.npcs'"):
        d = j(r["data"])
        if isinstance(d, list) and d:
            seen[r["id"]] = d[-1] == 1
    w["fdb_price"] = {}
    for r in rows(cur, f"SELECT id, data FROM {F}.src_foreverdb_net WHERE tbl = 'NPCs.sold'"):
        d = j(r["data"]) or []
        for i in range(0, len(d) - 3, 4):          # npc, price (copper), stack, stock limit
            npc = int(d[i])
            w["sell"][(npc, r["id"])].add("foreverdb-net" if seen.get(npc) else "foreverdb-net classic")
            w["fdb_price"][(npc, r["id"])] = d[i + 1]
    for r in rows(cur, f"SELECT id, data FROM {F}.src_questiedb WHERE tbl = %s", (Q_ITEM,)):
        d = j(r["data"]) or []
        for n in candidates.as_list(d[1] if len(d) > 1 else None):
            if candidates.as_int(n) is not None:
                w["drop"][(int(n), r["id"])].add("questiedb")
    for r in rows(cur, f"SELECT id, data FROM {F}.src_questiedb WHERE tbl = %s", (TRACE_ITEM,)):
        for n in candidates.as_list((j(r["data"]) or {}).get("npcDrops_add")):
            if candidates.as_int(n) is not None:
                w["drop"][(int(n), int(r["id"]))].add("questietrace")
    w["icy"] = {}                                    # ("drop"|"sell", npc, item) -> Icy Veins' row (chance, kills; price, stock)
    try:
        for tbl, kind in (("addon_drops", "drop"), ("addon_sells", "sell")):
            for r in rows(cur, f"SELECT id, ref, data FROM {F}.src_icyveins WHERE tbl = %s", (tbl,)):
                w[kind][(r["id"], r["ref"])].add("icyveins")
                w["icy"][(kind, r["id"], r["ref"])] = j(r["data"]) or {}
    except Exception:                                        # pylint: disable=broad-except
        pass                                                 # Icy Veins not loaded
    return w


INDEPENDENT = {"eg-link", "foreverdb-net"}
# The user's decision of 2026-11-12: Icy Veins counts as a second witness for NorgannonDB's lines (--icy-veins); it stays
# reference only for the slices (import_sql.REFERENCE_ONLY)
ICY = "icyveins"
ORIGIN = {"questiedb", "questietrace", "foreverdb-net classic"}


def fills(norg, st, wit, data_files, icy=False):
    """NorgannonDB drops and stock the world lacks, for items the world has no source for (drops) or a vendor lacks."""
    def mentioned(npc, item):
        return [f for f, t in data_files.items() if re.search(rf"\b{npc}\b", t) and re.search(rf"\b{item}\b", t)]
    out = {"drop": [], "sell": []}
    for iid, it in norg["items"].items():
        if iid in st["item_sources"]:
            continue
        for npc, chance in ((it.get("drops") or {}).get("npcs") or {}).items():
            npc = int(npc)
            out["drop"].append({"npc": npc, "item": iid, "chance": chance, "w": sorted(wit["drop"].get((npc, iid), ())),
                                "spawned": npc in st["spawned"], "own_loot": st["loot_id"].get(npc) == npc and st["loot_users"][npc] == 1,
                                "npc_name": (norg["npcs"].get(npc) or {}).get("name"), "item_name": it.get("name"),
                                "icy": wit["icy"].get(("drop", npc, iid)), "item_class": it.get("class")})
    for npc, rec in norg["npcs"].items():
        for item, count in (rec.get("sells") or {}).items():
            item = int(item)
            if (npc, item) in st["vendor"]:
                continue
            out["sell"].append({"npc": npc, "item": item, "count": count, "w": sorted(wit["sell"].get((npc, item), ())),
                                "spawned": npc in st["spawned"], "vendor_flag": bool(st["templates"].get(npc, 0) & 128),
                                "no_source": item not in st["item_sources"], "npc_name": rec.get("name"),
                                # EG Link saw this vendor's stock on a live build, without the item
                                "contradicted": npc in wit["live_stock"] and item not in wit["live_stock"][npc],
                                "price": wit["fdb_price"].get((npc, item)) if "foreverdb-net" in wit["sell"].get((npc, item), ()) else None,
                                "icy": wit["icy"].get(("sell", npc, item)),
                                "item_name": (norg["items"].get(item) or {}).get("name")})
    for kind, lst in out.items():
        for x in lst:
            ws = set(x["w"])
            x["class"] = ("independent" if ws & (INDEPENDENT | ({ICY} if icy else set())) else "origin only" if ws & ORIGIN
                          else "icy veins only" if "icyveins" in ws else "norgannondb only")
            if x["class"] == "independent" and data_files:
                x["files"] = mentioned(x["npc"], x["item"])
    return out


NV_COLUMNS = ["entry", "slot", "item", "maxcount", "incrtime", "ExtendedCost", "type", "PlayerConditionID", "IgnoreFiltering",
              "VerifiedBuild"]
NV_KEY = ["entry", "item", "ExtendedCost", "type"]
LICENCE = ("GPL-3.0: made from NorgannonDB (GPL-3.0; QuestieDB and pfQuest stock) and ForeverDB.net (Data from ForeverDB.net, "
           "GPL-3.0). Game names belong to Blizzard Entertainment.")
LICENCE_ICY = " Icy Veins' WoW Forever database (db.icy-veins.com/wow-forever) witnesses rows and gives chances and prices."


def vendor_rows(sells, st, label):
    """The vendor rows --write takes, and the ones it holds back with why."""
    take, held = [], []
    for x in sorted(sells, key=lambda x: (x["npc"], x["item"])):
        if x["class"] != "independent" or not x["spawned"] or not x["vendor_flag"]:
            continue
        icy = x.get("icy") or {}
        if not x.get("price") and icy.get("price") and not (icy.get("costs") or icy.get("currency_id") or icy.get("cost_item_ids")):
            x["price"] = icy["price"]
        why = ("a world-data file already names the vendor and item: " + ", ".join(x["files"]) if x.get("files")
               else "EG Link saw this vendor's stock on live Forever without it" if x["contradicted"]
               else "limited stock (no restock time recorded)" if x["count"] or icy.get("remaining") is not None
               else "Icy Veins: no longer sold" if icy and icy.get("current") is False
               else "no money price recorded" if not x.get("price") else None)
        if why:
            held.append(dict(x, why=why))
            continue
        take.append(x)
    rows, slot = [], {}
    for x in take:
        slot[x["npc"]] = slot.get(x["npc"], st["last_slot"].get(x["npc"], -1)) + 1
        rows.append({"entry": x["npc"], "slot": slot[x["npc"]], "item": x["item"], "maxcount": 0, "incrtime": 0, "ExtendedCost": 0,
                     "type": 1, "PlayerConditionID": 0, "IgnoreFiltering": 0, "VerifiedBuild": 0,
                     "note": f"NorgannonDB {label[:10]} + " + " + ".join(
                         n for n, ok in (("ForeverDB.net (seen on Forever)", "foreverdb-net" in x["w"]), ("EG Link", "eg-link" in x["w"]),
                                         ("Icy Veins", ICY in x["w"])) if ok) + f", {x['price']} copper: {x['npc_name']} sells {x['item_name']}",
                     "why": f"{x['npc_name']}: {x['item_name']}"})
    return rows, held


LOOT_COLUMNS = ["Entry", "ItemType", "Item", "Chance", "QuestRequired", "LootMode", "GroupId", "MinCount", "MaxCount", "Comment"]
LOOT_KEY = ["Entry", "ItemType", "Item"]
MIN_KILLS = 10          # Icy Veins kills behind a chance; fewer goes to the held-back list


def drop_rows(drops, label):
    """Loot rows --write --icy-veins takes: a NorgannonDB drop Icy Veins also recorded, with Icy Veins' chance."""
    take, held = [], []
    for x in sorted(drops, key=lambda x: (x["npc"], x["item"])):
        if x["class"] != "independent" or not x["spawned"] or not x["own_loot"]:
            continue
        icy = x.get("icy") or {}
        why = ("a world-data file already names the NPC and item: " + ", ".join(x["files"]) if x.get("files")
               else "no Icy Veins chance" if not icy.get("chance")
               else f"Icy Veins saw {icy.get('total')} kills, fewer than {MIN_KILLS}" if (icy.get("total") or 0) < MIN_KILLS
               else "a quest drop (needs the quest that asks for it)" if icy.get("quest") or x.get("item_class") == 12
               else "drops in stacks (no stack range recorded)" if (icy.get("stack") or 1) > 1 else None)
        if why:
            held.append(dict(x, why=why))
            continue
        chance = round(float(icy["chance"]) * 100, 3)
        take.append({"Entry": x["npc"], "ItemType": 0, "Item": x["item"], "Chance": chance, "QuestRequired": 0, "LootMode": 1,
                     "GroupId": 0, "MinCount": 1, "MaxCount": 1, "Comment": f"{x['npc_name']} - {x['item_name']}"[:255],
                     "note": f"NorgannonDB {label[:10]} + Icy Veins ({chance}% of {icy['total']} kills"
                             + (", " + " + ".join(sorted(set(x["w"]) & INDEPENDENT)) if set(x["w"]) & INDEPENDENT else "")
                             + f"): {x['npc_name']} drops {x['item_name']}",
                     "why": f"{x['npc_name']}: {x['item_name']} {chance}%"})
    return take, held


def column_types(cur, world, table):
    schema, prefix = world.split(".")
    return {r["COLUMN_NAME"]: {"type": r["DATA_TYPE"], "ddl": r["COLUMN_TYPE"] + ("" if r["IS_NULLABLE"] == "YES" else " NOT NULL")}
            for r in candidates.rows(cur, "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE FROM information_schema.columns "
                                         "WHERE table_schema = %s AND table_name = %s", (schema, prefix + table))}


def write_file(args, name, title, block, rows, held, pins):
    text = "\n".join(isql.file_header(title, name, pins, args.world, LICENCE + (LICENCE_ICY if args.icy_veins else ""))
                     + [isql.IMPORT_ROWS_DDL, ""] + block).rstrip() + "\n"
    path = os.path.join(args.write, "sql", "world", name)
    if os.path.exists(path) and open(path, encoding="utf-8").read() != text and not args.replace:
        raise SystemExit(f"{path} exists with other content: a deployed update file is never changed (--replace if it never was)")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    meta = os.path.join(args.write, "slices", name[:-4])
    os.makedirs(meta, exist_ok=True)
    with open(os.path.join(meta, "manifest.json"), "w") as handle:
        json.dump({"file": name, "pins": pins, "world": args.world, "rule": __doc__.split("--write takes")[1].split("\n\n")[0].strip(),
                   "adds": [{k: v for k, v in r.items() if k != "why"} for r in rows],
                   "held_back": [{k: x[k] for k in ("npc", "npc_name", "item", "item_name", "w", "why")} for x in held]},
                  handle, indent=1, sort_keys=True)
    with open(os.path.join(meta, "held-back.md"), "w") as handle:
        handle.write(f"# {name}: held back\n\n" + "".join(f"- {x['npc']} {x['npc_name']}: {x['item']} {x['item_name']}: {x['why']}\n"
                                                       for x in held))
    print(f"wrote {path}: {len(rows)} rows, {len(held)} held back")


def write_drops(args, cur, rows, held, pins):
    if not re.fullmatch(r"\d{4}_\d{2}_\d{2}_\d{2,3}_world_everlake_[a-z0-9_]+\.sql", args.drop_name or ""):
        raise SystemExit("--drop-name: YYYY_MM_DD_NN_world_everlake_<topic>.sql")
    name = args.drop_name
    block = isql.stage_block(
        "creature_loot_template", LOOT_COLUMNS, LOOT_KEY, rows, name,
        f"NOT EXISTS (SELECT 1 FROM `{isql.IMPORT_ROWS}` r WHERE r.`tbl` = 'creature_loot_template' AND r.`k1` = s.`Entry` "
        "AND r.`k2` = s.`ItemType` AND r.`k3` = s.`Item`) "
        "AND EXISTS (SELECT 1 FROM `creature` c WHERE c.`id` = s.`Entry`) "
        "AND EXISTS (SELECT 1 FROM `creature_template_difficulty` d WHERE d.`Entry` = s.`Entry` AND d.`DifficultyID` = 0 AND d.`LootID` = s.`Entry`) "
        "AND NOT EXISTS (SELECT 1 FROM `creature_template_difficulty` d WHERE d.`LootID` = s.`Entry` AND d.`Entry` <> s.`Entry`) "
        "AND NOT EXISTS (SELECT 1 FROM `creature_loot_template` l JOIN `reference_loot_template` x ON x.`Entry` = l.`Item` "
        "WHERE l.`Entry` = s.`Entry` AND l.`ItemType` = 1 AND x.`ItemType` = 0 AND x.`Item` = s.`Item`)",
        "creature_loot_template: drops of items the world has no source for (only while the creature is spawned and alone on "
        "its own loot table, not where one of its reference tables already holds the item, and never again once added)",
        column_types(cur, args.world, "creature_loot_template"))
    write_file(args, name, "Drops NorgannonDB lists and Icy Veins players recorded on Forever, for items the world has no source for",
               block, rows, held, pins)


def write_vendors(args, cur, rows, held, pins, norg_label):
    name = args.name
    if not re.fullmatch(r"\d{4}_\d{2}_\d{2}_\d{2,3}_world_everlake_[a-z0-9_]+\.sql", name or ""):
        raise SystemExit("--name: YYYY_MM_DD_NN_world_everlake_<topic>.sql")
    never_again = " AND ".join(f"r.`k{n + 1}` = s.{isql.ident(k)}" for n, k in enumerate(NV_KEY))
    block = isql.stage_block(
        "npc_vendor", NV_COLUMNS, NV_KEY, rows, name,
        f"NOT EXISTS (SELECT 1 FROM `{isql.IMPORT_ROWS}` r WHERE r.`tbl` = 'npc_vendor' AND {never_again}) "
        "AND NOT EXISTS (SELECT 1 FROM `npc_vendor` o WHERE o.`entry` = s.`entry` AND o.`item` = s.`item` AND o.`type` = s.`type`) "
        "AND EXISTS (SELECT 1 FROM `creature_template` c WHERE c.`entry` = s.`entry` AND (c.`npcflag` & 128) <> 0) "
        "AND EXISTS (SELECT 1 FROM `creature` c WHERE c.`id` = s.`entry`)",
        "npc_vendor: items the vendor's stock lacks (only while the vendor is a spawned vendor, not where it already sells the "
        "item at another price, and never again once added)", column_types(cur, args.world, "npc_vendor"))
    title = ("Vendor stock NorgannonDB lists and a second source shows on Forever (ForeverDB.net's seen vendors, EG Link, Icy Veins), "
             "that the world's vendors lack" if args.icy_veins else
             "Vendor stock NorgannonDB lists and ForeverDB.net players saw on Forever, that the world's vendors lack")
    write_file(args, name, title, block, rows, held, pins)


def tracker(norg, path):
    """The Tracker's work list: for each kind of gap, how many NorgannonDB has data for."""
    c = collections.Counter()
    products = norg["products"]
    with open(path, encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            kind, rid, new = row["type"], int(row["id"]), row["new"] == "1"
            for check in (row["missing"] or "").split(" | "):
                label = check.split(":")[0]
                key = f"{kind} / {label} / {'new' if new else 'old'}"
                c[key + " / total"] += 1
                if kind == "item" and label == "Obtainable in game":
                    it = norg["items"].get(rid) or {}
                    c[key + " / norg drop"] += bool(it.get("drops"))
                    c[key + " / norg vendor"] += bool(it.get("vendors"))
                    c[key + " / norg quest reward"] += bool(it.get("rewardOf"))
                    c[key + " / norg any"] += bool(it.get("drops") or it.get("vendors") or it.get("rewardOf") or rid in products)
                elif kind == "quest":
                    q = norg["quests"].get(rid)
                    c[key + " / in norg"] += bool(q)
                    c[key + " / in norg, not hidden"] += bool(q and not q.get("hidden"))
    return dict(c)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--norgannondb", help="a NorgannonDB checkout (default: the pinned files)")
    ap.add_argument("--sources", default=SOURCES)
    ap.add_argument("--world", default=candidates.WORLD)
    ap.add_argument("--data", help="a wow-everlake-world-data clone")
    ap.add_argument("--tracker", help="the Forever Tracker's work list CSV")
    ap.add_argument("--out", default=os.path.join(HERE, "reports"))
    ap.add_argument("--write", help="a wow-everlake-world-data clone to write the vendor file into")
    ap.add_argument("--name", help="the vendor file's name, YYYY_MM_DD_NN_world_everlake_<topic>.sql (check open PRs' numbers)")
    ap.add_argument("--icy-veins", action="store_true", help="count Icy Veins as a second witness (decided 2026-11-12) and "
                    "write drops too, with Icy Veins' chances (--drop-name)")
    ap.add_argument("--drop-name", help="the drop file's name (with --icy-veins)")
    ap.add_argument("--replace", action="store_true", help="overwrite a file that differs (only one never deployed)")
    args = ap.parse_args()
    folder = args.norgannondb
    if not folder:
        pin = json.load(open(os.path.join(args.sources, "manifest.json")))["current"]["norgannondb"]
        folder = os.path.join(args.sources, pin["folder"])          # pin_sources.py records it relative to the folder
        label = pin["label"]
    else:
        label = os.popen(f"git -C '{folder}' rev-parse HEAD 2>/dev/null").read().strip() or "checkout"
    norg = load_norgannondb(folder)
    cur = connect().cursor()
    report = {"norgannondb": {k: norg["info"].get(k) for k in ("generated", "build", "sources", "stats")}}
    prov = collections.Counter((kind, r.get("_provenance")) for kind in ("quests", "npcs", "objects", "items") for r in norg[kind].values())
    report["provenance"] = {f"{k} {p}": v for (k, p), v in sorted(prov.items())}
    print("agreement ...", flush=True)
    report["agreement"] = agreement(norg, cur)
    print("world and witnesses ...", flush=True)
    st = world_state(cur, args.world)
    files = {}
    if args.data:
        files = {os.path.basename(f): open(f, encoding="utf-8").read() for f in sorted(glob.glob(os.path.join(args.data, "sql", "world", "*.sql")))}
    f = fills(norg, st, witnesses(cur), files, icy=args.icy_veins)
    report["world"] = args.world
    summary = {}
    for kind, lst in f.items():
        c = collections.Counter()
        for x in lst:
            usable = x["spawned"] and (x.get("own_loot") if kind == "drop" else x.get("vendor_flag"))
            c[(x["class"], "usable" if usable else "npc unspawned or table shared")] += 1
            if x["class"] == "independent" and usable:
                c[("independent", "usable", "already in a world-data file" if x.get("files")
                   else "contradicted by EG Link's live stock" if x.get("contradicted") else "new")] += 1
        summary[kind] = {" / ".join(k): v for k, v in sorted(c.items())}
        summary[kind + " items"] = len({x["item"] for x in lst})
    report["fills"] = summary
    missing_quests = [i for i, q in norg["quests"].items() if i not in st["quests"] and not q.get("hidden")]
    report["quests missing from the world, in NorgannonDB (not hidden)"] = len(missing_quests)
    report["unspawned NPC templates NorgannonDB places"] = sum(1 for i, n in norg["npcs"].items()
                                                           if n.get("spawns") and i in st["templates"] and i not in st["spawned"])
    if args.tracker:
        report["tracker"] = tracker(norg, args.tracker)
    if args.write:
        pins = isql.public_pins({r["source"]: r["label"] for r in candidates.rows(cur, f"SELECT source, label FROM {F}.src_pins")})
        pins["norgannondb"] = label
        if args.icy_veins:
            pins["icyveins"] = [r["label"] for r in candidates.rows(cur, f"SELECT label FROM {F}.src_pins WHERE source = 'icyveins'")][0]
            rows, held = drop_rows(f["drop"], label)
            write_drops(args, cur, rows, held, pins)
        rows, held = vendor_rows(f["sell"], st, label)
        write_vendors(args, cur, rows, held, pins, label)
    os.makedirs(args.out, exist_ok=True)
    json.dump({"report": report, "fills": f}, open(os.path.join(args.out, "norgannondb-coverage.json"), "w"), indent=1)
    with open(os.path.join(args.out, "norgannondb-coverage.md"), "w") as md:
        md.write(f"# NorgannonDB coverage\n\nNorgannonDB generated {report['norgannondb']['generated']}, world `{args.world}`.\n\n")
        md.write("```json\n" + json.dumps(report, indent=1, default=str) + "\n```\n")
    print(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
