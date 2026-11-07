"""Static checks of a new Forever client build against the one we run (docs/client-watch.md).

Everything here reads public data only:
  WoWDBDefs   (github.com/wowdev/WoWDBDefs) - each table's layout hash and columns, per build
  wago.tools  - each table's rows, per build, as CSV (cached like tools/era/hotfix_kit.py: <cache>/<build>/<Table>.csv)
  our files   - sql/everlake/*hotfixes*.sql (the rows we send) and tools/era/kits/*.json (what the kits build)
"""
import csv
import io
import json
import os
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request

csv.field_size_limit(1 << 30)

UA = {"User-Agent": "everlake-clientwatch/1.0"}
WAGO_CSV = "https://wago.tools/db2/%s/csv?build=%s"
DBD_TARBALL = "https://codeload.github.com/wowdev/WoWDBDefs/tar.gz/refs/heads/master"

# Tables the server and kits depend on whatever our SQL holds today (the task list of docs/client-watch.md).
CORE_TABLES = ["Spell", "SpellName", "ChrClasses", "ChrRaces", "ChrSpecialization", "ChrClassesXPowerTypes",
               "PowerType", "CharBaseInfo", "SkillLine", "SkillLineAbility", "SkillRaceClassInfo",
               "Map", "MapDifficulty", "AreaTable"]
# Same lists as tools/era/hotfix_kit.py: a kit with spells sends rows of all of these.
SPELL_TABLES = ["SpellMisc", "SpellEffect", "SpellAuraOptions", "SpellAuraRestrictions", "SpellCastingRequirements",
                "SpellCategories", "SpellClassOptions", "SpellCooldowns", "SpellEquippedItems", "SpellInterrupts",
                "SpellLabel", "SpellLevels", "SpellPower", "SpellReagents", "SpellShapeshift",
                "SpellTargetRestrictions", "SpellTotems", "SpellXSpellVisual", "SpellLearnSpell",
                "SpellCastTimes", "SpellDuration", "SpellRange", "SpellRadius", "SpellCategory"]
# ID sets whose additions and removals are reported (content Blizzard added or took out).
ID_SET_TABLES = [("SpellName", "Name_lang"), ("ChrClasses", "Name_lang"), ("ChrRaces", "Name_lang"),
                 ("SkillLine", "DisplayName_lang"), ("Map", "MapName_lang"), ("TraitTree", None)]
# hotfix_blob rows name their table by hash; these are the ones our kits write (tools/era/hotfix_kit.py BLOB_TABLES).
BLOB_HASHES = {0xE111669E: "Spell"}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def fetch(url, dest, tries=3, timeout=600):
    """Downloads url to dest (atomically). Returns dest, or raises RuntimeError."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r, \
                    open(dest + ".tmp", "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            os.replace(dest + ".tmp", dest)
            return dest
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries - 1 or getattr(e, "code", 0) == 404:
                raise RuntimeError("%s: %s" % (url, e))
            time.sleep(2 + 4 * attempt)


def snake(name):
    """ChrClassesXPowerTypes -> chr_classes_x_power_types (the core's hotfix table names, as hotfix_kit.py)"""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()


def build_number(version):
    return int(str(version).split(".")[-1])


# --- WoWDBDefs -------------------------------------------------------------------------------------------------

def _in_build_line(line, version):
    """True when a BUILD line ("BUILD a, b, c-d") names version."""
    want = tuple(int(x) for x in version.split("."))
    for item in line[len("BUILD "):].split(","):
        item = item.strip()
        if "-" in item:
            lo, hi = (tuple(int(x) for x in p.split(".")) for p in item.split("-"))
            if lo[:3] == hi[:3] == want[:3] and lo[3] <= want[3] <= hi[3]:
                return True
        elif item == version:
            return True
    return False


def parse_dbd(text):
    """[{"layouts": [...], "builds": [BUILD lines], "fields": [field lines]}] of one .dbd file's definition blocks."""
    blocks, cur, in_columns = [], None, False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "COLUMNS":
            in_columns = True
            continue
        if not line:
            if cur:
                blocks.append(cur)
            cur, in_columns = None, False
            continue
        if in_columns:
            continue
        if cur is None:
            cur = {"layouts": [], "builds": [], "fields": []}
        if line.startswith("LAYOUT "):
            cur["layouts"] += [h.strip().upper() for h in line[7:].split(",")]
        elif line.startswith("BUILD "):
            cur["builds"].append(line)
        elif line.startswith("COMMENT"):
            continue
        else:
            cur["fields"].append(line.split("//")[0].strip())
    if cur:
        blocks.append(cur)
    return blocks


def block_for(blocks, version):
    for i, b in enumerate(blocks):
        if any(_in_build_line(line, version) for line in b["builds"]):
            return i, b
    return None, None


class DBD:
    """All WoWDBDefs definitions, from one tarball of the repository (cached for an hour)."""

    def __init__(self, cache, max_age=3600):
        path = os.path.join(cache, "WoWDBDefs.tar.gz")
        if not os.path.exists(path) or time.time() - os.path.getmtime(path) > max_age:
            log("  WoWDBDefs: downloading definitions")
            fetch(DBD_TARBALL, path)
        self.tables = {}
        with tarfile.open(path, "r:gz") as tar:
            for m in tar:
                if m.isfile() and "/definitions/" in m.name and m.name.endswith(".dbd"):
                    name = os.path.basename(m.name)[:-4]
                    self.tables[name] = parse_dbd(tar.extractfile(m).read().decode("utf-8", "replace"))
        self.by_snake = {snake(n): n for n in self.tables}
        self.by_lower = {n.lower(): n for n in self.tables}

    def knows(self, version):
        """True when WoWDBDefs lists the build for at least one table (its definitions were updated for it)."""
        return any(block_for(blocks, version)[1] for blocks in self.tables.values())

    def name(self, sql_table):
        return self.by_snake.get(sql_table) or self.by_lower.get(sql_table.replace("_", ""))

    def layout(self, table, version):
        """(block index, block) of the table in that build, or (None, None)."""
        return block_for(self.tables.get(table, []), version)

    def tables_in(self, version):
        return [n for n, blocks in self.tables.items() if block_for(blocks, version)[1]]


def compare_layout(dbd, table, base, new):
    """None when unchanged, else a dict describing the change."""
    bi, bb = dbd.layout(table, base)
    ni, nb = dbd.layout(table, new)
    if bb is None and nb is None:
        return None
    if bb is None:
        return {"table": table, "change": "added", "new_layouts": nb["layouts"]}
    if nb is None:
        return {"table": table, "change": "removed", "base_layouts": bb["layouts"]}
    if bi == ni:
        return None
    return {"table": table, "change": "layout", "base_layouts": bb["layouts"], "new_layouts": nb["layouts"],
            "fields_removed": [f for f in bb["fields"] if f not in nb["fields"]],
            "fields_added": [f for f in nb["fields"] if f not in bb["fields"]],
            "same_fields": bb["fields"] == nb["fields"]}


# --- our SQL and kits ------------------------------------------------------------------------------------------

def _values(text, at):
    """Parses SQL value tuples from text[at:] up to the closing ';'. Returns (rows, end)."""
    rows, row, tok, i, n = [], None, None, at, len(text)
    while i < n:
        c = text[i]
        if c == "'":
            j, buf = i + 1, []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                elif text[j] == "'" and j + 1 < n and text[j + 1] == "'":
                    buf.append("'")
                    j += 2
                elif text[j] == "'":
                    break
                else:
                    buf.append(text[j])
                    j += 1
            tok = ("" if tok is None or tok in ("X", "x") else tok) + "".join(buf)
            i = j + 1
            continue
        if c == "(" and row is None:
            row, tok = [], None
        elif c == "," and row is not None:
            row.append(tok.strip() if isinstance(tok, str) else tok)
            tok = None
        elif c == ")" and row is not None:
            row.append(tok.strip() if isinstance(tok, str) else tok)
            rows.append(row)
            row, tok = None, None
        elif c == ";" and row is None:
            return rows, i + 1
        elif row is not None and not c.isspace():
            tok = (tok or "") + c
        elif row is not None and tok is not None:
            tok += c
        i += 1
    return rows, n


INSERT = re.compile(r"INSERT\s+INTO\s+`?(\w+)`?\s*\(([^)]*)\)\s*VALUES\s*", re.I)


def sql_rows(text):
    """[(sql table, {column: value})] of every INSERT in an SQL file (comment lines skipped)."""
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("--"))
    out, at = [], 0
    while True:
        m = INSERT.search(text, at)
        if not m:
            return out
        cols = [c.strip().strip("`") for c in m.group(2).split(",")]
        rows, at = _values(text, m.end())
        out += [(m.group(1), dict(zip(cols, r))) for r in rows]


def hotfix_overrides(sql_files, dbd):
    """{DB2 table: {record id: [file names]}} of every row our hotfix SQL sends, and a list of problems."""
    over, problems = {}, []
    for path in sql_files:
        with open(path, encoding="utf-8") as f:
            rows = sql_rows(f.read())
        for table, row in rows:
            if table == "hotfix_data":
                continue
            if table == "hotfix_blob":
                h = int(row.get("TableHash") or 0) & 0xFFFFFFFF
                name = BLOB_HASHES.get(h)
                if not name:
                    problems.append("%s: hotfix_blob row with unknown table hash 0x%08X" % (os.path.basename(path), h))
                    continue
                rid = row.get("RecordId")
            else:
                name = dbd.name(table)
                if not name:
                    problems.append("%s: no DB2 table for hotfix table %s" % (os.path.basename(path), table))
                    continue
                rid = row.get("ID")
            if rid is None:
                problems.append("%s: %s row without an ID" % (os.path.basename(path), table))
                continue
            over.setdefault(name, {}).setdefault(int(rid), set()).add(os.path.basename(path))
    return over, problems


def kit_tables(kit_files):
    """(DB2 tables the kits write, [(kit file, target build)]) from tools/era/kits/*.json."""
    tables, notes = set(), []
    for path in kit_files:
        with open(path, encoding="utf-8") as f:
            kit = json.load(f)
        for spec in kit.get("rows", []):
            tables.add(spec["table"])
        if kit.get("spells"):
            tables.update(["SpellName", "Spell"] + SPELL_TABLES + ["SpellVisual"])
        if kit.get("clone_trees"):
            tables.update(["TraitTree", "TraitNode", "TraitNodeEntry", "TraitNodeXTraitNodeEntry", "TraitNodeGroup",
                           "TraitNodeGroupXTraitNode", "TraitCond", "TraitNodeGroupXTraitCond", "TraitEdge",
                           "TraitTreeXTraitCost", "TraitTreeXTraitCurrency", "SkillLineXTraitTree"])
        notes.append((os.path.basename(path), kit.get("target_build", "1.60.1.70790")))
    return tables, notes


def kit_sources(kit_files):
    """[(kit file, what, table, ids)] the kits copy FROM the target build itself (clone_trees), which a new build
    can change under them."""
    out = []
    for path in kit_files:
        with open(path, encoding="utf-8") as f:
            kit = json.load(f)
        for spec in kit.get("clone_trees", []):
            out.append((os.path.basename(path), "clone of tree %d" % spec["tree"], "TraitTree", [spec["tree"]]))
            out.append((os.path.basename(path), "nodes of tree %d" % spec["tree"], "TraitNode",
                        ("TraitTreeID", spec["tree"])))
    return out


# --- wago.tools rows -------------------------------------------------------------------------------------------

class Wago:
    """wago.tools CSVs, in the same cache layout as tools/era/hotfix_kit.py (<cache>/<build>/<Table>.csv), read
    streaming so big tables (Spell, SpellEffect) don't have to fit in memory as dicts."""

    def __init__(self, cache):
        self.cache = cache

    def path(self, table, build):
        p = os.path.join(self.cache, build, table + ".csv")
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            log("  wago: %s %s" % (build, table))
            try:
                fetch(WAGO_CSV % (table, build), p)
            except RuntimeError as e:
                log("  wago: %s" % e)
                return None
        with open(p, "rb") as f:
            error = f.read(1) == b"{"
        if error:  # {"errors": "Table not found."} or the build isn't processed yet: ask again next run
            os.remove(p)
            return None
        return p

    def scan(self, table, build, ids=None, where=None, label=None):
        """(header, {id: row} for wanted ids, {id: label value} of every row) or None when wago has no such CSV.
        ids: set of IDs whose full rows to keep. where: (column, value) keeps matching rows instead."""
        p = self.path(table, build)
        if not p:
            return None
        keep, labels = {}, {}
        with open(p, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            idx = header.index("ID") if "ID" in header else 0
            li = header.index(label) if label in header else None
            wi = header.index(where[0]) if where and where[0] in header else None
            for r in reader:
                if len(r) <= idx:
                    continue
                rid = int(r[idx])
                labels[rid] = r[li] if li is not None and li < len(r) else ""
                if (ids is not None and rid in ids) or (wi is not None and r[wi] == str(where[1])):
                    keep[rid] = dict(zip(header, r))
        return header, keep, labels


def row_diff(a, b):
    """Columns whose value differs between two row dicts (columns only one side has count too)."""
    out = []
    for c in list(a) + [c for c in b if c not in a]:
        if a.get(c) != b.get(c):
            out.append((c, a.get(c), b.get(c)))
    return out


# --- the whole static check ------------------------------------------------------------------------------------

def server_tables(cache, tc_repo, tc_commit):
    """DB2 file names the pinned core loads (DB2Stores.cpp at TC_COMMIT), or None when it can't be read."""
    url = "https://raw.githubusercontent.com/%s/%s/src/server/game/DataStores/DB2Stores.cpp" % (tc_repo, tc_commit)
    p = os.path.join(cache, "core", tc_commit, "DB2Stores.cpp")
    if not os.path.exists(p):
        try:
            fetch(url, p)
        except RuntimeError as e:
            log("  core: %s" % e)
            return None
    with open(p, encoding="utf-8", errors="replace") as f:
        return sorted(set(re.findall(r'"([A-Za-z0-9_]+)\.db2"', f.read())))


def static_check(base, new, dbd, wago, sql_files, kit_files, core_tables):
    """Runs every static check of build `new` against `base`. Returns a result dict (see report())."""
    res = {"base": base, "new": new, "items": [], "layout": [], "rows": [], "ids": [], "pending": []}

    def item(level, text):
        res["items"].append((level, text))

    over, problems = hotfix_overrides(sql_files, dbd)
    res["override_count"] = sum(len(v) for v in over.values())
    res["override_blizzard"] = 0  # rows that replace one of Blizzard's (the rest use IDs Blizzard doesn't have)
    res["override_tables"] = len(over)
    for p in problems:
        item("WARN", p)
    kt, targets = kit_tables(kit_files)
    for kit, target in targets:
        if target != new:
            item("TODO", "%s builds for %s: re-run it with target_build %s (and the client's DB2 headers of that "
                 "build) before moving the server" % (kit, target, new))
    ours = set(CORE_TABLES) | set(over) | kt | {t for t in dbd.tables if t.startswith("Trait")
                                                 and dbd.layout(t, base)[1]}
    server = set(core_tables or [])
    res["ours"], res["server"] = sorted(ours), sorted(server)

    # 1. layouts
    if not dbd.knows(new):
        res["pending"].append("WoWDBDefs has no definitions for %s yet: layouts not compared" % new)
    else:
        for t in sorted(set(dbd.tables_in(base)) | set(dbd.tables_in(new)) | ours):
            ch = compare_layout(dbd, t, base, new)
            if not ch:
                continue
            ch["tier"] = "ours" if t in ours else "server" if t in server else "other"
            res["layout"].append(ch)
        for ch in res["layout"]:
            if ch["tier"] in ("ours", "server") and ch["change"] != "added":
                item("FAIL", "%s (%s): %s" % (ch["table"], ch["tier"], describe_layout(ch)))
            elif ch["tier"] in ("ours", "server"):
                item("INFO", "%s (%s): new table in %s" % (ch["table"], ch["tier"], new))
        others = [c for c in res["layout"] if c["tier"] == "other"]
        if others:
            item("INFO", "%d other table(s) changed layout (neither the server nor our kits use them): %s"
                 % (len(others), ", ".join(c["table"] for c in others[:30]) + (" ..." if len(others) > 30 else "")))

    # 2. rows we override, and the target-build rows our kits copy
    for table in sorted(over):
        ids = set(over[table])
        a, b = wago.scan(table, base, ids), wago.scan(table, new, ids)
        if a is None or b is None:
            res["pending"].append("wago.tools has no %s CSV for %s" % (table, base if a is None else new))
            continue
        if a[0] != b[0]:
            item("FAIL", "%s: wago CSV columns differ between %s and %s" % (table, base, new))
        for rid in sorted(ids):
            files = ", ".join(sorted(over[table][rid]))
            ra, rb = a[1].get(rid), b[1].get(rid)
            res["override_blizzard"] += ra is not None
            if ra is None and rb is None:
                continue  # our own row, Blizzard has none in either build
            if ra is None:
                res["rows"].append((table, rid, "added", [], files))
                item("FAIL", "%s %d: Blizzard added a row with an ID our hotfix uses (%s): ours now replaces theirs"
                     % (table, rid, files))
            elif rb is None:
                res["rows"].append((table, rid, "removed", [], files))
                item("WARN", "%s %d: Blizzard removed the row our hotfix overrides (%s)" % (table, rid, files))
            else:
                d = row_diff(ra, rb)
                if d:
                    res["rows"].append((table, rid, "changed", d, files))
                    item("WARN", "%s %d: Blizzard changed a row our hotfix overrides (%s): %s"
                         % (table, rid, files, ", ".join("%s %s->%s" % x for x in d[:6])))
    for kit, what, table, sel in kit_sources(kit_files):
        if isinstance(sel, tuple):
            a, b = wago.scan(table, base, where=sel), wago.scan(table, new, where=sel)
        else:
            a, b = wago.scan(table, base, set(sel)), wago.scan(table, new, set(sel))
        if a is None or b is None:
            res["pending"].append("wago.tools has no %s CSV for %s (%s)" % (table, base if a is None else new, kit))
            continue
        changed = [rid for rid in set(a[1]) | set(b[1]) if a[1].get(rid) != b[1].get(rid)]
        if changed:
            item("WARN", "%s %s: %d %s row(s) differ in %s; re-run the kit" % (kit, what, len(changed), table, new))

    # 3. content added and removed
    for table, label in ID_SET_TABLES:
        a, b = wago.scan(table, base, label=label), wago.scan(table, new, label=label)
        if a is None or b is None:
            res["pending"].append("wago.tools has no %s CSV for %s" % (table, base if a is None else new))
            continue
        added = sorted(set(b[2]) - set(a[2]))
        removed = sorted(set(a[2]) - set(b[2]))
        res["ids"].append({"table": table, "added": [(i, b[2][i]) for i in added],
                           "removed": [(i, a[2][i]) for i in removed], "base_count": len(a[2]),
                           "new_count": len(b[2])})
        if table in ("ChrClasses", "ChrRaces", "Map") and (added or removed):
            item("WARN", "%s: %d added, %d removed" % (table, len(added), len(removed)))
        # our custom IDs (rows Blizzard didn't have) colliding with new Blizzard rows are reported in section 2

    if not any(level == "FAIL" for level, _ in res["items"]):
        res["status"] = "PENDING" if res["pending"] else "PASS"
    else:
        res["status"] = "FAIL"
    return res


def describe_layout(ch):
    if ch["change"] == "removed":
        return "table gone from the new build"
    if ch["change"] == "added":
        return "new table"
    s = "layout %s -> %s" % ("/".join(ch["base_layouts"]), "/".join(ch["new_layouts"]))
    if ch["same_fields"]:
        return s + " (same columns: field sizes or order may differ)"
    parts = []
    if ch["fields_removed"]:
        parts.append("removed " + ", ".join(ch["fields_removed"][:8]))
    if ch["fields_added"]:
        parts.append("added " + ", ".join(ch["fields_added"][:8]))
    return s + "; " + "; ".join(parts)
