#!/usr/bin/env python3
"""Slice 3 of Everlake's world import (docs/forever-import.md): trainers and vendors. Spells a trainer teaches on live
Forever that its trainer list lacks, and items a vendor sells that its stock lacks.

    import_slice3.py                          write the slice into world-data/ (gitignored, see below)
    import_slice3.py --out DIR                write somewhere else (a clone of wow-everlake-world-data)
    import_slice3.py --date 2026_11_08        the update files' date (default: today, UTC)
    import_slice3.py --world SCHEMA.PREFIX    compare with another copy of the fork world (default acore_forever.tc_)

Works on exactly the gaps gap_report.py lists (trainer_spells_missing, trainers_unlinked, vendor_items_missing,
vendors_no_stock), running the report itself (--gaps FILE reuses one). Writes only files:
- sql/world/YYYY_MM_DD_NN_world_everlake_import_slice3.sql: trainer_spell and npc_vendor rows, each with its source;
- slices/slice3/manifest.json, review.md and held-back.md.
No fork row needs changing (every vendor here already has its vendor flag), so there is no corrections file.

The source is EG Link: the newest trainer or vendor window a player opened that lists anything, chosen as the gap report
chooses it (gap_report.newest_windows: the highest build, live over beta on a tie; a beta window's row says so in its
note). A window lists what the NPC offers, so one window is enough; nothing here is random like loot.

Trainer spells (trainer_spell):
- The spell goes into the trainer list the creature uses (creature_trainer). A list several creatures share gets it
  only when no other creature on it was seen, in a window at least as new, without it.
- MoneyCost is the price at Neutral or Friendly (they match the fork's prices); one seen only at a higher standing is
  turned back into the base price with the game's discount (Honored 10%, Revered 15%, Exalted 20%) when that is exact.
- ReqLevel is the newest non-zero level any window shows for the spell (a window shows 0 when its player already knew
  it); a class spell every window shows at 0 is held back unless the fork teaches it at level 0 too. ReqSkillRank is EG Link's; ReqSkillLine is the skill line the fork's own rows use for that skill name.
  ReqAbility1..3 are what EG Link says the spell needs known first (`abilities`: "Cat Form (Shapeshift)", "Great
  Stamina (Rank 1)"), or for Rank 2 and up the rank before it, as the fork's rows have them; each is found by name in
  the same trainer window, and a rank before it must be on the list too. Without that the spell is held back.
- Held back: profession ranks (Apprentice ... Artisan; the plan has them checked by hand first: TrinityCore teaches
  some through other spell ids), pet training (the fork's trainers teach no pet spells: the core's support needs
  checking first), and spells not in Forever's client spell tables.
- A creature with no trainer list (trainers_unlinked) needs a gossip option to open one, and gossip menus are hand work
  (docs/forever-import.md): held back.

Vendor items (npc_vendor):
- Added after the vendor's last slot, in the window's order; ExtendedCost 0, no stock limit. Of an item listed twice,
  the money-only listing counts. A creature without the vendor flag is held back (the flag would be a correction).
- Held back: items that cost more than money (honor, marks, tokens: their ItemExtendedCost id isn't recorded), limited
  stock (the restock time isn't recorded), items not in Forever's client item list, and a vendor whose stock another
  vendor lists (a negative npc_vendor item) unless that one shows the item too.

The generated SQL is GPL-3.0 data like every slice's (the data repository's licence); EG Link is CC BY 4.0, credited.
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import candidates  # noqa: E402
import gap_report  # noqa: E402
import import_slice2  # noqa: E402  (file names, the gap report)
import import_sql as isql  # noqa: E402
from load_sources import SOURCES, connect  # noqa: E402

SLICE = "slice3"
F = candidates.F
OUT = os.path.join(HERE, "world-data")
CATEGORIES = ("trainer_spells_missing", "trainers_unlinked", "vendor_items_missing", "vendors_no_stock")
TS_COLUMNS = ["TrainerId", "SpellId", "MoneyCost", "ReqSkillLine", "ReqSkillRank", "ReqAbility1", "ReqAbility2", "ReqAbility3",
              "ReqLevel", "VerifiedBuild"]
TS_KEY = ["TrainerId", "SpellId"]
NV_COLUMNS = ["entry", "slot", "item", "maxcount", "incrtime", "ExtendedCost", "type", "PlayerConditionID", "IgnoreFiltering",
              "VerifiedBuild"]
NV_KEY = ["entry", "item", "ExtendedCost", "type"]
DISCOUNT = {4: 1.0, 5: 1.0, 6: 0.9, 7: 0.85, 8: 0.8}       # reputation standing -> price factor (calibrated on the fork)
PROFESSION_RANKS = ("Apprentice ", "Journeyman ", "Expert ", "Artisan ", "Master ", "Grand Master ")
LIVE = "wowf"
LICENCE = ("GPL-3.0, like the rest of wow-everlake-world-data; made from CC BY 4.0 data from EG Link (Data from Efficient "
           "Games, https://efficient.games). Game names belong to Blizzard Entertainment.")


def key_of(npc, thing):
    return f"{npc}/{thing}"


def base_price(costs):
    """(copper at Neutral, how) from EG Link's prices per standing, or (None, why)."""
    seen = {int(s): int(c) for s, c in (costs or {}).items() if str(s).isdigit() and isinstance(c, (int, float))}
    for s in (4, 5):
        if s in seen:
            return seen[s], f"standing {s}"
    for s in sorted(seen):
        if s in DISCOUNT:
            base = round(seen[s] / DISCOUNT[s])
            if int(base * DISCOUNT[s] + 1e-6) == seen[s]:          # the game floors the discounted price
                return base, f"from standing {s}"
    return None, "no price at a standing whose discount is known" if seen else "no price recorded"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--date", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y_%m_%d"))
    ap.add_argument("--world", default=candidates.WORLD, help="the fork world as SCHEMA.PREFIX (default acore_forever.tc_)")
    ap.add_argument("--sources", default=SOURCES, help="the pinned sources folder (for the gap report)")
    ap.add_argument("--gaps", help="a gap report JSON to use instead of running gap_report.py (made against --world)")
    ap.add_argument("--replace", action="store_true", help="overwrite update files that differ (only before they are deployed)")
    args = ap.parse_args()
    if not re.fullmatch(r"\d{4}_\d{2}_\d{2}", args.date):
        raise SystemExit("--date: YYYY_MM_DD")
    gap_report.set_world(args.world)
    W = candidates.WORLD
    name = file_name(args)
    conn = connect()
    cur = conn.cursor()
    rows = candidates.rows
    pins = isql.public_pins({r["source"]: r["label"] for r in rows(cur, f"SELECT source, label FROM {F}.src_pins")})
    world_label = pins.get("tc-release", "?") if W == f"{F}.tc_" else W
    report = import_slice2.load_gaps(args)
    gaps = collections.defaultdict(list)
    for zone, cats in report["zones"].items():
        for cat in CATEGORIES:
            gaps[cat] += cats.get(cat, [])
    print(", ".join(f"{len(v)} {c}" for c, v in gaps.items()) + "; reading the sources ...", flush=True)

    # ---- EG Link's windows: every one (for skill lines, pet abilities, learn levels), and the newest per NPC as the gap
    # report chooses it (gap_report.newest_windows), which is what each row is made from
    windows = {"trainers": collections.defaultdict(dict), "vendors": collections.defaultdict(dict)}
    for tbl in windows:
        for r in rows(cur, f"SELECT id, data FROM {F}.src_eg_link WHERE tbl = %s AND id IS NOT NULL", (tbl,)):
            d = candidates.j(r["data"]) or {}
            windows[tbl][int(r["id"])][(d.get("_product"), gap_report.build_no(d.get("_build")))] = d
    chosen = {tbl: gap_report.newest_windows(cur, tbl) for tbl in windows}

    sl = {"adds": collections.defaultdict(list), "review": [], "held": [], "outcomes": collections.defaultdict(dict)}

    def hold(cat, key, entry, reason, why=None):
        sl["held"].append(dict(entry, category=cat, reason=reason, why=why or reason))
        sl["outcomes"][cat][key] = "held back: " + reason

    def review(cat, key, entry, why):
        sl["review"].append(dict(entry, category=cat, why=why))
        sl["outcomes"][cat][key] = "review: " + why

    trainers(cur, W, gaps, windows["trainers"], chosen["trainers"], sl, hold, review)
    vendors(cur, W, gaps, chosen["vendors"], sl, hold)

    col_info = collections.defaultdict(dict)
    schema, prefix = W.split(".")
    for r in rows(cur, "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE FROM information_schema.columns "
                       "WHERE table_schema = %s AND table_name IN (%s, %s) ORDER BY ORDINAL_POSITION",
                  (schema, prefix + "trainer_spell", prefix + "npc_vendor")):
        col_info[r["TABLE_NAME"][len(prefix):]][r["COLUMN_NAME"]] = {
            "type": r["DATA_TYPE"], "ddl": r["COLUMN_TYPE"] + ("" if r["IS_NULLABLE"] == "YES" else " NOT NULL")}
    write(args, name, sl, pins, world_label, col_info, {c: len(v) for c, v in gaps.items()})


def spell_known(cur, spell_ids):
    """Spells in Forever's client spell tables: item-history's per-build spell records (a reference, used only to check
    a spell exists; nothing is copied from it)."""
    out = set()
    for r in candidates.rows(cur, f"SELECT id, data FROM {F}.src_item_history WHERE tbl = 'spells' AND id IN ({candidates.ids_sql(spell_ids)})"):
        d = (candidates.j(r["data"]) or {}).get("data") or {}
        if d.get("name") and d.get("related"):
            out.add(r["id"])
    return out


def trainers(cur, W, gaps, recs, pick, sl, hold, review):
    rows = candidates.rows
    lists_of, users = collections.defaultdict(set), collections.defaultdict(set)
    for r in rows(cur, f"SELECT CreatureID, TrainerID FROM {W}creature_trainer"):
        lists_of[r["CreatureID"]].add(r["TrainerID"])
        users[r["TrainerID"]].add(r["CreatureID"])
    ttype = {r["Id"]: r["Type"] for r in rows(cur, f"SELECT Id, Type FROM {W}trainer")}
    have = collections.defaultdict(dict)
    for r in rows(cur, f"SELECT * FROM {W}trainer_spell"):
        have[r["TrainerId"]][r["SpellId"]] = r
    # skill name -> the skill line the fork's rows use for it (learned from spells both the fork and EG Link list)
    skill_lines = collections.defaultdict(collections.Counter)
    for npc, by_build in recs.items():
        for d in by_build.values():
            for sid, sv in (d.get("services") or {}).items():
                if not str(sid).isdigit() or not sv.get("skill"):
                    continue
                for t in lists_of.get(npc, ()):
                    f = have[t].get(int(sid))
                    if f and f["ReqSkillLine"]:
                        skill_lines[sv["skill"]][f["ReqSkillLine"]] += 1
    skill_line = {name: c.most_common(1)[0][0] for name, c in skill_lines.items() if len(c) == 1 or
                  c.most_common(2)[1][1] * 10 < c.most_common(1)[0][1]}
    # pet abilities: what the windows of creatures on the fork's pet trainer lists (Type 3) show; Forever's hunter trainers
    # list the same abilities
    pet_spells, pet_names = set(), set()
    for npc, by_build in recs.items():
        if any(ttype.get(t) == 3 for t in lists_of.get(npc, ())):
            for d in by_build.values():
                for k, v in (d.get("services") or {}).items():
                    if str(k).isdigit():
                        pet_spells.add(int(k))
                        pet_names.add(v.get("name"))
    pet_names.discard(None)
    # the level a spell is learned at: a window shows 0 for a spell its player already knew, so the newest non-zero level
    # any window shows for it
    learn_level = {}
    for by_build in recs.values():
        for (_, b), d in by_build.items():
            for k, v in (d.get("services") or {}).items():
                if str(k).isdigit() and v.get("level"):
                    if int(k) not in learn_level or b >= learn_level[int(k)][0]:
                        learn_level[int(k)] = (b, int(v["level"]))
    fork_level = collections.defaultdict(set)
    for t, spells in have.items():
        for sid, r in spells.items():
            fork_level[sid].add(r["ReqLevel"])
    want = {s for g in gaps["trainer_spells_missing"] for s in g["items"]}
    known = spell_known(cur, want)
    per_list = collections.defaultdict(dict)                  # trainer list -> spell -> row (first creature's)

    for g in sorted(gaps["trainer_spells_missing"], key=lambda g: g["npc"]):
        npc = g["npc"]
        product, build, d = pick[npc]
        services = d.get("services") or {}
        src = f"eg-link@{build}" + ("" if product == LIVE else " (Forever beta)")
        lists = sorted(lists_of.get(npc, ()))
        def rank_no(spell):
            m = re.fullmatch(r"Rank (\d+)", str((services.get(str(spell)) or {}).get("rankText") or ""))
            return (int(m.group(1)) if m else 0, spell)

        for spell in sorted(g["items"], key=rank_no):
            sv = services.get(str(spell)) or {}
            key = key_of(npc, spell)
            e = {"npc": npc, "name": g["name"], "spell": spell, "spell_name": sv.get("name"), "rank": sv.get("rankText"),
                 "what": f"npc {npc} {g['name']}: spell {spell} {sv.get('name') or '?'}" + (f" ({sv['rankText']})" if sv.get("rankText") else ""),
                 "source": src, "lists": lists}
            cat = "trainer_spells_missing"
            if g.get("custom_sql"):
                hold(cat, key, e, "a fork custom file not loaded into the world yet writes this trainer's list")
                continue
            if sv.get("profession") or sv.get("step") or str(sv.get("name") or "").startswith(PROFESSION_RANKS):
                review(cat, key, e, "a profession rank: the plan has these checked by hand first (TrinityCore teaches some "
                                    "through other spell ids)")
                continue
            if len(lists) == 1 and (spell in have[lists[0]] or spell in per_list[lists[0]]):
                sl["outcomes"][cat][key] = "added"      # another creature on the same list brought it
                continue
            if any(ttype.get(t) == 3 for t in lists) or spell in pet_spells or sv.get("name") in pet_names:
                hold(cat, key, e, "pet training: the fork's trainers teach no pet spells, so the core's support needs checking first")
                continue
            if spell not in known:
                hold(cat, key, e, "the spell isn't in Forever's client spell tables")
                continue
            if len(lists) != 1:
                hold(cat, key, e, f"the creature uses {len(lists)} trainer lists" if lists else "the creature has no trainer list")
                continue
            t = lists[0]
            price, how = base_price(sv.get("costs"))
            if price is None:
                hold(cat, key, e, f"no usable price: {how}")
                continue
            line = 0
            if sv.get("skill"):
                line = skill_line.get(sv["skill"])
                if not line:
                    hold(cat, key, e, f"no skill line for {sv['skill']!r}: the fork's rows never name it")
                    continue
            # what it needs known first: EG Link's `abilities` ("Cat Form (Shapeshift)", "Great Stamina (Rank 1)"), else for
            # Rank 2 and up the rank before it; each found by name in the same window, as the fork's ReqAbility1..3 hold them
            needs = [str(a) for a in candidates.as_list(sv.get("abilities"))]
            m = re.fullmatch(r"Rank (\d+)", str(sv.get("rankText") or ""))
            if not needs and m and int(m.group(1)) > 1:
                needs = [f"{sv.get('name')} (Rank {int(m.group(1)) - 1})"]
            req, problem = [], None
            for need in needs:
                nm = re.fullmatch(r"(.*?)(?: \((.*)\))?", need)
                found = [int(k) for k, v in services.items() if str(k).isdigit() and v.get("name") == nm.group(1)
                         and (nm.group(2) is None or v.get("rankText") == nm.group(2))]
                if len(found) != 1:
                    problem = ("a required ability isn't in the same trainer window",
                               f"needs {need!r}: the window lists {len(found)} spells by that name")
                    break
                if nm.group(1) == sv.get("name") and found[0] not in have[t] and found[0] not in per_list[t]:
                    problem = ("the rank before it isn't on the trainer list either", f"the rank before it ({found[0]}) isn't on trainer list {t}")
                    break
                req.append(found[0])
            if not problem and len(req) > 3:
                problem = ("it needs more than three abilities", f"needs {needs}")
            if problem:
                hold(cat, key, e, *problem)
                continue
            req += [0] * (3 - len(req))
            level = int(sv.get("level") or 0) or learn_level.get(spell, (0, 0))[1]
            if not level and not sv.get("skill") and fork_level.get(spell) != {0}:
                hold(cat, key, e, "the level it's learned at isn't recorded",
                     "every window shows level 0 (its players may already have known it), and " +
                     (f"the fork teaches it at level {'/'.join(map(str, sorted(fork_level[spell])))}" if spell in fork_level
                      else "the fork doesn't teach it"))
                continue
            # a shared list: every other creature on it seen in a window at least as new must show the spell
            against = []
            for o in sorted(users[t] - {npc}):
                if o in pick:
                    op, ob, od = pick[o]
                    if (op == LIVE or product != LIVE) and ob >= build and str(spell) not in (od.get("services") or {}):
                        against.append(o)
            if against:
                hold(cat, key, e, "the trainer list is shared with creatures seen without the spell",
                     f"trainer list {t} is also creature {', '.join(map(str, against[:8]))}'s, seen in a window at least as new without it")
                continue
            row = {"TrainerId": t, "SpellId": spell, "MoneyCost": price, "ReqSkillLine": line,
                   "ReqSkillRank": int(sv.get("skillRank") or 0) if sv.get("skill") else 0, "ReqAbility1": req[0], "ReqAbility2": req[1],
                   "ReqAbility3": req[2], "ReqLevel": level, "VerifiedBuild": 0,
                   "note": f"{src}; price {how}", "why": f"{g['name']}: {sv.get('name')}" + (f" {sv['rankText']}" if sv.get("rankText") else "")}
            if spell not in per_list[t]:
                per_list[t][spell] = row
                sl["adds"]["trainer_spell"].append(row)
            sl["outcomes"][cat][key] = "added"

    # a creature whose spell was held back or put on the review list while another creature on the same list brought it
    added = {(r["TrainerId"], r["SpellId"]) for r in sl["adds"]["trainer_spell"]}
    moved = set()
    for g in gaps["trainer_spells_missing"]:
        for spell in g["items"]:
            key = key_of(g["npc"], spell)
            if any((t, spell) in added for t in lists_of.get(g["npc"], ())) and not sl["outcomes"]["trainer_spells_missing"].get(key, "").startswith("added"):
                sl["outcomes"]["trainer_spells_missing"][key] = "added"
                moved.add((g["npc"], spell))
    sl["held"][:] = [h for h in sl["held"] if (h["npc"], h.get("spell")) not in moved]
    sl["review"][:] = [h for h in sl["review"] if (h["npc"], h.get("spell")) not in moved]

    for g in gaps["trainers_unlinked"]:
        hold("trainers_unlinked", str(g["npc"]), {"npc": g["npc"], "name": g["name"], "what": f"npc {g['npc']} {g['name']}: trainer list"},
             "needs a gossip option to open its trainer list (gossip menus are hand work)",
             f"no trainer list and no trainer flag; EG Link saw {g.get('spells')} spells. Linking one needs a trainer list, "
             "the trainer flag and a gossip option, and gossip menus are hand work (docs/forever-import.md)")


def vendors(cur, W, gaps, pick, sl, hold):
    rows, ids_sql = candidates.rows, candidates.ids_sql
    npcs = {g["npc"] for c in ("vendor_items_missing", "vendors_no_stock") for g in gaps[c]}
    stock = collections.defaultdict(list)
    for r in rows(cur, f"SELECT entry, slot, item, ExtendedCost, type FROM {W}npc_vendor"):
        stock[r["entry"]].append(r)
    listed_by = collections.defaultdict(set)              # vendor -> vendors whose stock lists its stock
    for e, rs in stock.items():
        for r in rs:
            if r["item"] < 0:
                listed_by[-r["item"]].add(e)
    flags = {r["entry"]: int(r["npcflag"]) for r in rows(cur, f"SELECT entry, npcflag FROM {W}creature_template WHERE entry IN ({ids_sql(npcs)})")}
    items = set()
    for n in npcs:
        _, _, d = pick[n]
        items |= {candidates.as_int(v.get("itemId")) for v in (d.get("entries") or {}).values() if isinstance(v, dict)} - {None}
    item_known = {r["id"] for r in rows(cur, f"SELECT id FROM {F}.src_forever_db WHERE tbl = 'item' AND id IN ({ids_sql(items)})")}
    for cat in ("vendor_items_missing", "vendors_no_stock"):
        for g in sorted(gaps[cat], key=lambda g: g["npc"]):
            npc = g["npc"]
            product, build, d = pick[npc]
            src = f"eg-link@{build}" + ("" if product == LIVE else " (Forever beta)")
            entries = [(k, v) for k, v in (d.get("entries") or {}).items() if isinstance(v, dict)]
            # an item listed twice (item:X, item:X#2): the money-only listing first
            entries.sort(key=lambda kv: (bool(kv[1].get("costItems")) or bool(kv[1].get("limited") or kv[1].get("stockMax"))))
            order = {k: n for n, (k, _) in enumerate((d.get("entries") or {}).items())}
            want = set(g["items"]) if isinstance(g["items"], list) else None
            have = {r["item"] for r in stock.get(npc, ()) if r["type"] == 1 and r["item"] > 0}
            slot = first_slot = max([r["slot"] for r in stock.get(npc, ())] + [-1]) + 1
            added_any, done = False, set()
            for k, v in entries:
                item = candidates.as_int(v.get("itemId"))
                if not k.startswith("item:") or item is None or item in have or item in done or (want is not None and item not in want):
                    continue
                done.add(item)
                gkey = key_of(npc, item)
                e = {"npc": npc, "name": g["name"], "item": item, "item_name": v.get("name"), "source": src,
                     "what": f"npc {npc} {g['name']}: item {item} {v.get('name') or '?'}"}
                if g.get("custom_sql"):
                    hold(cat, gkey, e, "a fork custom file not loaded into the world yet writes this vendor's stock")
                elif not flags.get(npc, 0) & 128:
                    hold(cat, gkey, e, "the creature has no vendor flag (that would be a correction; none is written yet)")
                elif v.get("costItems"):
                    hold(cat, gkey, e, "costs more than money: the ItemExtendedCost id isn't recorded",
                         "costs " + ", ".join(f"{c.get('amount')} x {c.get('name') or c.get('itemId') or c.get('currencyId')}"
                                              for c in v["costItems"]) + ": the ItemExtendedCost id isn't recorded")
                elif v.get("limited") or v.get("stockMax"):
                    hold(cat, gkey, e, "limited stock: the restock time isn't recorded",
                         f"limited to {v.get('stockMax')}: the restock time (incrtime) isn't recorded")
                elif item not in item_known:
                    hold(cat, gkey, e, "the item isn't in Forever's client item list (forever-db)")
                elif listed_by.get(npc):
                    hold(cat, gkey, e, "another vendor lists this vendor's stock", f"vendor {', '.join(map(str, sorted(listed_by[npc])))} "
                         "lists this vendor's stock and would sell it too")
                else:
                    sl["adds"]["npc_vendor"].append({
                        "entry": npc, "slot": slot, "order": order[k], "item": item, "maxcount": 0, "incrtime": 0, "ExtendedCost": 0, "type": 1,
                        "PlayerConditionID": 0, "IgnoreFiltering": 0, "VerifiedBuild": 0, "note": src,
                        "why": f"{g['name']}: {v.get('name')}"})
                    slot += 1
                    added_any = True
                    sl["outcomes"][cat][gkey if cat == "vendor_items_missing" else str(npc)] = "added"
                    continue
                if cat == "vendors_no_stock":       # its items count on vendor_items_missing once it sells something
                    sl["outcomes"]["vendor_items_missing"][gkey] = sl["outcomes"][cat].pop(gkey)
            mine = sorted((r for r in sl["adds"]["npc_vendor"] if r["entry"] == npc), key=lambda r: r.pop("order"))
            for n, r in enumerate(mine):           # slots in the window's order
                r["slot"] = first_slot + n
            for item in sorted((want or set()) - done):     # listed in the gap, but not as an item of the window
                hold(cat, key_of(npc, item), {"npc": npc, "name": g["name"], "item": item, "source": src,
                                              "what": f"npc {npc} {g['name']}: item {item}"}, "not an item entry of the window")
            if cat == "vendors_no_stock":
                if added_any:
                    sl["outcomes"][cat][str(npc)] = "added"
                else:
                    reasons = sorted({h["reason"] for h in sl["held"] if h["npc"] == npc})
                    sl["outcomes"][cat][str(npc)] = "held back: " + "; ".join(reasons)


def file_name(args):
    """Slice 3's file follows every other slice's file already in the folder for this date."""
    folder = os.path.join(args.out, "sql", "world")
    taken = []
    if os.path.isdir(folder):
        for n in os.listdir(folder):
            m = re.match(rf"{args.date}_(\d\d)_world_everlake_import_(\w+?)(?:_corrections)?\.sql$", n)
            if m and m.group(2) != SLICE:
                taken.append(int(m.group(1)))
    return isql.check_name(f"{args.date}_{(max(taken) + 1 if taken else 0):02d}_world_everlake_import_{SLICE}.sql")


def write(args, name, sl, pins, world_label, col_info, gap_counts):
    sql_dir = os.path.join(args.out, "sql", "world")
    meta_dir = os.path.join(args.out, "slices", SLICE)
    os.makedirs(sql_dir, exist_ok=True)
    os.makedirs(meta_dir, exist_ok=True)

    def never_again(table, key):
        on = " AND ".join(f"r.`k{n + 1}` = s.{isql.ident(k)}" for n, k in enumerate(key))
        return f"NOT EXISTS (SELECT 1 FROM `{isql.IMPORT_ROWS}` r WHERE r.`tbl` = {isql.lit(table)} AND {on})"

    out = isql.file_header("Everlake world import, slice 3: trainer spells and vendor items live Forever shows that the "
                           "world lacks", name, pins, world_label, LICENCE)
    out += [isql.IMPORT_ROWS_DDL, ""]
    out += isql.stage_block(
        "trainer_spell", TS_COLUMNS, TS_KEY, [{k: v for k, v in r.items() if k in TS_COLUMNS + ["note", "why"]}
                                              for r in sl["adds"]["trainer_spell"]], name,
        f"{never_again('trainer_spell', TS_KEY)} AND EXISTS (SELECT 1 FROM `creature_trainer` c WHERE c.`TrainerID` = s.`TrainerId`)",
        "trainer_spell: spells the trainer list lacks (while a creature still uses the list, and never again once added: a row "
        "the fork removes stays removed; a ranked spell's rank before it is on the list or added here)", col_info["trainer_spell"])
    out += isql.stage_block(
        "npc_vendor", NV_COLUMNS, NV_KEY, [{k: v for k, v in r.items() if k in NV_COLUMNS + ["note", "why"]}
                                           for r in sl["adds"]["npc_vendor"]], name,
        f"{never_again('npc_vendor', NV_KEY)} AND NOT EXISTS (SELECT 1 FROM `npc_vendor` o WHERE o.`entry` = s.`entry` "
        "AND o.`item` = s.`item` AND o.`type` = s.`type`)",
        "npc_vendor: items the vendor's stock lacks (not where the vendor already sells the item at another price, and never "
        "again once added)", col_info["npc_vendor"])
    text = "\n".join(out).rstrip() + "\n"
    path = os.path.join(sql_dir, name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            if handle.read() != text and not args.replace:
                raise SystemExit(f"{path} exists with other content. A deployed update file is never changed; if this one "
                                 "was never deployed, run again with --replace")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    manifest = {"slice": SLICE, "pins": pins, "world": world_label, "gaps": gap_counts,
                "files": [{"name": name, "kind": "import", "sha1": hashlib.sha1(text.encode()).hexdigest().upper()}],
                "adds": {t: [{k: v for k, v in r.items() if k != "why"} for r in rs] for t, rs in sorted(sl["adds"].items())},
                "fixes": [], "review": sl["review"], "held_back": sl["held"],
                "outcomes": {c: dict(sorted(v.items())) for c, v in sorted(sl["outcomes"].items())}}
    with open(os.path.join(meta_dir, "manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True)
    with open(os.path.join(meta_dir, "review.md"), "w") as handle:
        handle.write(listing("Slice 3: for a person (not in the files)", "Profession ranks: the plan has them checked by "
                             "hand before any goes in.", sl["review"]))
    with open(os.path.join(meta_dir, "held-back.md"), "w") as handle:
        handle.write(listing("Slice 3: held back", "Rows that need something we don't have, and why. Nothing here was "
                             "guessed.", sl["held"]))
    print(f"wrote {path}: {len(sl['adds']['trainer_spell'])} trainer spells, {len(sl['adds']['npc_vendor'])} vendor items; "
          f"{len(sl['review'])} for review, {len(sl['held'])} held back (in {meta_dir})")


def listing(title, intro, items):
    out = [f"# {title}", "", intro, ""]
    groups = collections.defaultdict(list)
    for i in items:
        groups[i.get("reason") or i["category"]].append(i)
    for group, its in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out += [f"## {group} ({len(its)})", ""]
        for i in sorted(its, key=lambda x: (x["npc"], x.get("spell") or x.get("item") or 0)):
            why = f": {i['why']}" if i.get("why") and i["why"] != group else ""
            out.append(f"- {i['what']} ({i['category']}, {i.get('source', 'gap report')}){why}".replace("\n", " "))
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    main()
