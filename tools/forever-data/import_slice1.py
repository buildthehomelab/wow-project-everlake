#!/usr/bin/env python3
"""Slice 1 of Everlake's world import (docs/forever-import.md): quest givers and enders, quest objectives, and progress
and completion texts, for quests Everlake's world already has.

    import_slice1.py                          write the slice into world-data/ (gitignored, see below)
    import_slice1.py --date 2026_11_08        the update files' date (default: today, UTC)
    import_slice1.py --objective-flags 32,0   write objective rows with these Flags,Flags2 (no public source records
                                              them; without this option every objective row is held back)
    import_slice1.py --out DIR                write somewhere else
    import_slice1.py --world SCHEMA.PREFIX    compare with another copy of the fork world (default acore_forever.tc_)

Reads acore_forever (the pinned sources and the fork world, tc_*); writes only files:
- sql/world/YYYY_MM_DD_00_world_everlake_import_slice1.sql: rows the world is missing (givers, enders, objectives,
  progress and completion texts), each with a note of the sources that gave it;
- sql/world/YYYY_MM_DD_01_world_everlake_import_slice1_corrections.sql: changes to fork rows (other givers or enders,
  an empty text filled in), each guarded so it only acts while the fork row is still what it was written against;
- slice1/manifest.json (every decision, for import_dryrun.py), slice1/review.md (close calls, not written into the
  files) and slice1/held-back.md (rows that need something we don't have, with why).

Every value comes from the weighted vote (source_weights.py) over every source, the fork's own Forever beta sniffs
included (tc-sniff); the fork's converted Classic rows only count where no Forever source speaks. The generated SQL is
GPL-3.0 data (several sources are GPL-3.0), so it does not go into this GPL-2.0 repository: world-data/ is gitignored
until it moves to its own repository (wow-everlake-world-data).
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
import import_sql as isql  # noqa: E402
import source_weights  # noqa: E402
from load_sources import SOURCES, connect  # noqa: E402

SLICE = "slice1"
F = candidates.F
OUT = os.path.join(HERE, "world-data")
GIVER_TABLES = {("start", "npc"): "creature_queststarter", ("start", "object"): "gameobject_queststarter",
                ("end", "npc"): "creature_questender", ("end", "object"): "gameobject_questender"}
# EG Link objective typeId -> what its ObjectID names (TrinityCore QuestObjectiveType)
OBJECTIVE_KIND = {0: "npc", 1: "item", 2: "object", 3: "npc"}
FDB_KIND = {"kill": "npc", "talk": "npc", "item": "item", "object": "object"}
# Inserts name only the columns that get a value of their own; the rest take the table's defaults (0, Visible 1), so a
# later fork change to other columns can't make a re-run fail.
OBJECTIVE_COLUMNS = ["ID", "QuestID", "Type", "Order", "StorageIndex", "ObjectID", "Amount", "Flags", "Flags2", "Description"]
TEXT_COLUMN = {"quest_request_items": "CompletionText", "quest_offer_reward": "RewardText"}
CUSTOM_FILE = "a fork custom file not loaded into the world yet writes this quest's rows"
LICENCE = ("GPL-3.0: made from GPL-3.0 sources (forever-db's tables, QuestieDB, ForeverDB.net) and CC BY 4.0 data from "
           "EG Link (Data from Efficient Games, https://efficient.games). Game text belongs to Blizzard Entertainment.")


class Slice:
    """Every decision of the slice: rows to add, corrections, close calls, rows held back, and what became of each
    quest the gap report lists (outcomes), so the dry run can tell a closed gap from one left on purpose."""

    def __init__(self):
        self.adds = collections.defaultdict(list)          # table -> [row dict + note, why]
        self.fixes = []                                     # corrections, numbered from 1
        self.review, self.held = [], []
        self.outcomes = collections.defaultdict(dict)       # gap category -> {quest: outcome}

    def outcome(self, category, quest, what):
        self.outcomes[category][int(quest)] = what


def note(sources):
    return " ".join(sorted(set(sources)))[:255]


def set_close_call(vote):
    """A member kept or dropped by resolve_set() within CLOSE_CALL of the keep line (half the strongest member)."""
    top = max(vote["weights"].values())
    line = top * 0.5
    return any(line * (1 - source_weights.CLOSE_CALL) <= w < line * (1 + source_weights.CLOSE_CALL)
               for w in vote["weights"].values())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--date", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y_%m_%d"))
    ap.add_argument("--objective-flags", help="FLAGS,FLAGS2 for objective rows (else they are held back)")
    ap.add_argument("--world", default=candidates.WORLD, help="the fork world as SCHEMA.PREFIX (default acore_forever.tc_)")
    ap.add_argument("--sources", default=SOURCES, help="the pinned sources folder (for fork custom files not loaded yet)")
    ap.add_argument("--replace", action="store_true", help="overwrite update files that differ (only before they are deployed)")
    args = ap.parse_args()
    if not re.fullmatch(r"\d{4}_\d{2}_\d{2}", args.date):
        raise SystemExit("--date: YYYY_MM_DD")
    flags = None
    if args.objective_flags:
        m = re.fullmatch(r"(\d+),(\d+)", args.objective_flags)
        if not m:
            raise SystemExit("--objective-flags: FLAGS,FLAGS2 (two numbers)")
        flags = (int(m.group(1)), int(m.group(2)))
    gap_report.set_world(args.world)
    W = candidates.WORLD
    names = {"import": isql.check_name(f"{args.date}_00_world_everlake_import_{SLICE}.sql"),
             "corrections": isql.check_name(f"{args.date}_01_world_everlake_import_{SLICE}_corrections.sql")}
    conn = connect()
    cur = conn.cursor()
    rows = candidates.rows
    ids_sql = candidates.ids_sql
    pins = {r["source"]: r["label"] for r in rows(cur, f"SELECT source, label FROM {F}.src_pins")}
    world_label = pins.get("tc-release", "?") if W == f"{F}.tc_" else W

    # ---- the world's types, for the stage tables and the row guards
    schema, prefix = W.split(".")
    col_info = collections.defaultdict(dict)
    for r in rows(cur, "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE FROM information_schema.columns "
                       "WHERE table_schema = %s AND table_name IN (%s) ORDER BY ORDINAL_POSITION" % ("%s", ", ".join(["%s"] * 8)),
                  (schema, *(prefix + t for t in ("quest_template", "quest_objectives", "quest_request_items", "quest_offer_reward",
                                                   *GIVER_TABLES.values())))):
        col_info[r["TABLE_NAME"][len(prefix):]][r["COLUMN_NAME"]] = {
            "type": r["DATA_TYPE"], "ddl": r["COLUMN_TYPE"] + ("" if r["IS_NULLABLE"] == "YES" else " NOT NULL")}

    def types(table):
        return {c: v["type"] for c, v in col_info[table].items()}

    # ---- the quests: every quest the world has that a Forever source knows (the gap report's set)
    evidence, _ = gap_report.quest_evidence(cur)
    tc_q = {r["ID"]: r for r in rows(cur, f"SELECT ID, LogTitle, QuestDescription FROM {W}quest_template WHERE ID IN ({ids_sql(evidence)})")}
    applied = {r["name"] for r in rows(cur, f"SELECT name FROM {W}updates")}
    mentions, _ = gap_report.custom_sql_mentions(args.sources, applied)

    def custom_touched(qid):        # a fork custom file not loaded into the world yet writes this quest's rows
        return any(qid in ids for (t, col), ids in mentions.items()
                   if (t in gap_report.QUEST_ID_TABLES and col == "id") or (t.startswith("quest_") and col == "questid")
                   or (t.endswith(("queststarter", "questender")) and col == "quest"))

    print(f"{len(tc_q)} quests in the world that Forever's sources know; voting ...", flush=True)
    qc = candidates.quests(cur, set(tc_q))
    sl = Slice()
    quests = {}
    for qid in sorted(tc_q):
        fields = qc.get(qid, {})
        name = source_weights.resolve("name", [c for c in fields.get("name", []) if not c[1].startswith("tc-")])
        title = (name or {}).get("value") or tc_q[qid]["LogTitle"]
        if title and gap_report.TEST_NAME.search(str(title)):
            continue
        quests[qid] = tc_q[qid]["LogTitle"] or title

    # world relations
    world_rel = {"start": collections.defaultdict(dict), "end": collections.defaultdict(dict)}
    for (role, kind), table in GIVER_TABLES.items():
        for r in rows(cur, f"SELECT id, quest, VerifiedBuild FROM {W}{table} WHERE quest IN ({ids_sql(quests)})"):
            world_rel[role][r["quest"]][(kind, r["id"])] = r["VerifiedBuild"]

    # names of every NPC and object a vote may name, and whether the world has their templates
    named = collections.defaultdict(set)
    for qid in quests:
        for field in ("quest_giver", "quest_ender"):
            for (value, _, _) in qc.get(qid, {}).get(field, []):
                if isinstance(value, (list, tuple)) and value[0] in ("npc", "object"):
                    named[value[0]].add(value[1])
    tpl = {"npc": {r["entry"]: r["name"] for r in rows(cur, f"SELECT entry, name FROM {W}creature_template WHERE entry IN ({ids_sql(named['npc'])})")},
           "object": {r["entry"]: r["name"] for r in rows(cur, f"SELECT entry, name FROM {W}gameobject_template WHERE entry IN ({ids_sql(named['object'])})")}}
    fdb_names = {r["id"]: r["name"] for r in rows(cur, f"SELECT id, JSON_UNQUOTE(JSON_EXTRACT(data, '$.name')) AS name FROM {F}.src_forever_db "
                                                       f"WHERE tbl IN ('npc', 'object') AND id IN ({ids_sql(named['npc'] | named['object'])})")}

    def label(member):
        kind, i = member
        return f"{kind} {i} {tpl[kind].get(i) or fdb_names.get(i) or '?'}"

    # ---- 1. givers and enders
    for qid, title in quests.items():
        fields = qc.get(qid, {})
        for role, field, gone_cat, diff_cat in (("start", "quest_giver", "quests_no_giver", "quests_giver_differs"),
                                                ("end", "quest_ender", "quests_no_ender", "quests_ender_differs")):
            cands = fields.get(field, [])
            vote = source_weights.resolve_set(field, cands)
            others = source_weights.resolve_set(field, [c for c in cands if not c[1].startswith("tc-")])
            if not vote:
                continue
            world = world_rel[role].get(qid, {})
            members = {tuple(m) for m in vote["members"] if isinstance(m, (list, tuple)) and m[0] in ("npc", "object")}
            item_started = role == "start" and any(isinstance(m, (list, tuple)) and m[0] == "item" for m in vote["members"])
            o_members = {tuple(m) for m in (others or {}).get("members", []) if isinstance(m, (list, tuple)) and m[0] in ("npc", "object")}
            # what the gap report (the vote without the fork's rows) says about this quest, as gap_report.py decides it
            gap_cat = None
            o_item = role == "start" and any(isinstance(m, (list, tuple)) and m[0] == "item" for m in (others or {}).get("members", []))
            if o_members and not o_item:
                if not world:
                    gap_cat = gone_cat
                elif o_members != set(world) and not others["classic_only"]:
                    gap_cat = diff_cat
            cat = gone_cat if not world else diff_cat
            what = f"quest {qid} {title}: {'givers' if role == 'start' else 'enders'}"
            sources = {str(m): vote["sources"].get(str(m), []) for m in vote["members"]}

            def record(outcome):
                if gap_cat:
                    sl.outcome(gap_cat, qid, outcome)

            if item_started:
                record("kept: an item starts the quest")      # as the gap report: givers of item-started quests aren't compared
                continue
            if not members or members == set(world):
                record("kept: the vote with the fork's own Forever beta sniff counted agrees with the world"
                       if members == set(world) else "kept: the vote names no NPC or object")
                continue
            if vote["classic_only"]:
                if gap_cat:
                    record("kept: only Classic data speaks")
                continue
            entry = {"quest": qid, "name": title, "role": role, "world": [label(m) for m in sorted(world)],
                     "vote": [label(m) for m in sorted(members)], "sources": sources,
                     "weights": vote["weights"], "category": cat}
            if custom_touched(qid):
                sl.held.append(dict(entry, what=what, reason=CUSTOM_FILE, why=CUSTOM_FILE))
                record("held back")
                continue
            if set_close_call(vote):
                sl.review.append(dict(entry, what=what, why="close call: a member is within 15% of the vote's keep line"))
                record("review")
                continue
            no_tpl = sorted(m for m in members - set(world) if m[1] not in tpl[m[0]])
            if not world:
                for m in no_tpl:
                    sl.held.append(dict(entry, what=f"{what}: {label(m)}", reason="the NPC or object has no template in the world (slice 5)",
                                        why=f"no {'creature' if m[0] == 'npc' else 'gameobject'} template in the world (new NPCs and "
                                        "objects are slice 5)"))
                adds = sorted(members - set(no_tpl))
                for kind, i in adds:
                    table = GIVER_TABLES[(role, kind)]
                    sl.adds[table].append({"id": i, "quest": qid, "VerifiedBuild": 0, "note": note(vote["sources"][str((kind, i))]),
                                           "why": f"{title}: {label((kind, i))}"})
                record("added" if adds else "held back")
                if adds and no_tpl:          # the quest then has some of the vote's members: the gap report will say "other"
                    sl.outcome(diff_cat, qid, "held back: " + ", ".join(label(m) for m in no_tpl) + " has no template yet")
                continue
            if no_tpl:
                sl.held.append(dict(entry, what=what, reason="the NPC or object has no template in the world (slice 5)", why="the vote's " + ", ".join(label(m) for m in no_tpl) +
                                    " has no template in the world (slice 5); the fork's givers stay until it has"))
                record("held back")
                continue
            # Removing a fork giver rests on the sources' silence about it. One source's silence isn't evidence (forever-db
            # often lists one of a class quest's several trainers), so removals need two Forever sources speaking about
            # the quest's givers; else the vote's new members still go in and the removals go to a person.
            speaking = sorted({c[1] for c in cands if not c[1].startswith("tc-") and c[1] not in source_weights.CLASSIC
                               and source_weights.weight(c[1], field) > 0})
            removes, adds = sorted(set(world) - members), sorted(members - set(world))
            if removes and len(speaking) < 2:
                sl.review.append(dict(entry, what=f"{what}: remove " + ", ".join(label(m) for m in removes),
                                      why=f"only {', '.join(speaking) or 'no Forever source'} lists this quest's "
                                          f"{'givers' if role == 'start' else 'enders'}: its silence about the fork's isn't enough"
                                      + ("; the vote's new members are added (corrections file)" if adds else "")))
                removes = []
            if not adds and not removes:
                record("review")
                continue
            fix = len(sl.fixes) + 1
            sl.fixes.append(dict(entry, fix=fix, kind="relations", what=what, speaking=speaking,
                                 against=[{"table": GIVER_TABLES[(role, k)], "id": i, "VerifiedBuild": vb} for (k, i), vb in sorted(world.items())],
                                 delete=[{"table": GIVER_TABLES[(role, k)], "id": i, "quest": qid} for k, i in removes],
                                 add=[{"table": GIVER_TABLES[(role, k)], "id": i, "quest": qid, "VerifiedBuild": 0,
                                       "note": note(vote["sources"][str((k, i))])} for k, i in adds]))
            record("corrected" if set(world) - members == set(removes) else "review: the vote's new members added, removals need a person")

    # ---- 2. progress and completion texts (EG Link records what the live and beta servers sent)
    eg_texts, eg_empty = collections.defaultdict(list), set()
    for r in rows(cur, f"SELECT id, data FROM {F}.src_eg_link WHERE tbl = 'texts.enUS' AND id IN ({ids_sql(quests)})"):
        d = candidates.j(r["data"])
        build = gap_report.build_no(d.get("_build"))
        for key in ("progress", "complete"):
            if key in d:
                eg_empty.add((r["id"], key))
            for e in candidates.as_list(d.get(key)):
                if isinstance(e, dict) and isinstance(e.get("text"), str) and e["text"].strip():
                    eg_texts[(r["id"], key)].append((e["text"], "eg-link", build))
    text_tables = {"progress": ("quest_request_items", "CompletionText", "quests_no_progress_text"),
                   "complete": ("quest_offer_reward", "RewardText", "quests_no_completion_text")}
    for key, (table, col, cat) in text_tables.items():
        cols = list(col_info[table])
        world = {r["ID"]: r for r in rows(cur, f"SELECT * FROM {W}{table} WHERE ID IN ({ids_sql(quests)})")}
        for qid, title in quests.items():
            cands = eg_texts.get((qid, key))
            if world.get(qid) and (world[qid][col] or "").strip():
                continue
            if not cands:
                if (qid, key) in eg_empty:      # the gap report lists it: EG Link has the record, but no text in it
                    sl.held.append({"quest": qid, "name": title, "category": cat, "what": f"quest {qid} {title}: {key} text",
                                    "reason": "EG Link's record has no text", "why": "EG Link's record has no text"})
                    sl.outcome(cat, qid, "held back")
                continue
            vote = source_weights.resolve("quest_text", cands)
            what = f"quest {qid} {title}: {'progress' if key == 'progress' else 'completion'} text"
            entry = {"quest": qid, "name": title, "category": cat, "what": what, "value": vote["value"], "sources": vote["sources"],
                     "runner_up": vote["runner_up"]}
            if custom_touched(qid):
                sl.held.append(dict(entry, reason=CUSTOM_FILE, why=CUSTOM_FILE))
                sl.outcome(cat, qid, "held back")
            elif vote["conflict"]:
                sl.review.append(dict(entry, why="close call: the sources (or one source's variants) give different texts"))
                sl.outcome(cat, qid, "review")
            elif qid not in world:
                # emotes take the default 0 (none), like every sniffed Forever row; VerifiedBuild 0: not a sniff
                row = {"ID": qid, col: vote["value"], "note": note(vote["sources"]), "why": title}
                sl.adds[table].append(row)
                sl.outcome(cat, qid, "added")
            else:
                fix = len(sl.fixes) + 1
                sl.fixes.append(dict(entry, fix=fix, kind="update", table=table, key={"ID": qid},
                                     against={c: world[qid][c] for c in cols}, set={col: vote["value"]}))
                sl.outcome(cat, qid, "corrected")

    # ---- 3. quest text, where the world's is empty (a correction: the quest's row is the fork's)
    for qid, title in quests.items():
        if (tc_q[qid]["QuestDescription"] or "").strip():
            continue
        vote = source_weights.resolve("quest_text", [c for c in qc.get(qid, {}).get("quest_text", []) if not c[1].startswith("tc-")])
        if not vote:
            continue
        what, cat = f"quest {qid} {title}: quest text", "quests_no_text"
        entry = {"quest": qid, "name": title, "category": cat, "what": what, "value": vote["value"], "sources": vote["sources"],
                 "runner_up": vote["runner_up"]}
        if custom_touched(qid):
            sl.held.append(dict(entry, reason=CUSTOM_FILE, why=CUSTOM_FILE))
            sl.outcome(cat, qid, "held back")
        elif vote["conflict"] or vote["classic_only"]:
            sl.review.append(dict(entry, why="close call between sources" if vote["conflict"] else "only Classic data gives it"))
            sl.outcome(cat, qid, "review")
        else:
            cols = list(col_info["quest_template"])
            row = rows(cur, f"SELECT * FROM {W}quest_template WHERE ID = %s", (qid,))[0]
            fix = len(sl.fixes) + 1
            sl.fixes.append(dict(entry, fix=fix, kind="update", table="quest_template", key={"ID": qid},
                                 against={c: row[c] for c in cols}, set={"QuestDescription": vote["value"]}))
            sl.outcome(cat, qid, "corrected")

    # ---- 4. objectives, for quests the world has none for
    with_obj = {r["QuestID"] for r in rows(cur, f"SELECT DISTINCT QuestID FROM {W}quest_objectives WHERE QuestID IN ({ids_sql(quests)})")}
    want = {r["id"] for r in rows(cur, f"SELECT DISTINCT id FROM {F}.src_forever_db WHERE tbl = 'quest_objective' AND id IN ({ids_sql(quests)})")}
    for r in rows(cur, f"SELECT id, data FROM {F}.src_eg_link WHERE tbl = 'objectives' AND id IN ({ids_sql(quests)})"):
        d = candidates.j(r["data"])
        if isinstance(d, dict) and any(k.isdigit() and isinstance(v, dict) and v.get("type") for k, v in d.items()):
            want.add(r["id"])
    todo = sorted(want - with_obj)
    eg_obj = {}
    for r in rows(cur, f"SELECT id, data FROM {F}.src_eg_link WHERE tbl = 'quests.enUS' AND id IN ({ids_sql(todo)})"):
        d = candidates.j(r["data"])
        b = gap_report.build_no(d.get("_build"))
        if d.get("objectives") and (r["id"] not in eg_obj or b > eg_obj[r["id"]][0]):
            eg_obj[r["id"]] = (b, d["objectives"])
    fdb_obj = collections.defaultdict(set)
    for r in rows(cur, f"SELECT id, data FROM {F}.src_forever_db WHERE tbl = 'quest_objective' AND id IN ({ids_sql(todo)})"):
        d = candidates.j(r["data"])
        fdb_obj[r["id"]].add((FDB_KIND.get(d.get("kind"), str(d.get("kind"))), candidates.as_int(d.get("target")), candidates.as_int(d.get("count"))))
    obj_ids = {o.get("id") for _, objs in eg_obj.values() for o in objs}
    taken = {r["ID"]: r["QuestID"] for r in rows(cur, f"SELECT ID, QuestID FROM {W}quest_objectives WHERE ID IN ({ids_sql(obj_ids)})")}
    targets = collections.defaultdict(set)
    for _, objs in eg_obj.values():
        for o in objs:
            if o.get("typeId") in OBJECTIVE_KIND:
                targets[OBJECTIVE_KIND[o["typeId"]]].add(o.get("objectId"))
    known = {"npc": {r["entry"] for r in rows(cur, f"SELECT entry FROM {W}creature_template WHERE entry IN ({ids_sql(targets['npc'])})")},
             "object": {r["entry"] for r in rows(cur, f"SELECT entry FROM {W}gameobject_template WHERE entry IN ({ids_sql(targets['object'])})")},
             "item": {r["id"] for r in rows(cur, f"SELECT id FROM {F}.src_forever_db WHERE tbl = 'item' AND id IN ({ids_sql(targets['item'])})")}}
    cat = "quests_no_objectives"
    for qid in todo:
        if qid not in quests:
            continue
        title = quests[qid]
        what = f"quest {qid} {title}: objectives"
        fdb = sorted(fdb_obj.get(qid, ()), key=str)
        if qid not in eg_obj:
            sl.held.append({"quest": qid, "name": title, "category": cat, "what": what, "forever_db": fdb,
                            "reason": "objectives: Forever's objective ids aren't recorded",
                            "why": "Forever's objective ids aren't recorded: forever-db lists kind, target and count only, and no "
                                   "EG Link quest record has the objectives"})
            sl.outcome(cat, qid, "held back")
            continue
        build, objs = eg_obj[qid]
        eg_set = {(OBJECTIVE_KIND.get(o.get("typeId"), f"type{o.get('typeId')}"), o.get("objectId"), o.get("amount")) for o in objs}
        entry = {"quest": qid, "name": title, "category": cat, "what": what, "eg_link": objs, "build": build, "forever_db": fdb}
        # compare what both can say: forever-db files area triggers and reputations under other kinds, and has no count
        # for some objectives (None: not compared)
        other_ids = {x[1] for x in eg_set if x[0] not in FDB_KIND.values()}
        mine = {x for x in fdb_obj[qid] if x[0] in FDB_KIND.values() and x[1] not in other_ids}
        theirs = {x for x in eg_set if x[0] in FDB_KIND.values()}
        if fdb and ({x[:2] for x in mine} != {x[:2] for x in theirs}
                    or any(c is not None and (k, t, c) not in theirs for k, t, c in mine)):
            sl.review.append(dict(entry, why="EG Link's and forever-db's objectives differ"))
            sl.outcome(cat, qid, "review")
            continue
        problems = []
        if flags is None:
            problems.append("objective Flags and Flags2 aren't recorded by any source (sniffed Forever objectives use "
                            "Flags 32 for 94% and Flags2 0 or 1): decide them with --objective-flags")
        for o in objs:
            if o.get("id") in taken:
                problems.append(f"objective id {o['id']} is the fork's objective of quest {taken[o['id']]}")
            kind = OBJECTIVE_KIND.get(o.get("typeId"))
            if kind is None:
                problems.append(f"objective {o.get('id')} is a {o.get('type') or 'type ' + str(o.get('typeId'))} objective, "
                                "which needs more than a quest_objectives row (area trigger or reputation set-up): not in slice 1")
            elif o.get("objectId") not in known[kind]:
                problems.append(f"objective {o.get('id')}'s {kind} {o.get('objectId')} isn't in the world")
        if custom_touched(qid):
            problems.append("a fork custom file not loaded into the world yet writes this quest's rows")
        if problems:
            sl.held.append(dict(entry, why="; ".join(dict.fromkeys(problems)),
                                reason="objectives: " + ("Flags not recorded" if flags is None else "see why")))
            sl.outcome(cat, qid, "held back")
            continue
        for order, o in enumerate(objs):
            sl.adds["quest_objectives"].append({
                "ID": o["id"], "QuestID": qid, "Type": o["typeId"], "Order": order, "StorageIndex": o["storageIndex"],
                "ObjectID": o["objectId"], "Amount": o["amount"], "ConditionalAmount": 0, "Flags": flags[0], "Flags2": flags[1],
                "ProgressBarWeight": 0.0, "ParentObjectiveID": 0, "Visible": 1, "Description": o.get("text") or "",
                "VerifiedBuild": 0, "note": note([f"eg-link@{build}"] + (["forever-db"] if fdb else [])),
                "why": f"{title}: {o.get('type') or o['typeId']} {o['objectId']} x{o['amount']}"})
        sl.outcome(cat, qid, "added")

    write(args, names, sl, pins, world_label, col_info, types, flags)


def write(args, names, sl, pins, world_label, col_info, types, flags):
    sql_dir = os.path.join(args.out, "sql", "world")
    meta_dir = os.path.join(args.out, SLICE)
    os.makedirs(sql_dir, exist_ok=True)
    os.makedirs(meta_dir, exist_ok=True)

    def ddl(table):
        return col_info[table]

    # ---- the import file: rows the world is missing
    name = names["import"]
    out = isql.file_header("Everlake world import, slice 1: quest givers, enders, objectives, progress and completion texts",
                           name, pins, world_label, LICENCE)
    out += [isql.IMPORT_ROWS_DDL, ""]
    giver_guard = {}
    for role in ("start", "end"):
        a, b = GIVER_TABLES[(role, "npc")], GIVER_TABLES[(role, "object")]
        giver_guard[role] = isql.not_others(a, "quest", ["id", "quest"]) + " AND " + isql.not_others(b, "quest", ["id", "quest"])
    for (role, kind), table in GIVER_TABLES.items():
        out += isql.stage_block(table, ["id", "quest", "VerifiedBuild"], ["id", "quest"], sl.adds.get(table, []), name,
                                giver_guard[role], f"{table}: {'givers' if role == 'start' else 'enders'} for quests the world has "
                                "none for (only while the quest still has none but these)", ddl(table))
    out += isql.stage_block("quest_objectives", OBJECTIVE_COLUMNS, ["ID"], sl.adds.get("quest_objectives", []), name,
                            isql.not_others("quest_objectives", "QuestID", ["ID"], "s.`QuestID`"),
                            "quest_objectives: objectives with Forever's own ids, for quests the world has none for", ddl("quest_objectives"))
    for table, what in (("quest_request_items", "progress texts"), ("quest_offer_reward", "completion texts")):
        out += isql.stage_block(table, ["ID", TEXT_COLUMN[table]], ["ID"], sl.adds.get(table, []), name, None,
                                f"{table}: {what} for quests the world has no row for", ddl(table))
    files = {name: "\n".join(out).rstrip() + "\n"}

    # ---- the corrections file
    name = names["corrections"]
    out = isql.file_header("Everlake world import, slice 1 corrections: fork rows changed, each only while it is still as "
                           "written against", name, pins, world_label, LICENCE)
    out += [isql.IMPORT_ROWS_DDL, "",
            "-- Every correction's guard is checked first, against the world as it is before any of them acts.",
            f"DROP TEMPORARY TABLE IF EXISTS `{isql.FIX_OK}`;",
            f"CREATE TEMPORARY TABLE `{isql.FIX_OK}` (`fix` int NOT NULL, PRIMARY KEY (`fix`)) ENGINE=InnoDB;"]
    if sl.fixes:
        out.append(f"INSERT INTO `{isql.FIX_OK}` (`fix`) VALUES " + ", ".join(f"({f['fix']})" for f in sl.fixes) + ";")
    for f in sl.fixes:
        out.append(f"-- fix {f['fix']}: {isql.comment(f['what'])}" + (f": {', '.join(f['world'])} -> {', '.join(f['vote'])}"
                                                                     if f["kind"] == "relations" else ""))
        if f["kind"] == "relations":
            q = f["quest"]
            conds = []
            for table in sorted({t for (r, _), t in GIVER_TABLES.items() if r == f["role"]}):
                rows_t = [a for a in f["against"] if a["table"] == table]
                conds.append(f"(SELECT COUNT(*) FROM `{table}` g WHERE g.`quest` = {q}) = {len(rows_t)}")
                if rows_t:
                    match = " OR ".join(f"(g.`id` = {a['id']} AND g.`VerifiedBuild` = {a['VerifiedBuild']})" for a in rows_t)
                    conds.append(f"(SELECT COUNT(*) FROM `{table}` g WHERE g.`quest` = {q} AND ({match})) = {len(rows_t)}")
            guard = " AND ".join(conds)
        else:
            key = " AND ".join(f"t.{isql.ident(k)} = {isql.lit(v)}" for k, v in f["key"].items())
            # the value it changes and the row's VerifiedBuild (the fork re-sniffing a row changes it): naming every
            # column would make the file fail on a re-run once a later fork file changes the table's columns
            against = {c: f["against"][c] for c in [*f["set"], "VerifiedBuild"] if c in f["against"]}
            guard = f"EXISTS (SELECT 1 FROM {isql.ident(f['table'])} t WHERE {key} AND {isql.row_guard('t', against, types(f['table']))})"
        out.append(f"DELETE FROM `{isql.FIX_OK}` WHERE `fix` = {f['fix']} AND NOT ({guard});")
    out.append("")
    for f in sl.fixes:
        if f["kind"] != "relations":
            continue
        for d in f["delete"]:
            out.append(f"DELETE t FROM `{d['table']}` t JOIN `{isql.FIX_OK}` ok ON ok.`fix` = {f['fix']} "
                       f"WHERE t.`id` = {d['id']} AND t.`quest` = {d['quest']}; -- fix {f['fix']}")
    if any(f["kind"] == "relations" and f["delete"] for f in sl.fixes):
        out.append("")
    for table in GIVER_TABLES.values():
        add_rows = [dict(a, fix=f["fix"], why=f"fix {f['fix']}: {f['name']}") for f in sl.fixes if f["kind"] == "relations"
                    for a in f["add"] if a["table"] == table]
        out += isql.stage_block(table, ["id", "quest", "VerifiedBuild"], ["id", "quest"],
                                [{k: v for k, v in a.items() if k != "table"} for a in add_rows], name, None,
                                f"{table}: the vote's members the fork lacks, for the corrections above", ddl(table))
    for f in sl.fixes:
        if f["kind"] != "update":
            continue
        sets = ", ".join(f"t.{isql.ident(c)} = {isql.lit(v)}" for c, v in f["set"].items())
        key = " AND ".join(f"t.{isql.ident(k)} = {isql.lit(v)}" for k, v in f["key"].items())
        out.append(f"-- fix {f['fix']}: {isql.comment(f['what'])} ({isql.comment(', '.join(f['sources']))})")
        out.append(f"UPDATE `{f['table']}` t JOIN `{isql.FIX_OK}` ok ON ok.`fix` = {f['fix']} SET {sets} WHERE {key};")
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

    manifest = {"slice": SLICE, "pins": pins, "world": world_label, "objective_flags": flags,
                "files": [{"name": n, "kind": k, "sha1": hashlib.sha1(files[n].encode()).hexdigest().upper()} for k, n in names.items()],
                "adds": {t: [{k: v for k, v in r.items()} for r in rs] for t, rs in sorted(sl.adds.items())},
                "fixes": sl.fixes, "review": sl.review, "held_back": sl.held,
                "outcomes": {c: {str(q): o for q, o in sorted(v.items())} for c, v in sorted(sl.outcomes.items())}}
    with open(os.path.join(meta_dir, "manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True, default=str)
    with open(os.path.join(meta_dir, "review.md"), "w") as handle:
        handle.write(listing("Slice 1: close calls (not in the files)", "A person decides these; the vote was too close, or "
                             "the sources disagree.", sl.review))
    with open(os.path.join(meta_dir, "held-back.md"), "w") as handle:
        handle.write(listing("Slice 1: held back", "Rows that need something we don't have, and why. Nothing here was guessed.",
                             sl.held))
    counts = {t: len(r) for t, r in sorted(sl.adds.items())}
    print(f"wrote {sql_dir}: " + ", ".join(f"{n} {t}" for t, n in counts.items()) + f"; {len(sl.fixes)} corrections; "
          f"{len(sl.review)} close calls, {len(sl.held)} held back (in {meta_dir})")


def listing(title, intro, items):
    out = [f"# {title}", "", intro, ""]
    by_cat = collections.defaultdict(list)
    for i in items:
        by_cat[i.get("category", "other")].append(i)
    for cat, its in sorted(by_cat.items()):
        out += [f"## {cat} ({len(its)})", ""]
        for i in sorted(its, key=lambda x: x["quest"]):
            line = f"- {i['what']}: {i['why']}"
            if "world" in i and "vote" in i:
                line += f". World: {', '.join(i['world']) or 'none'}; vote: {', '.join(i['vote'])}; weights {i['weights']}"
            if i.get("value") and i.get("runner_up"):
                line += f". Winner ({', '.join(i['sources'])}): \"{shorten(i['value'])}\"; runner-up ({', '.join(i['runner_up']['sources'])}): " \
                        f"\"{shorten(i['runner_up']['value'])}\""
            out.append(line.replace("\n", " "))
        out.append("")
    return "\n".join(out)


def shorten(text, n=160):
    text = re.sub(r"\s+", " ", str(text))
    return text if len(text) <= n else text[:n] + "..."


if __name__ == "__main__":
    main()
