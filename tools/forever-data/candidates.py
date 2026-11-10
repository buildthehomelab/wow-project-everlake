"""Every source's value for each quest and NPC field, ready for source_weights.resolve() / resolve_set().

Each function takes a cursor on the server (acore_forever) and a set of ids, and returns {id: {field: [(value, source,
build)]}}. The source names are the keys of source_weights.W. TrinityCore rows count as "tc-sniff" when their
VerifiedBuild is a Forever build (69800 and up: beta sniffs) and as "tc-vmangos" otherwise (the converted Classic world).
"""
import collections
import json
import re

F = "acore_forever"
# the world being compared: the fork's world as load_tc.py keeps it (acore_forever.tc_*), or another copy of it
# (gap_report.py --world, the dry runs of import_slice1.py)
WORLD = f"{F}.tc_"
FOREVER_BUILD = 69800      # Forever beta and live builds start here; TrinityCore's retail rows carry 69497 and below
TRACE_QUEST = "src/corrections/Forever/traces/foreverQuestTraces.lua:ForeverQuestTraces:Load"
TRACE_NPC = "src/corrections/Forever/traces/foreverNpcTraces.lua:ForeverNpcTraces:Load"
FIX_QUEST = "src/corrections/Forever/foreverQuestFixes.lua:ForeverQuestFixes:Load"
GEN_QUEST = "src/corrections/Forever/generated/foreverBaseQuest.lua:ForeverBaseQuest:Load"
BASE_QUEST = "data/Forever/foreverQuestDB.lua:QuestieDB.questData"
BASE_NPC = "data/Forever/foreverNpcDB.lua:QuestieDB.npcData"
# QuestieDB's positional keys (data/Forever/*DB.lua headers)
QK = {"name": 1, "startedBy": 2, "finishedBy": 3, "requiredLevel": 4, "questLevel": 5, "objectivesText": 8, "objectives": 10}
NK = {"name": 1, "minLevel": 4, "maxLevel": 5, "rank": 6, "factionID": 12, "subName": 14}


def rows(cur, sql, args=None):
    cur.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def ids_sql(ids):
    return ",".join(str(int(i)) for i in ids) or "0"


def j(value):
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def pos(row, index):
    """Element `index` (1-based) of a QuestieDB positional row, which arrives as a list or a {"1": ...} dict."""
    if isinstance(row, list):
        return row[index - 1] if 0 < index <= len(row) else None
    if isinstance(row, dict):
        return row.get(str(index))
    return None


def as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return [v[k] for k in sorted(v, key=lambda k: int(k) if k.isdigit() else 0) if k.isdigit()]
    return [v]


def as_int(v):
    """An integer id, or None for anything else (strings, nulls, floats with a fraction)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdecimal():
        try:
            return int(v)
        except ValueError:
            return None
    return None


def givers_from_questie(value):
    """{{npcs},{objects},{items}} -> [("npc", id), ("object", id), ("item", id)]. Positions matter (a sparse
    {"1": npcs, "3": items} must keep items third), so groups are read by position, not compacted."""
    out = []
    for index, kind in enumerate(("npc", "object", "item"), 1):
        out += [(kind, i) for i in (as_int(x) for x in as_list(pos(value, index))) if i is not None]
    return out


def tc_source(build):
    return "tc-sniff" if (build or 0) >= FOREVER_BUILD else "tc-vmangos"


def wowhead_objectives(tooltip):
    """A Wowhead quest tooltip's objective text, every paragraph of it.

    The tooltip is the name table, then a body cell that opens with <br /> and holds the objective paragraphs
    (separated by <br /><br />) up to the first <span class="q"> heading ("Requirements:", "Provided:"). Paragraphs come
    back joined with a blank line, as quest text is stored; same_text() ignores the exact spacing when votes compare.

    Wowhead shows the player stand-ins the client fills in (<name>, <race>, <class>, <brother/sister>); they go back to
    WoW's tokens ($N, $R, $C, $gbrother:sister;) so the text can be stored and compares equal to other sources."""
    import html
    tooltip = tooltip or ""
    start = re.search(r"<td>\s*<br\s*/?>", tooltip)
    if not start:
        return None
    body = tooltip[start.end():]
    body = re.split(r"<span class=\"q\">|</td>", body, maxsplit=1)[0]
    text = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", body)))
    text = re.sub(r"<(name|race|class)>", lambda m: "$" + m.group(1)[0].upper(), text, flags=re.I)
    text = re.sub(r"<([A-Za-z'-]+)\s*/\s*([A-Za-z'-]+)>", r"$g\1:\2;", text)      # one word each side: <lad/lass>
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    paragraphs = [p for p in paragraphs if p]
    return "\r\n\r\n".join(paragraphs) or None


def quests(cur, ids):
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    if not ids:
        return out
    s = ids_sql(ids)

    def add(qid, field, value, source, build=None):
        if value in (None, "", [], {}):
            return
        out[int(qid)][field].append((value, source, build))

    # TrinityCore
    for r in rows(cur, f"SELECT t.ID, t.LogTitle, t.LogDescription, t.QuestDescription, t.QuestCompletionLog, t.VerifiedBuild, "
                       f"l.QuestLevel, l.MinLevel FROM {WORLD}quest_template t LEFT JOIN {WORLD}quest_classic_level l ON l.ID = t.ID "
                       f"WHERE t.ID IN ({s})"):
        src = tc_source(r["VerifiedBuild"])
        add(r["ID"], "name", r["LogTitle"], src, r["VerifiedBuild"])
        add(r["ID"], "quest_text", r["QuestDescription"], src, r["VerifiedBuild"])
        add(r["ID"], "objectives_text", r["LogDescription"], src, r["VerifiedBuild"])
        if r["QuestLevel"] is not None:
            add(r["ID"], "level", r["QuestLevel"], src, r["VerifiedBuild"])
        if r["MinLevel"]:
            add(r["ID"], "min_level", r["MinLevel"], src, r["VerifiedBuild"])
    builds = {r["ID"]: r["VerifiedBuild"] for r in rows(cur, f"SELECT ID, VerifiedBuild FROM {WORLD}quest_template WHERE ID IN ({s})")}
    for table, field in (("creature_queststarter", "quest_giver"), ("gameobject_queststarter", "quest_giver"),
                         ("creature_questender", "quest_ender"), ("gameobject_questender", "quest_ender")):
        kind = "npc" if table.startswith("creature") else "object"
        # the relation row's own build says whether it was sniffed; a re-sniffed quest can keep Classic givers
        for r in rows(cur, f"SELECT id, quest, VerifiedBuild FROM {WORLD}{table} WHERE quest IN ({s})"):
            add(r["quest"], field, (kind, r["id"]), tc_source(r["VerifiedBuild"]), r["VerifiedBuild"])
    for r in rows(cur, f"SELECT QuestID, Type, ObjectID FROM {WORLD}quest_objectives WHERE QuestID IN ({s})"):
        kind = {0: "npc", 3: "npc", 1: "item", 2: "object"}.get(r["Type"], f"type{r['Type']}")
        add(r["QuestID"], "objective", (kind, r["ObjectID"]), tc_source(builds.get(r["QuestID"])), builds.get(r["QuestID"]))

    # forever-db (client tables at a beta build plus independent sources)
    for r in rows(cur, f"SELECT tbl, id, data FROM {F}.src_forever_db WHERE id IN ({s}) AND tbl IN "
                       f"('quest', 'quest_start', 'quest_end', 'quest_objective')"):
        d = j(r["data"])
        if r["tbl"] == "quest":
            add(r["id"], "name", d.get("title"), "forever-db")
            if d.get("level") is not None:
                add(r["id"], "level", d["level"], "forever-db")
            if d.get("min_level"):
                add(r["id"], "min_level", d["min_level"], "forever-db")
        elif r["tbl"] in ("quest_start", "quest_end") and d.get("kind") in ("npc", "object", "item") and as_int(d.get("id")) is not None:
            add(r["id"], "quest_giver" if r["tbl"] == "quest_start" else "quest_ender", (d["kind"], as_int(d["id"])), "forever-db")
        elif r["tbl"] == "quest_objective" and as_int(d.get("target")) is not None:
            kind = {"kill": "npc", "talk": "npc", "item": "item", "object": "object"}.get(d.get("kind"), str(d.get("kind")))
            add(r["id"], "objective", (kind, as_int(d["target"])), "forever-db")

    # QuestieDB: player traces, hand fixes and the generated delta (Forever), the base database (Classic-derived)
    for r in rows(cur, f"SELECT tbl, id, data FROM {F}.src_questiedb WHERE id IN ({s}) AND tbl IN (%s, %s, %s, %s)",
                  (TRACE_QUEST, FIX_QUEST, GEN_QUEST, BASE_QUEST)):
        d = j(r["data"])
        src = {TRACE_QUEST: "questietrace", FIX_QUEST: "questiedb-fixes", GEN_QUEST: "questiedb-fixes", BASE_QUEST: "questiedb-classic"}[r["tbl"]]
        if r["tbl"] == BASE_QUEST:
            d = {"name": pos(d, QK["name"]), "startedBy": pos(d, QK["startedBy"]), "finishedBy": pos(d, QK["finishedBy"]),
                 "questLevel": pos(d, QK["questLevel"]), "requiredLevel": pos(d, QK["requiredLevel"])}
        if not isinstance(d, dict):
            continue
        add(r["id"], "name", d.get("name"), src)
        if isinstance(d.get("questLevel"), (int, float)):
            add(r["id"], "level", int(d["questLevel"]), src)
        if isinstance(d.get("requiredLevel"), (int, float)) and d["requiredLevel"] > 0:
            add(r["id"], "min_level", int(d["requiredLevel"]), src)
        for key, field in (("startedBy", "quest_giver"), ("startedBy_add", "quest_giver"), ("finishedBy", "quest_ender"),
                           ("finishedBy_add", "quest_ender")):
            for g in givers_from_questie(d.get(key)):
                add(r["id"], field, g, src)
        objectives = as_list(d.get("objectives"))
        for kind, group in zip(("npc", "object", "item"), objectives + [None] * 3):
            for o in as_list(group):
                target = as_list(o)[0] if as_list(o) else None
                if isinstance(target, (int, float)):
                    add(r["id"], "objective", (kind, int(target)), src)

    # ForeverDB: "title|level|min|objective text|starts|ends|players who saw it|new"
    for r in rows(cur, f"SELECT id, data FROM {F}.src_foreverdb_net WHERE tbl = 'QuestForever.qfQuests' AND id IN ({s})"):
        d = j(r["data"])
        parts = (d.get("value") or "").split("|") if isinstance(d, dict) and isinstance(d.get("value"), str) else []
        if len(parts) < 8:
            continue
        seen = int(parts[6]) if parts[6].isdecimal() else 0
        src = "foreverdb-seen" if seen >= 2 else "foreverdb-unconfirmed" if seen == 1 else "cmangos-classic"
        add(r["id"], "name", parts[0], src)
        add(r["id"], "objectives_text", parts[3], src)
        if parts[1].lstrip("-").isdecimal():
            add(r["id"], "level", int(parts[1]), src)
        if parts[2].isdecimal() and int(parts[2]) > 0:         # 0 = not known to ForeverDB
            add(r["id"], "min_level", int(parts[2]), src)
        for field, text in (("quest_giver", parts[4]), ("quest_ender", parts[5])):
            for kind, gid in re.findall(r"([noi])(\d+)", text):
                add(r["id"], field, ({"n": "npc", "o": "object", "i": "item"}[kind], int(gid)), src)

    # EG Link (beta and live builds; newest wins on ties)
    for r in rows(cur, f"SELECT id, data FROM {F}.src_eg_link WHERE tbl = 'quests.enUS' AND id IN ({s})"):
        d = j(r["data"])
        build = int(str(d.get("_build", "0")).split(".")[-1] or 0)
        add(r["id"], "name", d.get("title"), "eg-link", build)
        add(r["id"], "quest_text", d.get("description"), "eg-link", build)
        add(r["id"], "objectives_text", d.get("objectivesText"), "eg-link", build)
        if d.get("level") is not None:
            add(r["id"], "level", d["level"], "eg-link", build)
        if d.get("minLevel"):
            add(r["id"], "min_level", d["minLevel"], "eg-link", build)

    # Wowhead tooltips: name and the objective sentence
    for r in rows(cur, f"SELECT id, data FROM {F}.src_wowhead_tooltips WHERE tbl = 'quest' AND id IN ({s})"):
        d = j(r["data"])
        if d.get("status") != "ok" or not d.get("data"):
            continue
        add(r["id"], "name", d["data"].get("name"), "wowhead")
        text = wowhead_objectives(d["data"].get("tooltip"))
        if text:
            add(r["id"], "objectives_text", text, "wowhead")
    return out


def npcs(cur, ids):
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    if not ids:
        return out
    s = ids_sql(ids)

    def add(nid, field, value, source, build=None):
        if value not in (None, "", [], {}):
            out[int(nid)][field].append((value, source, build))

    for r in rows(cur, f"SELECT t.entry, t.name, t.subname, t.faction, t.Classification, t.VerifiedBuild, l.level_min, l.level_max "
                       f"FROM {WORLD}creature_template t LEFT JOIN {WORLD}creature_classic_level l ON l.entry = t.entry WHERE t.entry IN ({s})"):
        src = tc_source(r["VerifiedBuild"])
        add(r["entry"], "name", r["name"], src, r["VerifiedBuild"])
        add(r["entry"], "subname", r["subname"], src, r["VerifiedBuild"])
        add(r["entry"], "faction", r["faction"], src, r["VerifiedBuild"])
        add(r["entry"], "rank", r["Classification"], src, r["VerifiedBuild"])
        if r["level_min"]:
            add(r["entry"], "level", [r["level_min"], r["level_max"] or r["level_min"]], src, r["VerifiedBuild"])
    for r in rows(cur, f"SELECT CreatureID, GROUP_CONCAT(CreatureDisplayID ORDER BY Idx) AS displays, MAX(VerifiedBuild) AS vb "
                       f"FROM {WORLD}creature_template_model WHERE CreatureID IN ({s}) GROUP BY CreatureID"):
        add(r["CreatureID"], "model", [int(x) for x in r["displays"].split(",")], tc_source(r["vb"]), r["vb"])
    dbf_npcs(cur, s, add)
    for r in rows(cur, f"SELECT id, data FROM {F}.src_forever_db WHERE tbl = 'npc' AND id IN ({s})"):
        d = j(r["data"])
        add(r["id"], "name", d.get("name"), "forever-db")
        add(r["id"], "subname", d.get("subname"), "forever-db")
        add(r["id"], "faction", d.get("faction_template"), "forever-db")
        add(r["id"], "rank", d.get("rank"), "forever-db")
        if d.get("level_min"):
            add(r["id"], "level", [d["level_min"], d.get("level_max") or d["level_min"]], "forever-db")
    for r in rows(cur, f"SELECT tbl, id, data FROM {F}.src_questiedb WHERE id IN ({s}) AND tbl IN (%s, %s)", (TRACE_NPC, BASE_NPC)):
        d = j(r["data"])
        if r["tbl"] == BASE_NPC:
            add(r["id"], "name", pos(d, NK["name"]), "questiedb-classic")
            if pos(d, NK["minLevel"]):
                add(r["id"], "level", [pos(d, NK["minLevel"]), pos(d, NK["maxLevel"]) or pos(d, NK["minLevel"])], "questiedb-classic")
        elif isinstance(d, dict):
            add(r["id"], "name", d.get("name"), "questietrace")
            if d.get("minLevel"):
                add(r["id"], "level", [d["minLevel"], d.get("maxLevel") or d["minLevel"]], "questietrace")
            add(r["id"], "rank", d.get("rank"), "questietrace")
    for r in rows(cur, f"SELECT id, data FROM {F}.src_eg_link WHERE tbl = 'creature_details.enUS' AND id IN ({s})"):
        d = j(r["data"])
        build = int(str(d.get("_build", "0")).split(".")[-1] or 0)
        add(r["id"], "name", d.get("name"), "eg-link", build)
        displays = [x.get("id") if isinstance(x, dict) else x for x in as_list(d.get("displays"))]
        add(r["id"], "model", [int(x) for x in displays if isinstance(x, (int, float))], "eg-link", build)
    for r in rows(cur, f"SELECT id, data FROM {F}.src_wowhead_tooltips WHERE tbl = 'npc' AND id IN ({s})"):
        d = j(r["data"])
        if d.get("status") != "ok" or not d.get("data"):
            continue
        add(r["id"], "name", d["data"].get("name"), "wowhead")
        m = re.search(r"Level (\d+)(?:\s*-\s*(\d+))?", re.sub(r"<[^>]+>", " ", d["data"].get("tooltip") or ""))
        if m:
            add(r["id"], "level", [int(m.group(1)), int(m.group(2) or m.group(1))], "wowhead")
    return out


DBF = f"{F}.dbf_"


def has_source(cur, source):
    """Whether load_sources.py has loaded this source (its src_ table exists in acore_forever)."""
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
                (F, "src_" + re.sub(r"[^a-z0-9]", "_", source.lower())))
    return cur.fetchone()[0] > 0


def has_dbf(cur):
    """Whether load_dbf.py has loaded DatabaseForever (dbf_* tables) into acore_forever."""
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s AND table_name = 'dbf_creature_template'", (F,))
    return cur.fetchone()[0] > 0


def dbf_npcs(cur, s, add):
    """DatabaseForever's NPC fields, as source "databaseforever", for the NPCs the fork world lacks only. It started from
    the same fork world as tc_*: on the NPCs both have, its values are the fork's (counting them would count the fork
    twice) or bulk defaults (faction 35 on 15,000 of them), so they don't vote."""
    if not has_dbf(cur):
        return
    sql = (f"SELECT d.entry, d.name, d.subname, d.faction, d.Classification, dl.level_min, dl.level_max, "
           f"GROUP_CONCAT(m.CreatureDisplayID ORDER BY m.Idx) AS displays "
           f"FROM {DBF}creature_template d LEFT JOIN {WORLD}creature_template t ON t.entry = d.entry "
           f"LEFT JOIN {DBF}creature_classic_level dl ON dl.entry = d.entry "
           f"LEFT JOIN {DBF}creature_template_model m ON m.CreatureID = d.entry "
           f"WHERE d.entry IN ({s}) AND t.entry IS NULL GROUP BY d.entry")
    for r in rows(cur, sql):
        add(r["entry"], "name", r["name"], "databaseforever")
        add(r["entry"], "subname", r["subname"], "databaseforever")
        add(r["entry"], "faction", r["faction"], "databaseforever")
        add(r["entry"], "rank", r["Classification"], "databaseforever")
        if r["level_min"]:
            add(r["entry"], "level", [r["level_min"], r["level_max"] or r["level_min"]], "databaseforever")
        if r["displays"]:
            add(r["entry"], "model", [int(x) for x in r["displays"].split(",")], "databaseforever")
