#!/usr/bin/env python3
"""Hotfix SQL for the Forever client, built from another build's DB2 rows (docs/era-data.md).

    python3 tools/era/hotfix_kit.py <kit.json> --schema <hotfixes schema.tsv> --dbc <data/dbc/enUS> \
        --cache <dir> --out <file.sql>

A kit names rows to send to the client as hotfixes: rows copied from another build (retail, MoP Classic, WotLK
Titan, TBC Anniversary...), rows written by hand, and whole spells. For each row it:

  1. reads the source build's table from wago.tools (CSV, cached in --cache),
  2. lays it out as the Forever build's table: columns are matched by name with the Forever build's CSV header
     (a column the source lacks is 0 or ''), then by position with the hotfix database table, which follows the
     client's field order (checked: same column count, and a warning when a name looks unrelated),
  3. writes DELETE + INSERT for the hotfix table and a hotfix_data row (table hash from the client's DB2 header,
     UniqueId = push * 100 + n, so each push holds at most 99 rows; the kit spreads rows over pushes).

A spell brings the rows of every spell table keyed by SpellID (SpellMisc, SpellEffect, SpellPower...), its
SpellName, and any SpellCastTimes/SpellDuration/SpellRange/SpellRadius/SpellCategory row the Forever build
lacks. Its visual (SpellXSpellVisual) is kept only when the Forever build already has that SpellVisual: visual
kits hang off SpellVisualEvent, which the core can't hotfix. With "follow_triggers", spells named by
EffectTriggerSpell are added too (one level). Spells the Forever build already has are left alone.

The schema file is `mysql -N -e "SELECT table_name, column_name, ordinal_position, data_type, column_type FROM
information_schema.columns WHERE table_schema='hotfixes' ORDER BY table_name, ordinal_position"`.

Kit format (JSON):
  {"comment": "...", "target_build": "1.60.1.70790", "first_push": 9540000,
   "rows": [{"table": "ChrClasses", "build": "5.5.4.70631", "ids": [6], "set": {"6": {"DefaultSpec": 0}}},
            {"table": "ChrClassesXPowerTypes", "custom": [{"ID": 9540001, "PowerType": 5, "ClassID": 6}]}],
   "spells": [{"build": "12.1.5.70783", "ids": [47541], "follow_triggers": true,
               "skip": [123], "set": {"SpellLevels": {"47541": {"BaseLevel": 1}}}}]}
"""
import argparse
import csv
import json
import os
import re
import struct
import sys
import urllib.request

WAGO = "https://wago.tools/db2/%s/csv?build=%s"
csv.field_size_limit(1 << 30)

# spell tables keyed by SpellID (the hotfix tables the core has for them)
SPELL_TABLES = ["SpellMisc", "SpellEffect", "SpellAuraOptions", "SpellAuraRestrictions", "SpellCastingRequirements",
                "SpellCategories", "SpellClassOptions", "SpellCooldowns", "SpellEquippedItems", "SpellInterrupts",
                "SpellLabel", "SpellLevels", "SpellPower", "SpellReagents", "SpellShapeshift",
                "SpellTargetRestrictions", "SpellTotems", "SpellXSpellVisual", "SpellLearnSpell"]
# shared rows a spell points at: (table, column, referenced table)
SPELL_REFS = [("SpellMisc", "CastingTimeIndex", "SpellCastTimes"), ("SpellMisc", "DurationIndex", "SpellDuration"),
              ("SpellMisc", "PvPDurationIndex", "SpellDuration"), ("SpellMisc", "RangeIndex", "SpellRange"),
              ("SpellEffect", "EffectRadiusIndex_0", "SpellRadius"), ("SpellEffect", "EffectRadiusIndex_1", "SpellRadius"),
              ("SpellCategories", "Category", "SpellCategory"), ("SpellCategories", "ChargeCategory", "SpellCategory")]

INT_RANGES = {"tinyint": 8, "smallint": 16, "mediumint": 24, "int": 32, "bigint": 64}


def snake(name):
    """ChrClassesXPowerTypes -> chr_classes_x_power_types"""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()


def norm(name):
    return re.sub(r"(_lang$|[^a-z])", "", name.lower())


class Wago:
    def __init__(self, cache):
        self.cache = cache
        self.tables = {}

    def path(self, table, build):
        return os.path.join(self.cache, build, table + ".csv")

    def load(self, table, build):
        key = (table, build)
        if key in self.tables:
            return self.tables[key]
        p = self.path(table, build)
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            print("  wago: %s %s" % (build, table), file=sys.stderr)
            req = urllib.request.Request(WAGO % (table, build), headers={"User-Agent": "everlake-hotfix-kit/1.0"})
            with urllib.request.urlopen(req, timeout=600) as r, open(p + ".tmp", "wb") as f:
                f.write(r.read())
            os.replace(p + ".tmp", p)
        with open(p, encoding="utf-8", newline="") as f:
            text = f.read()
        if text.startswith("{"):
            self.tables[key] = None  # {"errors":"Table not found."}
            return None
        reader = csv.reader(text.splitlines(True))
        header = next(reader)
        rows = [dict(zip(header, r)) for r in reader]
        self.tables[key] = (header, rows)
        return self.tables[key]

    def by(self, table, build, column):
        t = self.load(table, build)
        out = {}
        if t:
            for r in t[1]:
                out.setdefault(int(r[column]), []).append(r)
        return out


# Tables the core has no hotfix table for: their rows go to hotfix_blob as the client's own record bytes (a sparse table's
# record: the fields in order, strings inline and null-terminated, no ID). Spell holds the tooltip text; the client keeps
# no spell as known without its row.
BLOB_TABLES = {"Spell": ["NameSubtext_lang", "Description_lang", "AuraDescription_lang"]}


def blob(table, row):
    out = b""
    for c in BLOB_TABLES[table]:
        out += (row.get(c) or "").encode("utf-8") + b"\0"
    return out


def table_hash(dbc, table):
    with open(os.path.join(dbc, table + ".db2"), "rb") as f:
        head = f.read(200)
    if head[:4] != b"WDC5":
        raise SystemExit("%s.db2: not WDC5 (%r)" % (table, head[:4]))
    return struct.unpack_from("<6I", head, 136)[4]


def load_schema(path):
    schema = {}
    with open(path) as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5 or parts[2] == "ordinal_position" or parts[0] == "TABLE_NAME":
                continue
            schema.setdefault(parts[0], []).append((parts[1], parts[3], parts[4]))
    return schema


def sql_value(value, data_type, column_type):
    if data_type in INT_RANGES:
        v = int(float(value or 0))
        bits = INT_RANGES[data_type]
        if "unsigned" in column_type:
            v &= (1 << bits) - 1
        else:
            v &= (1 << bits) - 1
            if v >= 1 << (bits - 1):
                v -= 1 << bits
        return str(v)
    if data_type in ("float", "double", "decimal"):
        return repr(float(value or 0))
    return "'" + str(value or "").replace("\\", "\\\\").replace("'", "''") + "'"


class Kit:
    def __init__(self, args, kit):
        self.wago = Wago(args.cache)
        self.schema = load_schema(args.schema)
        self.dbc = args.dbc
        self.target = kit.get("target_build", "1.60.1.70790")
        self.push = kit["first_push"]
        self.n = 0
        self.out = []          # (table, record id, row dict laid out as the target)
        self.notes = []
        self.seen = set()

    def target_header(self, table):
        t = self.wago.load(table, self.target)
        if not t:
            raise SystemExit("the target build has no %s table on wago.tools" % table)
        return t[0]

    def target_has(self, table, rid, column="ID"):
        return rid in self.wago.by(table, self.target, column)

    def add(self, table, src, overrides=None, source="?"):
        """Lays one source row out as the target build's table and queues it."""
        header = self.target_header(table)
        row = {c: src.get(c, "") for c in header}
        missing = [c for c in header if c not in src]
        for k, v in (overrides or {}).items():
            if k not in header:
                raise SystemExit("%s has no column %s" % (table, k))
            row[k] = v
        rid = int(row["ID"])
        if (table, rid) in self.seen:
            return
        self.seen.add((table, rid))
        if self.target_has(table, rid):
            self.notes.append("%s %d: the Forever build already has this ID; the hotfix replaces it" % (table, rid))
        if missing and source != "custom":
            self.notes.append("%s %d from %s: no %s in the source, sent as 0/empty" % (table, rid, source, ", ".join(missing)))
        self.out.append((table, rid, row))

    def rows(self, spec):
        table = spec["table"]
        sets = spec.get("set", {})
        if "custom" in spec:
            for r in spec["custom"]:
                self.add(table, {k: str(v) for k, v in r.items()}, source="custom")
            return
        by_id = self.wago.by(table, spec["build"], "ID")
        for rid in spec["ids"]:
            if rid not in by_id:
                raise SystemExit("%s %s has no ID %d" % (spec["build"], table, rid))
            over = dict(spec.get("set_all", {}))
            over.update(sets.get(str(rid), {}))
            self.add(table, by_id[rid][0], over or None, spec["build"])

    def spells(self, spec):
        build = spec["build"]
        skip = set(spec.get("skip", []))
        names = self.wago.by("SpellName", build, "ID")
        have = self.wago.by("SpellName", self.target, "ID")
        want = [s for s in spec["ids"] if s not in skip]
        if spec.get("follow_triggers"):
            eff = self.wago.by("SpellEffect", build, "SpellID")
            for s in list(want):
                for e in eff.get(s, []):
                    t = int(e["EffectTriggerSpell"] or 0)
                    if t and t not in want and t not in skip and t in names:
                        want.append(t)
        sets = spec.get("set", {})
        visuals = self.wago.by("SpellVisual", self.target, "ID")
        for s in want:
            if s in have:
                self.notes.append("spell %d %s: already in the Forever build, not sent" % (s, have[s][0]["Name_lang"]))
                continue
            if s not in names:
                raise SystemExit("%s has no spell %d" % (build, s))
            self.add("SpellName", names[s][0], sets.get("SpellName", {}).get(str(s)), build)
            text = self.wago.by("Spell", build, "ID").get(s)
            if text:
                self.add("Spell", text[0], None, build)
            else:
                self.notes.append("spell %d: no Spell (text) row in %s" % (s, build))
            for table in SPELL_TABLES:
                src = self.wago.load(table, build)
                if not src or not self.wago.load(table, self.target):
                    continue
                for r in self.wago.by(table, build, "SpellID").get(s, []):
                    if table == "SpellXSpellVisual" and int(r["SpellVisualID"]) not in visuals:
                        self.notes.append("spell %d: visual %s not in the Forever build, spell sent without it"
                                          % (s, r["SpellVisualID"]))
                        continue
                    self.add(table, r, sets.get(table, {}).get(str(s)), build)
                    for t2, col, ref in SPELL_REFS:
                        if t2 == table and int(r.get(col) or 0) and not self.target_has(ref, int(r[col])):
                            refs = self.wago.by(ref, build, "ID").get(int(r[col]))
                            if refs:
                                self.add(ref, refs[0], None, build)
            self.notes.append("spell %d %s: sent" % (s, names[s][0]["Name_lang"]))

    def clone_tree(self, spec):
        """Copies one of the target build's talent trees under new IDs and links it to a skill line: the tree, its
        nodes and node entries, groups, the group conditions (points spent per tier), edges, cost and currency.
        Trait definitions (the talent spells) are shared with the original."""
        tree_id, new_tree, base = spec["tree"], spec["new_tree"], spec["id_base"]
        tgt = lambda t: self.wago.load(t, self.target)[1]
        ids = {}

        def new(table, old, slot):
            key = (table, int(old))
            if key not in ids:
                ids[key] = base + slot * 1000 + sum(1 for k in ids if k[0] == table)
                if ids[key] >= base + (slot + 1) * 1000:
                    raise SystemExit("clone_tree: more than 1000 %s rows" % table)
            return ids[key]

        def put(table, row, **changes):
            row = dict(row)
            row.update({k: str(v) for k, v in changes.items()})
            self.add(table, row, source="clone of tree %d" % tree_id)

        trees = [r for r in tgt("TraitTree") if int(r["ID"]) == tree_id]
        if not trees:
            raise SystemExit("clone_tree: no tree %d" % tree_id)
        nodes = [r for r in tgt("TraitNode") if int(r["TraitTreeID"]) == tree_id]
        node_ids = {r["ID"] for r in nodes}
        groups = [r for r in tgt("TraitNodeGroup") if int(r["TraitTreeID"]) == tree_id]
        group_ids = {r["ID"] for r in groups}
        nxe = [r for r in tgt("TraitNodeXTraitNodeEntry") if r["TraitNodeID"] in node_ids]
        entry_ids = {r["TraitNodeEntryID"] for r in nxe}
        gxc = [r for r in tgt("TraitNodeGroupXTraitCond") if r["TraitNodeGroupID"] in group_ids]
        cond_ids = {r["TraitCondID"] for r in gxc}
        conds = [r for r in tgt("TraitCond") if r["ID"] in cond_ids or int(r["TraitTreeID"]) == tree_id]

        put("TraitTree", trees[0], ID=new_tree, FirstTraitNodeID=new("TraitNode", trees[0]["FirstTraitNodeID"], 0)
            if int(trees[0]["FirstTraitNodeID"]) else 0)
        for r in nodes:
            put("TraitNode", r, ID=new("TraitNode", r["ID"], 0), TraitTreeID=new_tree)
        for r in tgt("TraitNodeEntry"):
            if r["ID"] in entry_ids:
                put("TraitNodeEntry", r, ID=new("TraitNodeEntry", r["ID"], 1))
        for r in nxe:
            put("TraitNodeXTraitNodeEntry", r, ID=new("TraitNodeXTraitNodeEntry", r["ID"], 2),
                TraitNodeID=new("TraitNode", r["TraitNodeID"], 0),
                TraitNodeEntryID=new("TraitNodeEntry", r["TraitNodeEntryID"], 1))
        for r in groups:
            put("TraitNodeGroup", r, ID=new("TraitNodeGroup", r["ID"], 3), TraitTreeID=new_tree)
        gxn = [r for r in tgt("TraitNodeGroupXTraitNode") if r["TraitNodeGroupID"] in group_ids]
        for r in gxn:
            put("TraitNodeGroupXTraitNode", r, ID=new("TraitNodeGroupXTraitNode", r["ID"], 4),
                TraitNodeGroupID=new("TraitNodeGroup", r["TraitNodeGroupID"], 3),
                TraitNodeID=new("TraitNode", r["TraitNodeID"], 0))
        for r in conds:
            put("TraitCond", r, ID=new("TraitCond", r["ID"], 5),
                TraitTreeID=new_tree if int(r["TraitTreeID"]) == tree_id else r["TraitTreeID"],
                TraitNodeGroupID=new("TraitNodeGroup", r["TraitNodeGroupID"], 3) if r["TraitNodeGroupID"] in group_ids else r["TraitNodeGroupID"],
                TraitNodeID=new("TraitNode", r["TraitNodeID"], 0) if r["TraitNodeID"] in node_ids else r["TraitNodeID"],
                TraitNodeEntryID=new("TraitNodeEntry", r["TraitNodeEntryID"], 1) if r["TraitNodeEntryID"] in entry_ids else r["TraitNodeEntryID"])
        for r in gxc:
            put("TraitNodeGroupXTraitCond", r, ID=new("TraitNodeGroupXTraitCond", r["ID"], 6),
                TraitCondID=new("TraitCond", r["TraitCondID"], 5),
                TraitNodeGroupID=new("TraitNodeGroup", r["TraitNodeGroupID"], 3))
        for r in tgt("TraitEdge"):
            if r["LeftTraitNodeID"] in node_ids and r["RightTraitNodeID"] in node_ids:
                put("TraitEdge", r, ID=new("TraitEdge", r["ID"], 7),
                    LeftTraitNodeID=new("TraitNode", r["LeftTraitNodeID"], 0),
                    RightTraitNodeID=new("TraitNode", r["RightTraitNodeID"], 0))
        for r in tgt("TraitTreeXTraitCost"):
            if int(r["TraitTreeID"]) == tree_id:
                put("TraitTreeXTraitCost", r, ID=new("TraitTreeXTraitCost", r["ID"], 8), TraitTreeID=new_tree)
        for r in tgt("TraitTreeXTraitCurrency"):
            if int(r["TraitTreeID"]) == tree_id:
                put("TraitTreeXTraitCurrency", r, ID=new("TraitTreeXTraitCurrency", r["ID"], 9), TraitTreeID=new_tree)
        put("SkillLineXTraitTree", {"ID": base + 10 * 1000, "SkillLineID": spec["skill_line"], "TraitTreeID": new_tree,
                                    "Variant": 0})
        self.notes.append("tree %d cloned as %d for skill line %d: %d nodes, %d groups, %d conditions"
                          % (tree_id, new_tree, spec["skill_line"], len(nodes), len(groups), len(conds)))

    def sql(self, comment):
        lines = ["-- " + l for l in comment.strip().splitlines()]
        lines.append("-- Written by tools/era/hotfix_kit.py; re-runnable: the DELETEs undo it.")
        pushes = []
        by_table = {}
        hotfix = []
        for i, (table, rid, row) in enumerate(self.out):
            push = self.push + i // 99
            unique = push * 100 + i % 99 + 1
            if push not in pushes:
                pushes.append(push)
            by_table.setdefault(table, []).append((rid, row))
            hotfix.append((push, unique, table_hash(self.dbc, table), rid))
        lines.append("")
        lines.append("DELETE FROM `hotfix_data` WHERE `Id` BETWEEN %d AND %d;" % (pushes[0], pushes[-1]))
        for table, recs in by_table.items():
            if table in BLOB_TABLES:
                h = table_hash(self.dbc, table)
                ids = ", ".join(str(r) for r, _ in recs)
                lines.append("")
                lines.append("DELETE FROM `hotfix_blob` WHERE `TableHash` = %d AND `RecordId` IN (%s);" % (h, ids))
                lines.append("INSERT INTO `hotfix_blob` (`TableHash`, `RecordId`, `locale`, `Blob`, `VerifiedBuild`) VALUES")
                lines.append(",\n".join("(%d, %d, 'enUS', X'%s', %s)" % (h, r, blob(table, row).hex(), self.target.split(".")[-1])
                                         for r, row in recs) + ";")
                continue
            name = snake(table)
            cols = self.schema.get(name)
            if not cols:
                raise SystemExit("no hotfix table %s in the schema" % name)
            header = self.target_header(table)
            dbcols = [c for c in cols if c[0] != "VerifiedBuild"]
            if len(dbcols) != len(header):
                raise SystemExit("%s: %d hotfix columns, %d in the client's layout" % (name, len(dbcols), len(header)))
            for (dbname, _, _), h in zip(dbcols, header):
                a, b = norm(dbname), norm(h)
                if not (a.startswith(b[:4]) or b.startswith(a[:4]) or a.endswith(b[-4:])):
                    self.notes.append("%s: column %s holds %s (check)" % (name, dbname, h))
            lines.append("")
            lines.append("DELETE FROM `%s` WHERE `ID` IN (%s);" % (name, ", ".join(str(r) for r, _ in recs)))
            lines.append("INSERT INTO `%s` (%s) VALUES" % (name, ", ".join("`%s`" % c[0] for c in cols)))
            values = []
            for rid, row in recs:
                v = [sql_value(row[h], dt, ct) for (n, dt, ct), h in zip(dbcols, header)] + [self.target.split(".")[-1]]
                values.append("(" + ", ".join(v) + ")")
            lines.append(",\n".join(values) + ";")
        lines.append("")
        lines.append("INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES")
        lines.append(",\n".join("(%d, %d, %d, %d, 1, %s)" % (p, u, h, r, self.target.split(".")[-1])
                                for p, u, h, r in hotfix) + ";")
        return "\n".join(lines) + "\n", pushes


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("kit")
    ap.add_argument("--schema", required=True)
    ap.add_argument("--dbc", required=True, help="the client's DB2 files (data/dbc/enUS), for the table hashes")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(args.kit) as f:
        kit = json.load(f)
    k = Kit(args, kit)
    for spec in kit.get("rows", []):
        k.rows(spec)
    for spec in kit.get("spells", []):
        k.spells(spec)
    for spec in kit.get("clone_trees", []):
        k.clone_tree(spec)
    text, pushes = k.sql(kit.get("comment", ""))
    with open(args.out, "w") as f:
        f.write(text)
    counts = {}
    for table, _, _ in k.out:
        counts[table] = counts.get(table, 0) + 1
    print("%d rows in pushes %d-%d: %s" % (len(k.out), pushes[0], pushes[-1],
                                           ", ".join("%s %d" % c for c in counts.items())))
    for n in k.notes:
        print("  " + n)


if __name__ == "__main__":
    main()
