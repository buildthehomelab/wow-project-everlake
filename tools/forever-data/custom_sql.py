"""Runs TrinityCore update files against renamed tables: split a file into statements, point every table name at its
new name, and refuse anything that could reach another table. Used by load_tc.py to apply the fork's sql/updates and
sql/custom world files to the tc_*__new tables.

The rewrite is token based, not a full SQL parser, so it is strict about what it lets through:
- only these statements run: INSERT, REPLACE, UPDATE, DELETE, CREATE [TEMPORARY] TABLE, DROP [TEMPORARY] TABLE,
  ALTER TABLE, TRUNCATE, SET, PREPARE, EXECUTE, DEALLOCATE;
- after FROM, JOIN, INTO, UPDATE, TABLE, EXISTS, TRUNCATE, DELETE and LIKE, every name of the table list (a, b, c) must
  be a table we know (or, after DELETE, an alias the statement defines); a schema-qualified name (`db`.`table`) is
  refused, except information_schema;
- a string that holds a statement (update files build ALTER statements in strings and PREPARE them) is checked and
  rewritten the same way; a string compared with TABLE_NAME is rewritten when it is a table we know.
Anything else names a table this tool won't touch, and the caller stops.
"""
import re

TOKEN = re.compile(r"""('(?:[^'\\]|\\.|'')*'|"(?:[^"\\]|\\.|"")*"|`(?:[^`]|``)+`|--(?=\s|$)[^\n]*|\#[^\n]*|/\*.*?\*/|\s+|\w+|.)""", re.S)
CONTEXT = {"FROM", "JOIN", "STRAIGHT_JOIN", "INTO", "INSERT", "REPLACE", "UPDATE", "TABLE", "EXISTS", "DELETE", "TRUNCATE", "LIKE", "REFERENCES", "USING"}
# SET may only assign user variables, NAMES, and these session settings
SESSION_SETTINGS = {"foreign_key_checks", "unique_checks", "autocommit", "names", "sql_notes"}   # not sql_mode: PIPES_AS_CONCAT
# functions a SET @var may use to build a statement for PREPARE (the update files' "add a column if missing" pattern)
SET_FUNCTIONS = {"IF", "COUNT", "IFNULL", "COALESCE", "DATABASE", "MAX", "MIN", "ROUND", "FLOOR", "CEIL", "CEILING", "GREATEST",
                 "LEAST", "ABS"}
BANNED_FUNCTIONS = {"LOAD_FILE", "SLEEP", "BENCHMARK", "GET_LOCK", "RELEASE_LOCK", "SYS_EXEC", "SYS_EVAL"}
MODIFIERS = {"IGNORE", "LOW_PRIORITY", "QUICK", "IF", "NOT", "EXISTS", "TEMPORARY", "DELAYED", "HIGH_PRIORITY", "TABLE"}
KEYWORDS = {"FROM", "INTO", "IGNORE", "IF", "NOT", "EXISTS", "TEMPORARY", "LOW_PRIORITY", "QUICK", "TABLE", "SELECT", "SET",
            "STRAIGHT_JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS", "NATURAL", "DELAYED", "HIGH_PRIORITY", "ONLY", "LATERAL",
            "WHERE", "ON", "USING", "VALUES", "VALUE", "JOIN", "AS", "ORDER", "LIMIT", "GROUP", "ADD", "MODIFY", "CHANGE", "DROP",
            "ENGINE", "DEFAULT", "LIKE", "UNION", "PARTITION", "WITH", "FOR", "ALGORITHM", "LOCK", "KEY"}
VERBS = {"INSERT", "REPLACE", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "TRUNCATE", "SET", "PREPARE", "EXECUTE", "DEALLOCATE"}
STRING_VERBS = VERBS | {"SELECT"}
SCHEMAS = {"information_schema"}
WORLD_SCHEMAS = {"world"}        # TrinityCore's default name for the world database: `world`.`creature` is the world's own
CREATE = re.compile(r"\bCREATE\s+(TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?", re.I)
# a string holds a statement when it reads like one (leading comments allowed), not when it is text that starts with a
# verb ("Drop Off Point", "Set the trap")
SQL_SHAPE = re.compile(r"\s*(?:/\*.*?\*/\s*)*(?:ALTER\s+TABLE|INSERT\s+(?:IGNORE\s+)?INTO|REPLACE\s+INTO|UPDATE\s+\S+\s+.*\bSET\b|"
                       r"DELETE\s+.*\bFROM\b|CREATE\s+(?:TEMPORARY\s+)?TABLE|DROP\s+(?:TEMPORARY\s+)?TABLE|TRUNCATE\s|"
                       r"RENAME\s+TABLE|SELECT\s+(?:\d|.*\bFROM\b)|USE\s+`?\w+`?\s*$|"
                       r"(?:CREATE|DROP)\s+(?:INDEX|DATABASE|SCHEMA|VIEW|TRIGGER|PROCEDURE|FUNCTION|EVENT|USER)\b|"
                       r"GRANT\s+.*\bON\b|LOCK\s+TABLES?\b)", re.I | re.S)
VERSIONED = re.compile(r"^/\*!\d*\s?(.*)\*/$", re.S)


def tokens(text):
    return [m.group(0) for m in TOKEN.finditer(text)]


def is_space(tok):
    return tok.isspace() or (tok.startswith(("--", "#", "/*")) and not tok.startswith("/*!"))


def statements(text):
    """The file's statements, comments dropped (/*! ... */ code kept, as MySQL runs it), split on top-level semicolons."""
    buf = []
    for tok in tokens(text):
        if tok.startswith("/*!"):
            m = VERSIONED.match(tok)
            buf.append(" " + (m.group(1) if m else "") + " ")
        elif tok.startswith(("--", "#", "/*")):
            buf.append(" ")
        elif tok == ";":
            sql = "".join(buf).strip()
            if sql:
                yield sql
            buf = []
        else:
            buf.append(tok)
    sql = "".join(buf).strip()
    if sql:
        yield sql


def created_tables(texts):
    """{table: temporary?} for every CREATE TABLE in the files."""
    out = {}
    for text in texts:
        for statement in statements(text):
            for m in CREATE.finditer(statement):
                out[m.group(2).lower()] = bool(m.group(1))
    return out


def ident(tok):
    if tok.startswith("`"):
        return tok[1:-1]
    return tok if re.fullmatch(r"[A-Za-z_]\w*", tok) else None


def insert_target(sql):
    """The one table an INSERT or REPLACE statement writes (lower case), or None for any other statement. Only that
    table changes: the tables its SELECT reads stay as they are (ON DUPLICATE KEY UPDATE also writes only the target)."""
    toks = tokens(sql)
    words = [t for t in toks if not is_space(t)]
    upper = [w.upper() for w in words]
    if not upper or upper[0] not in ("INSERT", "REPLACE"):
        return None
    k = 1
    while k < len(upper) and upper[k] in ("LOW_PRIORITY", "DELAYED", "HIGH_PRIORITY", "IGNORE", "INTO"):
        k += 1
    if k >= len(words) or (k + 1 < len(words) and words[k + 1] == "."):
        return None                      # schema-qualified: not ours to judge
    name = ident(words[k])
    return name.lower() if name else None


def on_duplicate(words, k):
    """Is the UPDATE at word index k the one in ON DUPLICATE KEY UPDATE?"""
    return words[max(0, k - 3):k] == ["ON", "DUPLICATE", "KEY"]


def _unquote(body, quote):
    return body.replace(quote * 2, quote).replace("\\" + quote, quote)


def _quote(body, quote):
    return body.replace(quote, quote * 2)


def retarget(sql, mapping, skipped=frozenset(), top=True):
    """(sql with table names replaced, True when it names a table in `skipped`, problems). Problems are names or
    statements the caller must not run: an unknown table, a schema-qualified table, a statement kind not allowed."""
    toks = tokens(sql)
    out, uses_skipped, problems = list(toks), False, set()
    sig = [i for i, t in enumerate(toks) if not is_space(t)]
    words = [toks[i].upper() for i in sig]
    if words:
        allowed = VERBS if top else STRING_VERBS
        if words[0] == "DO" and all(w.isdigit() or w == "," for w in words[1:]):
            pass                         # DO 0: a no-op some update files use as a placeholder
        elif top and words in (["START", "TRANSACTION"], ["BEGIN"], ["COMMIT"]):
            pass                         # a file wrapped in its own transaction: the loader commits once per file anyway
        elif words[0] not in allowed:
            problems.add(f"<statement {words[0]}>")
        elif words[0] == "CREATE" and words[1:2] != ["TABLE"] and words[1:3] != ["TEMPORARY", "TABLE"]:
            problems.add("<CREATE other than TABLE>")
        elif words[0] == "DROP" and words[1:2] != ["TABLE"] and words[1:3] != ["TEMPORARY", "TABLE"]:
            problems.add("<DROP other than TABLE>")
        elif words[0] == "ALTER" and "RENAME" in words:
            problems.add("<ALTER TABLE RENAME>")
        elif words[0] == "SET":
            problems |= _set_problems(toks, sig, words)
        for k, w in enumerate(words):
            if w in BANNED_FUNCTIONS and k + 1 < len(words) and words[k + 1] == "(":
                problems.add(f"<{w}>")
    # aliases: a name right after a known table (optionally after AS)
    aliases = set()
    for n, i in enumerate(sig):
        name = ident(toks[i])
        if name and name.lower() in mapping and n + 1 < len(sig):
            nxt = n + 2 if words[n + 1] == "AS" and n + 2 < len(sig) else n + 1
            alias = ident(toks[sig[nxt]])
            if alias and alias.upper() not in KEYWORDS:
                aliases.add(alias.lower())
    # names a WITH clause defines (common table expressions): they exist only inside this statement
    bare = "".join("''" if t[0] in "'\"" else t for t in toks)                    # string literals blanked out
    ctes = {x.lower() for x in re.findall(r"\bWITH\s+(?:RECURSIVE\s+)?`?(\w+)`?", bare, re.I)}
    ctes |= {x.lower() for x in re.findall(r",\s*`?(\w+)`?\s*(?:\([^()]*\))?\s*AS\s*\(", bare, re.I)} if ctes else set()
    ctes -= set(mapping)
    n, expect, after_delete = 0, False, False
    while n < len(sig):
        i, tok, word = sig[n], toks[sig[n]], words[n]
        if tok[0] in "'\"":
            out[i] = _string(tok, mapping, skipped, problems, words, n)
            n += 1
            continue
        if word in CONTEXT and ident(tok) and not tok.startswith("`") and not (word == "UPDATE" and on_duplicate(words, n)) \
                and not (word == "LIKE" and words[:1] != ["CREATE"]) \
                and not (word == "USING" and words[:1] != ["DELETE"]):     # LIKE / USING name tables only in these statements
            expect, after_delete = True, words[0] == "DELETE"   # a DELETE names its targets by alias (DELETE c FROM, DELETE FROM c USING)
            n += 1
            continue
        if expect:
            if word in MODIFIERS and not tok.startswith("`"):
                n += 1
                continue
            name = ident(tok)
            if name is None or (name.upper() in KEYWORDS and not tok.startswith("`")):
                expect = False           # the table list is over: (, WHERE, SET, VALUES ...
                continue
            if n + 1 < len(sig) and toks[sig[n + 1]] == ".":       # `db`.`table`
                table = ident(toks[sig[n + 2]]) if n + 2 < len(sig) else None
                if name.lower() in WORLD_SCHEMAS and table and table.lower() in mapping:
                    out[i], out[sig[n + 1]], out[sig[n + 2]] = f"`{mapping[table.lower()]}`", "", ""
                    for gap in range(sig[n] + 1, sig[n + 2]):
                        out[gap] = ""            # drop any space around the dot
                    n += 2                       # continue as for a plain table name (alias, comma)
                    sig_name_done = True
                elif name.lower() not in SCHEMAS:
                    problems.add(f"{name}.<table>")
                    expect = False
                    n += 3
                    continue
                else:
                    expect = False
                    n += 3
                    continue
            else:
                sig_name_done = False
            low = name.lower()
            if sig_name_done:
                pass
            elif low in skipped:
                uses_skipped = True
            elif low in mapping:
                out[i] = f"`{mapping[low]}`"
            elif low in ctes or (low == "dual" and not toks[i].startswith("`")):
                pass                     # a CTE, or DUAL: MySQL's dummy table for SELECT ... FROM DUAL WHERE ...
            elif not (after_delete and low in aliases):
                problems.add(name)
            # skip an alias after the table (`creature` c, `creature` AS c)
            k = n + 1
            if k < len(sig) and words[k] == "AS":
                k += 1
            if k < len(sig) and ident(toks[sig[k]]) and words[k] not in KEYWORDS and toks[sig[k]] not in (",", "."):
                k += 1
            n = k
            if n < len(sig) and toks[sig[n]] == ",":
                n += 1                   # next table of the list
                continue
            expect = False
            continue
        if toks[sig[n + 1]] == "." if n + 1 < len(sig) else False:  # a qualified column: table.column
            name = ident(tok)
            if name and name.lower() in mapping and name.lower() not in aliases:
                out[i] = f"`{mapping[name.lower()]}`"
            n += 3
            continue
        n += 1
    return "".join(out), uses_skipped, problems


def _set_problems(toks, sig, words):
    """SET may assign user variables (@x), NAMES and a few session settings. The value of a user variable may be a
    string literal, a number, or IF/COUNT over information_schema, so a statement it holds for PREPARE is a literal that
    retarget() checks; anything that builds text at run time (CONCAT and other functions, hex, ||) is refused. Other
    variables may be used (SET @path := @entry * 100): without a way to join strings they can only copy a checked one."""
    problems = set()
    k = 1
    while k < len(words):
        target = words[k]
        if target == "@" and k + 1 < len(words) and words[k + 1] == "@":
            problems.add("<SET @@>")             # @@global / @@session: server settings
            break
        if target == "@":
            k += 2                               # @name
        elif target in ("SESSION", "LOCAL"):
            if k + 1 >= len(words) or words[k + 1].lower() not in SESSION_SETTINGS:
                problems.add(f"<SET {words[k + 1] if k + 1 < len(words) else ''}>")
            k += 2
        elif target == "@@":
            problems.add("<SET @@>")
            break
        elif target.lower() in SESSION_SETTINGS:
            k += 1
        else:
            problems.add(f"<SET {target}>")
            break
        # the value, up to the next top-level comma
        depth = 0
        while k < len(words) and not (words[k] == "," and depth == 0):
            w, tok = words[k], toks[sig[k]]
            depth += (w == "(") - (w == ")")
            if w == "|" and k + 1 < len(words) and words[k + 1] == "|":
                problems.add("<||>")             # string concatenation under some sql_modes
            elif re.fullmatch(r"0X[0-9A-F]+|X", w) and k + 1 < len(words) and toks[sig[k + 1]][0] == "'" and w == "X":
                problems.add("<hex string>")
            elif re.fullmatch(r"0X[0-9A-F]+", w):
                problems.add("<hex literal>")
            elif ident(tok) and k + 1 < len(words) and words[k + 1] == "(" and w not in SET_FUNCTIONS and w != "SELECT":
                problems.add(f"<SET {w}()>")
            k += 1
        k += 1
    return problems


def _string(tok, mapping, skipped, problems, words, n):
    quote, body = tok[0], tok[1:-1]
    inner = _unquote(body, quote)
    if SQL_SHAPE.match(inner):                          # a statement built in a string
        sql, _, more = retarget(inner, mapping, skipped, top=False)
        problems |= more
        return quote + _quote(sql, quote) + quote
    if n >= 2 and words[n - 1] in ("=", "LIKE") and words[n - 2] == "TABLE_NAME" and inner.lower() in mapping:
        return quote + mapping[inner.lower()] + quote
    return tok


PREPARE = re.compile(r"\s*PREPARE\s+`?(\w+)`?\s+FROM\s+(.+?)\s*$", re.I | re.S)


def prepared_source(sql):
    """For PREPARE name FROM <source>: the source (a @variable or a string literal), else None."""
    m = PREPARE.match(sql)
    return m.group(2) if m else None


def check_prepared(text, targets):
    """The statement a PREPARE would run, checked at run time (its text is only known then: it may have been built in a
    variable any number of ways). Allowed only when it is one statement of an allowed kind whose every table is one of
    `targets` (the tc_*__new / __tmp names). Returns the problems; empty means it may run."""
    if text is None:
        return {"<PREPARE from an empty variable>"}
    stmts = list(statements(text))
    if len(stmts) != 1:
        return {"<PREPARE of more than one statement>"}
    _, uses_skipped, problems = retarget(stmts[0], {t: t for t in targets}, top=False)     # SELECT 1 / DO 0 placeholders allowed
    bare = "".join("''" if t[0] in "'\"" else t for t in tokens(stmts[0]))
    if re.search(r"`?\w+`?\s*\.\s*`?(%s)`?" % "|".join(map(re.escape, targets)), bare) if targets else False:
        problems.add("<schema-qualified table in a prepared statement>")
    if uses_skipped:
        problems.add("<PREPARE on a table not loaded>")
    if re.match(r"\s*(PREPARE|EXECUTE|DEALLOCATE|SET)\b", stmts[0], re.I):
        problems.add("<PREPARE of PREPARE, EXECUTE or SET>")
    return problems


def drops_missing_only(sql, problems, mapping):
    """DROP [TEMPORARY] TABLE IF EXISTS naming only tables that aren't here at all: a no-op, safe to leave out."""
    m = re.match(r"\s*DROP\s+(?:TEMPORARY\s+)?TABLE\s+IF\s+EXISTS\s+(.*)$", sql, re.I | re.S)
    if not m or not problems:
        return False
    names = [x.strip().strip("`").lower() for x in m.group(1).split(",")]
    return all(re.fullmatch(r"\w+", x) and x not in mapping for x in names) and problems == {n for n in problems if n.lower() in names}


def file_hashes(raw):
    """(line-ending independent SHA1, raw SHA1) of an update file, upper-case hex, as the fork's updater makes them."""
    import hashlib
    normalized = raw.replace(b"\r\n", b"\n")
    return hashlib.sha1(normalized).hexdigest().upper(), hashlib.sha1(raw).hexdigest().upper()


class UpdatePlan:
    """What the fork's UpdateFetcher (src/server/database/Updater/UpdateFetcher.cpp, forever branch) does with each file, in
    file-name order across the update directories, with Updates.Redundancy on (the default):
    - not in `updates`: renamed (same hash as an entry whose file is gone: the entry is renamed) or applied;
    - in `updates` with no hash: rehashed;
    - content changed: a custom world baseline (`_baseline_` under sql/custom) is only rehashed, never run again; any other
      file is applied again;
    - unchanged, but an earlier custom file was applied again: every later custom file (not a baseline) is applied again;
    - unchanged with the raw hash stored: rehashed. Otherwise skipped.
    Call next_step() file by file and tell it what ran with applied(), because the "apply later custom files" rule depends
    on what was applied before."""

    def __init__(self, held, available):
        self.held = dict(held)                 # name -> (hash, state)
        self.available = set(available)
        self.by_hash = {}
        for name, (h, _) in held.items():
            self.by_hash.setdefault((h or "").upper(), name)
        self.reapply_later = False

    @staticmethod
    def is_custom(path):
        return "/custom/" in path.replace("\\", "/")

    def step(self, name, path, raw):
        """("apply" | "rehash" | "rename" | "skip", detail) for one file."""
        normalized, raw_hash = file_hashes(raw)
        custom = self.is_custom(path)
        baseline = custom and "_baseline_" in name
        if name not in self.held:
            old = self.by_hash.get(normalized) or self.by_hash.get(raw_hash)
            if old and old not in self.available:
                return "rename", old
            return "apply", None
        stored = (self.held[name][0] or "").upper()
        if not stored:
            return "rehash", None
        same = stored in (normalized, raw_hash)
        if not same:
            return ("rehash", "baseline changed") if baseline else ("apply", "changed")
        if self.reapply_later and custom and not baseline:
            return "apply", "after an earlier custom file"
        if stored != normalized:
            return "rehash", "raw hash"
        return "skip", None

    def applied(self, name, path):
        if name in self.held and self.is_custom(path):
            self.reapply_later = True


if __name__ == "__main__":       # small self-check
    m = {"creature": "tc_creature__new", "creature_addon": "tc_creature_addon__new", "classic_spell_value": "tc_classic_spell_value__new"}
    sql, _, p = retarget("UPDATE `creature_addon` ca JOIN `creature` c ON c.`guid` = ca.`guid` SET ca.`mount` = 1 WHERE creature.id = 5", m)
    assert sql == "UPDATE `tc_creature_addon__new` ca JOIN `tc_creature__new` c ON c.`guid` = ca.`guid` SET ca.`mount` = 1 WHERE `tc_creature__new`.id = 5" and not p, (sql, p)
    sql, _, p = retarget("SET @s := IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_NAME = 'classic_spell_value') = 0, "
                         "'ALTER TABLE `classic_spell_value` ADD COLUMN `x` int COMMENT ''it''''s''', 'SELECT 1')", m)
    assert "'tc_classic_spell_value__new'" in sql and "ALTER TABLE `tc_classic_spell_value__new`" in sql and not p, (sql, p)
    assert list(statements("INSERT INTO a VALUES ('x;y'); -- c;\nDELETE FROM b;")) == ["INSERT INTO a VALUES ('x;y')", "DELETE FROM b"]
    assert list(statements("UPDATE a SET x = 1--1;")) == ["UPDATE a SET x = 1--1"]              # --1 is minus minus one
    assert list(statements("/*!40000 ALTER TABLE `a` DISABLE KEYS */;")) == ["ALTER TABLE `a` DISABLE KEYS"]
    assert retarget("DELETE FROM creature_template_locale WHERE 1", m, {"creature_template_locale"})[1]
    assert retarget("INSERT INTO creature (creature) VALUES (1)", m)[0] == "INSERT INTO `tc_creature__new` (creature) VALUES (1)"
    assert retarget("INSERT INTO creature (id) VALUES (1) ON DUPLICATE KEY UPDATE AllowableClasses = 2, slot = 3", m)[2] == set()
    assert retarget("DELETE ca FROM creature_addon ca JOIN creature c ON c.guid = ca.guid", m)[2] == set()
    assert retarget("SET comment = 'creature'", m)[0] == "SET comment = 'creature'"             # data, not a table
    for ok in ("START TRANSACTION", "BEGIN", "COMMIT"):                                       # a file's own transaction
        assert retarget(ok, m)[2] == set(), ok
    for bad in ("ROLLBACK", "START TRANSACTION READ ONLY", "COMMIT AND RELEASE"):
        assert retarget(bad, m)[2], bad
    assert retarget("COMMIT", m, top=False)[2]                                                 # never inside a PREPARE string
    assert not retarget("INSERT INTO creature (id) SELECT 1 FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM creature WHERE id = 1)", m)[2]
    assert retarget("INSERT INTO creature (id) SELECT 1 FROM `dual`", m)[2]                      # a quoted name is a real table
    assert insert_target("INSERT INTO `gossip_menu_option_locale` (a) SELECT a FROM `gossip_menu_option` ON DUPLICATE KEY UPDATE a = 1") == "gossip_menu_option_locale"
    assert insert_target("REPLACE LOW_PRIORITY INTO creature_template_locale SELECT * FROM creature_template") == "creature_template_locale"
    assert insert_target("INSERT IGNORE x.creature_template_locale SELECT 1") is None
    assert insert_target("UPDATE creature_template_locale l JOIN creature_template c SET c.name = l.Name") is None
    assert insert_target("DELETE l FROM creature_template_locale l JOIN creature_template c ON 1") is None
    for bad in ("DROP TABLE IF EXISTS `merge_id_map`", "UPDATE acore_world.creature SET map = 0", "DROP TABLE IF EXISTS creature_addon, merge_id_map",
                "UPDATE creature c, src_pins p SET p.label = 1", "DELETE src_pins FROM creature c, src_pins", "UPDATE LOW_PRIORITY src_pins SET x = 1",
                "RENAME TABLE creature TO ref_client_ids", "CREATE INDEX i ON src_pins (x)", "USE acore_world",
                "SET @s = 'DELETE FROM `merge_id_map`'", "INSERT INTO creature SELECT * FROM `acore_world`.`creature`"):
        assert retarget(bad, m)[2], bad
    for text in ("Drop Off Point", "Set the trap", "Update your gear", "Create a portal", "Delete me", "Select a target", "Use the key"):
        assert retarget(f"REPLACE INTO creature (name) VALUES ('{text}')", m)[2] == set(), text
    assert retarget("SET @s = '/* x */ DELETE FROM `merge_id_map`'", m)[2]
    sql, _, p = retarget("DELETE FROM `world`.`creature` WHERE guid = 1", m)
    assert sql == "DELETE FROM `tc_creature__new` WHERE guid = 1" and not p, (sql, p)
    sql, _, p = retarget("UPDATE world.creature c, world.creature_addon a SET a.mount = 1 WHERE a.guid = c.guid", m)
    assert sql == "UPDATE `tc_creature__new` c, `tc_creature_addon__new` a SET a.mount = 1 WHERE a.guid = c.guid" and not p, (sql, p)
    assert not retarget("UPDATE creature SET x = 1 WHERE name LIKE 'Al''Aketh %' AND y = 2", m)[2]
    assert retarget("CREATE TABLE creature_copy LIKE merge_id_map", m)[2]
    assert not retarget("INSERT INTO creature (entry) WITH RECURSIVE `seq` (`n`) AS (SELECT 0 UNION ALL SELECT `n` + 1 FROM `seq` WHERE `n` < 9) SELECT n FROM `seq` `a`", m)[2]
    assert retarget("INSERT INTO creature (entry) WITH RECURSIVE `seq` (`n`) AS (SELECT 1) SELECT n FROM merge_id_map", m)[2]
    for bad in ("UPDATE src_pins SET a = 'Fight with src_pins'", "DELETE FROM merge_id_map WHERE 'x' <> 'Speak with merge_id_map'",
                "UPDATE creature c STRAIGHT_JOIN src_pins p ON 1 SET p.a = 1", "SET @s = CONCAT('DROP TABLE ', 'src_pins')",
                "SET @s = 0x44524f50", "SET @s = REPLACE('x', 'x', 'DROP TABLE src_pins')", "SET @s = 'a' || 'b'", "SET sql_mode = 'PIPES_AS_CONCAT'",
                "SET PASSWORD = 'x'", "SET GLOBAL read_only = 1", "SET @@session.sql_log_bin = 0", "ALTER TABLE creature RENAME TO x",
                "ALTER TABLE creature ADD FOREIGN KEY (id) REFERENCES src_pins (id)", "UPDATE creature SET name = LOAD_FILE('/etc/passwd')",
                "DELETE FROM c USING creature c JOIN src_pins p"):
        assert retarget(bad, m)[2], bad
    for good in ("SET @s := IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_NAME = 'creature') = 0, 'ALTER TABLE `creature` ADD COLUMN `x` int', 'SELECT 1')",
                 "SET NAMES utf8mb4", "SET SESSION foreign_key_checks = 0", "SET @a = 1, @b = 'text'", "SET @PATH := @ENTRY * 100 + @PATHOFFSET", "PREPARE stmt FROM @s", "EXECUTE stmt",
                 "DEALLOCATE PREPARE stmt", "DELETE FROM c USING creature c JOIN creature_addon a ON a.guid = c.guid"):
        assert not retarget(good, m)[2], (good, retarget(good, m)[2])
    targets = set(m.values())
    assert not check_prepared("ALTER TABLE `tc_classic_spell_value__new` ADD COLUMN `x` int", targets)
    assert not check_prepared("SELECT 1", targets) and not check_prepared("DO 0", targets)
    for bad in ("DROP/**/TABLE src_pins", "-- x\nDROP TABLE src_pins", "/*!DROP TABLE src_pins*/", "INSERT src_pins VALUES (1)",
                "update`src_pins`set a=1", "TRUNCATE`src_pins`", "CALL p()", "DELETE FROM merge_id_map", "ALTER TABLE creature ADD x int",
                "SELECT 1; DROP TABLE src_pins", "DELETE FROM `world`.`tc_creature__new`", None):
        assert check_prepared(bad, targets), bad
    assert not retarget("SET @GUID := (SELECT MAX(guid) + 1 FROM creature)", m)[2]
    assert not retarget("DO 0", m)[2] and retarget("DO RELEASE_LOCK('x')", m)[2]
    assert retarget("DELETE FROM world.merge_id_map", m)[2] and retarget("DELETE FROM `acore_forever`.`creature`", m)[2]
    assert drops_missing_only("DROP TABLE IF EXISTS `gone`", retarget("DROP TABLE IF EXISTS `gone`", m)[2], m)
    assert not drops_missing_only("DROP TABLE IF EXISTS gone, creature", retarget("DROP TABLE IF EXISTS gone, creature", m)[2], m)
    a, b = b"x\r\ny", b"z"
    held = {"2026_01_00_world_forever_baseline_01.sql": ("OLD", "RELEASED"), "2026_01_01_world_a.sql": (file_hashes(a)[1], "RELEASED"),
            "2026_01_02_world_b.sql": (file_hashes(b)[0], "RELEASED"), "gone.sql": (file_hashes(b"moved")[0], "RELEASED")}
    files = {"2026_01_00_world_forever_baseline_01.sql": b"changed", "2026_01_01_world_a.sql": a, "2026_01_02_world_b.sql": b,
             "2026_01_03_world_new.sql": b"new", "2026_01_04_world_moved.sql": b"moved"}
    plan, seen = UpdatePlan(held, files), []
    for f in sorted(files):
        mode, _ = plan.step(f, "sql/custom/world/" + f, files[f])
        seen.append(mode)
        if mode == "apply":
            plan.applied(f, "sql/custom/world/" + f)
    assert seen == ["rehash", "rehash", "skip", "apply", "rename"], seen        # baseline changed: rehash only; raw hash: rehash
    plan, seen = UpdatePlan({**held, "2026_01_01_world_a.sql": ("CHANGED", "RELEASED")}, files), []
    for f in sorted(files):
        mode, _ = plan.step(f, "sql/custom/world/" + f, files[f])
        seen.append(mode)
        if mode == "apply":
            plan.applied(f, "sql/custom/world/" + f)
    assert seen == ["rehash", "apply", "apply", "apply", "rename"], seen         # a changed custom file re-runs every later one
    print("custom_sql: ok")
