"""How much each Forever source is trusted, per kind of data, and how one value is picked when sources disagree.

Everlake's Forever data pulls the same facts (a quest's giver, an NPC's level, an item's price, a vendor's stock) from many sources.
None is complete or always right, so every candidate value carries its source's weight for that field, and resolve()
picks the value with the most weight behind it. Agreement adds up: two middling sources that agree beat one good source
alone. Every pick keeps its provenance (which sources, which builds) and a confidence, and close calls are flagged for a
person to look at instead of being decided silently.

Weights are 0-100. They reflect what each source actually is:
- what players saw in the live game since launch (QuestieTrace corrections, ForeverDB "seen" rows) is the best evidence
  for anything the server decides (givers, spawns, prices, stock, drops);
- the live client's own tables (wago DB2, the item/spell history) are authoritative for what the client holds (names,
  item and spell data, areas, factions), but say nothing about server-side behaviour;
- beta data (TrinityCore's sniffs, EG Link, forever-db at a beta build) is real Forever data that may have changed;
- Classic data (VMaNGOS, CMaNGOS, QuestieDB's Classic base) is only a fallback and never beats Forever data.
"""

# field groups a source can speak to
FIELDS = ("name", "level", "quest_giver", "quest_text", "quest_objectives", "quest_rewards", "spawn", "vendor_stock",
          "price", "drops", "item_stats", "spell_data", "model", "faction", "zone")

W = {
    # live play, recorded by players' addons
    "questietrace":      {"quest_giver": 90, "spawn": 85, "level": 85, "quest_objectives": 80, "drops": 75, "name": 80, "zone": 80},
    "foreverdb-seen":    {"vendor_stock": 90, "price": 90, "quest_rewards": 85, "drops": 80, "level": 80, "item_stats": 85},
    "foreverdb-unconfirmed": {"vendor_stock": 60, "price": 60, "quest_rewards": 55, "drops": 55, "level": 55, "item_stats": 60},
    # live client data
    "wago":              {"name": 95, "faction": 95, "zone": 95, "spell_data": 90, "item_stats": 85, "model": 90},
    "item-history":      {"item_stats": 90, "spell_data": 90, "name": 90, "price": 70},
    # Wowhead's tooltips: live, built from client data plus players running the Wowhead Client; spell tooltips can lag
    "wowhead":           {"name": 85, "level": 75, "item_stats": 80, "quest_objectives": 75, "quest_text": 60, "drops": 70,
                          "spawn": 70, "spell_data": 50},
    # beta and curated data
    "forever-db":        {"name": 80, "level": 70, "quest_giver": 75, "quest_objectives": 75, "quest_rewards": 70, "spawn": 70,
                          "zone": 75, "drops": 60, "quest_text": 0},
    "tc-sniff":          {"quest_text": 80, "quest_giver": 70, "vendor_stock": 70, "spawn": 75, "model": 80, "level": 65,
                          "quest_objectives": 75, "quest_rewards": 70, "drops": 50, "name": 75},
    "eg-link":           {"quest_text": 70, "quest_objectives": 70, "vendor_stock": 65, "model": 75, "drops": 55, "name": 70},
    "allthethings":      {"vendor_stock": 50, "quest_giver": 50, "drops": 45, "name": 60},
    "questiedb-fixes":   {"quest_giver": 70, "quest_objectives": 65, "spawn": 60, "name": 65},
    # Classic fallbacks: only used when nothing Forever speaks to the field
    "tc-vmangos":        {f: 25 for f in FIELDS},
    "questiedb-classic": {f: 20 for f in FIELDS},
    "cmangos-classic":   {f: 20 for f in FIELDS},
}
CLASSIC = {"tc-vmangos", "questiedb-classic", "cmangos-classic"}
RECENCY_BONUS = 10        # added to a value that comes from the newest build any candidate names
CLOSE_CALL = 0.15          # runner-up within 15% of the winner's weight: flag for review


# candidate field names (candidates.py) -> the field group whose weights they use
ALIAS = {"quest_ender": "quest_giver", "objective": "quest_objectives", "objectives_text": "quest_objectives",
         "subname": "name", "rank": "level", "min_level": "level"}


def same_text(text):
    """Texts that differ only in HTML entities, spacing, line endings or case count as the same text. WoW's $B line-break
    token (TrinityCore and EG Link keep it, Wowhead renders it) counts as spacing too."""
    import html
    import re
    text = re.sub(r"\$[Bb]", " ", html.unescape(text or "").replace("\u00a0", " "))
    return re.sub(r"\s+", " ", text).strip().lower()


def one_vote_per_source(candidates):
    """A source that offers values from several builds (EG Link has one per build) votes once, with its newest build."""
    newest = {}
    for value, source, build in candidates:
        newest[source] = max(newest.get(source, 0), int(build or 0))
    return [c for c in candidates if int(c[2] or 0) == newest[c[1]]]


def weight(source, field):
    return W.get(source, {}).get(ALIAS.get(field, field), 0)


def resolve_set(field, candidates, keep=0.5):
    """For fields that hold several values (a quest's givers, its objectives): every member is voted on alone; members
    with at least `keep` of the strongest member's weight stay. Classic sources only count when no Forever source says
    anything. Returns {members: [...], weights: {member: weight}, sources: {member: [...]}, classic_only}."""
    candidates = one_vote_per_source(candidates)
    candidates = list({(c[1], tuple(c[0]) if isinstance(c[0], list) else c[0]): c for c in candidates}.values())
    forever = [c for c in candidates if c[1] not in CLASSIC and weight(c[1], field) > 0]
    pool = forever or [c for c in candidates if weight(c[1], field) > 0]
    if not pool:
        return None
    score, who = {}, {}
    for value, source, build in pool:
        member = tuple(value) if isinstance(value, list) else value
        score[member] = score.get(member, 0) + weight(source, field)
        who.setdefault(member, []).append(source if build is None else f"{source}@{build}")
    top = max(score.values())
    members = sorted((m for m, w in score.items() if w >= top * keep), key=str)      # mixed types never break sorting
    dropped = sorted((m for m in score if m not in members), key=str)
    return {"members": members, "weights": {str(m): score[m] for m in score}, "sources": {str(m): who[m] for m in members},
            "dropped": dropped, "classic_only": not forever}


def resolve(field, candidates):
    """candidates: [(value, source, build or None)]. Returns {value, weight, confidence, sources, conflict, runner_up}.

    Values are compared as JSON-ish text so lists and dicts can agree. A Classic source only counts when no Forever
    source offers a value at all. Ties go to the value with the newest build behind it."""
    import json
    candidates = one_vote_per_source(candidates)
    candidates = [(v, s, b) for v, s, b in candidates if not (isinstance(v, str) and not same_text(v))]
    seen = set()
    candidates = [c for c in candidates if not ((c[1], json.dumps(c[0], sort_keys=True, default=str)) in seen
                                                 or seen.add((c[1], json.dumps(c[0], sort_keys=True, default=str))))]
    forever = [c for c in candidates if c[1] not in CLASSIC and weight(c[1], field) > 0]
    pool = forever or [c for c in candidates if weight(c[1], field) > 0]
    if not pool:
        return None
    newest_build = max((int(b or 0) for _, _, b in pool), default=0)
    groups = {}
    for value, source, build in pool:
        key = same_text(value) if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
        g = groups.setdefault(key, {"value": value, "weight": 0, "sources": [], "newest": 0})
        # the newest build's value gets a small edge: Forever's text and numbers change between builds
        g["weight"] += weight(source, field) + (RECENCY_BONUS if newest_build and int(build or 0) == newest_build else 0)
        g["sources"].append(source if build is None else f"{source}@{build}")
        g["newest"] = max(g["newest"], int(build or 0))
    ranked = sorted(groups.values(), key=lambda g: (g["weight"], g["newest"]), reverse=True)
    best, runner = ranked[0], (ranked[1] if len(ranked) > 1 else None)
    total = sum(g["weight"] for g in ranked)
    return {"value": best["value"], "weight": best["weight"], "confidence": round(best["weight"] / total, 2),
            "sources": best["sources"], "classic_only": not forever,
            "conflict": bool(runner and runner["weight"] >= best["weight"] * (1 - CLOSE_CALL)),
            "runner_up": runner and {"value": runner["value"], "weight": runner["weight"], "sources": runner["sources"]}}


if __name__ == "__main__":       # small self-check
    r = resolve("quest_giver", [(951, "forever-db", 70532), (951, "questietrace", 70790), (383, "tc-sniff", 70235)])
    assert r["value"] == 951 and not r["conflict"], r
    r = resolve("vendor_stock", [([6256], "tc-vmangos", None)])
    assert r["value"] == [6256] and r["classic_only"], r
    r = resolve("level", [(10, "tc-vmangos", None), (12, "forever-db", 70532)])
    assert r["value"] == 12, r                       # Classic never beats Forever
    r = resolve("name", [("A", "wago", 70790), ("B", "wowhead", None)])
    assert r["value"] == "A", r                      # live client table wins (95 + newest-build bonus vs 85)
    r = resolve("quest_text", [("beta wording", "tc-sniff", 70124), ("live wording", "eg-link", 70790)])
    assert r["value"] == "live wording" and r["conflict"], r   # 80 vs 70 + 10: the live build's text wins, flagged
    s = resolve_set("quest_giver", [(("npc", 1), "forever-db", None), (("npc", 1), "questietrace", None),
                                    (("npc", 2), "tc-vmangos", None), (("npc", 3), "allthethings", None)])
    assert s["members"] == [("npc", 1)] and ("npc", 3) in s["dropped"], s   # Classic 2 ignored, weak 3 dropped
    r = resolve("name", [("A", "eg-link", 70170), ("A", "eg-link", 70790), ("B", "forever-db", None)])
    eg = r if r["value"] == "A" else r["runner_up"]
    assert eg["weight"] == 80 and eg["sources"] == ["eg-link@70790"], r   # one vote (70 + newest-build 10), not one per build
    r = resolve("quest_text", [("A  b&nbsp;c", "wowhead", None), ("a b c", "tc-sniff", 70124)])
    assert not r["conflict"] and len(r["sources"]) == 2, r          # same text, written differently
    r = resolve("objectives_text", [("Kill 15.$B$BReturn.", "eg-link", 70790), ("Kill 15.\r\n\r\nReturn.", "wowhead", None)])
    assert not r["conflict"] and len(r["sources"]) == 2, r          # $B is a line break
    import sys
    sys.path.insert(0, __import__("os").path.dirname(__file__))
    from candidates import wowhead_objectives
    tip = ('<table><tr><td><b class="q">An Enchanting Lesson</b></td></tr></table><table><tr><td><br />Collect 3 Residue.'
           '<br /><br />Residue &amp; wax.<br /><br /><span class="q">Requirements:</span><br /> - Residue x 3</td></tr></table>')
    assert wowhead_objectives(tip) == "Collect 3 Residue.\r\n\r\nResidue & wax.", wowhead_objectives(tip)
    assert wowhead_objectives('<table><tr><td><b class="q">&lt;UNUSED&gt;</b></td></tr></table>') is None
    tip = '<td><br />Return to me, &lt;name&gt;, young &lt;fella/lady&gt;. Bring <span class="q1">Linen</span>.</td>'
    assert wowhead_objectives(tip) == "Return to me, $N, young $gfella:lady;. Bring Linen.", wowhead_objectives(tip)
    r = resolve("objectives_text", [("Return to me, $n.", "eg-link", 70790), (wowhead_objectives("<td><br />Return to me, &lt;name&gt;."), "wowhead", None)])
    assert not r["conflict"] and len(r["sources"]) == 2, r          # Wowhead's <name> is the $N token
    print("source_weights: ok")
