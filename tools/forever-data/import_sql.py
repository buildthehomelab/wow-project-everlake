"""How Everlake's world import writes its update files (docs/forever-import.md, "Rules").

Every file is an ordinary TrinityCore update file for the worldserver's own updater, and is never edited once deployed.
It must be safe to run again, because the updater runs a custom file again when an earlier custom file changes:

- An import file adds a row only where none exists. Rows go through a temporary stage table: the rows the world is
  missing are marked first, then exactly those are inserted, and their keys are recorded with the file's own name in
  `everlake_import_rows`. A key is recorded only when its row was missing, never from a fixed list.
- A corrections file changes or removes a fork row only while that row (or, for a quest's givers, the whole set of
  them) is still exactly what the correction was written against. Every guard is checked before any correction acts,
  so one correction can't change what another one is checked against; a re-run finds the rows changed and does nothing.
- No file deletes a row unless it is a fork row a correction names, guarded as above; import files delete nothing.

The statements stay inside what custom_sql.py lets through (it checks our files in the dry run like the fork's).
"""
import hashlib
import re

IMPORT_ROWS = "everlake_import_rows"
STAGE = "everlake_import_stage"
FIX_OK = "everlake_fix_ok"
TEXT_TYPES = {"char", "varchar", "tinytext", "text", "mediumtext", "longtext", "binary", "varbinary", "tinyblob", "blob",
              "mediumblob", "longblob", "enum", "set", "json"}
FLOAT_TYPES = {"float", "double"}

IMPORT_ROWS_DDL = (f"CREATE TABLE IF NOT EXISTS `{IMPORT_ROWS}` (\n"
                   "  `tbl` varchar(64) NOT NULL COMMENT 'world table of the row',\n"
                   "  `k1` bigint NOT NULL COMMENT 'the row''s key, in the table''s primary key order',\n"
                   "  `k2` bigint NOT NULL DEFAULT '0',\n"
                   "  `k3` bigint NOT NULL DEFAULT '0',\n"
                   "  `k4` bigint NOT NULL DEFAULT '0',\n"
                   "  `file` varchar(200) NOT NULL COMMENT 'the update file that added the row',\n"
                   "  `note` varchar(255) NOT NULL DEFAULT '' COMMENT 'the sources that gave it',\n"
                   "  PRIMARY KEY (`tbl`, `k1`, `k2`, `k3`, `k4`),\n"
                   "  KEY `file` (`file`)\n"
                   ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci "
                   "COMMENT='Rows the Everlake world import added (docs/forever-import.md)';")

FILE_NAME = re.compile(r"^\d{4}_\d{2}_\d{2}_\d{2}_world_everlake_import_[a-z0-9_]+\.sql$")


def lit(value):
    """A SQL literal, written the way mysqldump and TrinityCore's own files write them."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if type(value).__name__ == "Decimal":
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return "0x" + value.hex() if value else "''"
    text = (str(value).replace("\\", "\\\\").replace("'", "''").replace("\r", "\\r").replace("\n", "\\n")
            .replace("\0", "\\0").replace("\x1a", "\\Z"))
    return f"'{text}'"


def comment(text):
    """One SQL comment line's text: no line breaks, nothing that could end or open a comment."""
    return re.sub(r"\s+", " ", str(text)).replace("*/", "* /").replace("/*", "/ *").strip()


def ident(name):
    if not re.fullmatch(r"\w+", name):
        raise ValueError(f"not a plain table or column name: {name!r}")
    return f"`{name}`"


def row_guard(alias, row, types):
    """SQL that holds while the row aliased `alias` still has exactly these values. Text compares by SHA-256 of its
    bytes (exact, unlike the collation's case-insensitive =), floats within a millionth (a FLOAT read back as a double
    is not the decimal it was written as), everything else with =."""
    parts = []
    for col, value in row.items():
        c = f"{alias}.{ident(col)}"
        kind = types[col]
        if value is None:
            parts.append(f"{c} IS NULL")
        elif kind in FLOAT_TYPES:
            v = float(value)
            parts.append(f"ABS({c} - ({lit(v)})) <= {lit(max(1.0, abs(v)) * 1e-6)}")
        elif kind in TEXT_TYPES:
            data = value if isinstance(value, (bytes, bytearray)) else str(value).encode("utf-8")
            parts.append(f"SHA2({c}, 256) = '{hashlib.sha256(data).hexdigest()}'")
        else:
            parts.append(f"{c} = {lit(value)}")
    return " AND ".join(parts)


def stage_block(table, columns, key, rows, file_name, missing_if, header, types):
    """Add rows where they are missing and record the ones added.

    columns: the world table's columns to fill; key: its primary key columns (recorded as k1..k4); rows: dicts with
    every column plus `note` (sources) and optional `fix` (a corrections file's fix number) and `why` (a comment).
    missing_if: extra SQL on the stage row `s` that must hold too (a quest-level guard), or None."""
    if not rows:
        return []
    if len(key) > 4:
        raise ValueError(f"{table}: keys of more than 4 columns don't fit {IMPORT_ROWS}")
    fix = any("fix" in r for r in rows)
    cols = (["fix"] if fix else []) + columns
    defs = (["`fix` int NOT NULL"] if fix else []) + [f"{ident(c)} {types[c]['ddl']}" for c in columns] + \
           ["`note` varchar(255) NOT NULL", "`missing` tinyint NOT NULL DEFAULT '0'"]
    out = [f"-- {comment(header)}",
           f"DROP TEMPORARY TABLE IF EXISTS `{STAGE}`;",
           f"CREATE TEMPORARY TABLE `{STAGE}` ({', '.join(defs)}, PRIMARY KEY ({', '.join(ident(k) for k in key)})) "
           "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;",
           f"INSERT INTO `{STAGE}` ({', '.join(ident(c) for c in cols)}, `note`) VALUES"]
    values = []
    for r in rows:
        why = f" -- {comment(r['why'])}" if r.get("why") else ""
        values.append((f"({', '.join(lit(r[c]) for c in cols)}, {lit(r['note'][:255])})", why))
    # the separator is joined in, never formatted: the data may hold braces ({skull})
    out += [row + ("," if k < len(values) - 1 else ";") + why for k, (row, why) in enumerate(values)]
    exists = " AND ".join(f"t.{ident(k)} = s.{ident(k)}" for k in key)
    cond = [f"NOT EXISTS (SELECT 1 FROM {ident(table)} t WHERE {exists})"]
    if missing_if:
        cond.append(missing_if)
    join = f" JOIN `{FIX_OK}` ok ON ok.`fix` = s.`fix`" if fix else ""
    out.append(f"UPDATE `{STAGE}` s{join} SET s.`missing` = 1 WHERE " + " AND ".join(cond) + ";")
    out.append(f"INSERT INTO {ident(table)} ({', '.join(ident(c) for c in columns)}) "
               f"SELECT {', '.join(ident(c) for c in columns)} FROM `{STAGE}` WHERE `missing` = 1;")
    ks = ", ".join(f"s.{ident(k)}" for k in key)
    kcols = ", ".join(f"`k{n + 1}`" for n in range(len(key)))
    out.append(f"INSERT INTO `{IMPORT_ROWS}` (`tbl`, {kcols}, `file`, `note`) SELECT {lit(table)}, {ks}, {lit(file_name)}, s.`note` "
               f"FROM `{STAGE}` s WHERE s.`missing` = 1 ON DUPLICATE KEY UPDATE `file` = {lit(file_name)}, `note` = s.`note`;")
    out += [f"DROP TEMPORARY TABLE `{STAGE}`;", ""]
    return out


def not_others(table, quest_col, other_key, s_quest="s.`quest`"):
    """SQL: the quest has no rows in `table` but ours, so a re-run after the fork has filled the quest in adds nothing
    next to the fork's rows. Ours = recorded in everlake_import_rows and still VerifiedBuild 0 as we wrote it: a fork
    file that takes a row over with its own sniff build (DELETE the quest's rows, INSERT them again) makes it the fork's.
    A fork row re-added with VerifiedBuild 0 under one of our keys can't be told apart; the handover files
    (docs/forever-import.md) deal with those before the fork pin moves."""
    key = " AND ".join(f"r.`k{n + 1}` = o.{ident(k)}" for n, k in enumerate(other_key))
    return (f"NOT EXISTS (SELECT 1 FROM {ident(table)} o WHERE o.{ident(quest_col)} = {s_quest} AND NOT (o.`VerifiedBuild` = 0 "
            f"AND EXISTS (SELECT 1 FROM `{IMPORT_ROWS}` r WHERE r.`tbl` = {lit(table)} AND {key})))")


def file_header(title, file_name, pins, world, licence_note):
    lines = [f"-- {comment(title)}",
             f"-- {file_name}: generated by tools/forever-data in wow-project-everlake from public WoW Forever data.",
             "-- Sources (pins): " + comment(", ".join(f"{k} {str(v)[:20]}" for k, v in sorted(pins.items()) if k != "tc-release")),
             f"-- Written against the fork world {comment(world)}.",
             f"-- {comment(licence_note)}",
             "-- Never edit this file once it is deployed (the updater would run it and every later custom file again):",
             "-- a later fix is a new file. Running it again changes nothing: see docs/forever-import.md.",
             ""]
    return lines


def check_name(name):
    if not FILE_NAME.match(name):
        raise SystemExit(f"{name}: update files are named YYYY_MM_DD_NN_world_everlake_import_<slice>.sql")
    return name


if __name__ == "__main__":       # small self-check
    assert lit("it's \\ a\r\nb") == "'it''s \\\\ a\\r\\nb'"
    assert lit(None) == "NULL" and lit(3) == "3" and lit(0.5) == "0.5"
    t = {"a": "int", "b": "varchar", "c": "float"}
    g = row_guard("t", {"a": 1, "b": "X", "c": 0.10000000149011612}, t)
    assert "t.`a` = 1" in g and "SHA2(t.`b`, 256) = '" + hashlib.sha256(b"X").hexdigest() + "'" in g and "ABS(t.`c` -" in g, g
    assert row_guard("t", {"b": None}, t) == "t.`b` IS NULL"
    check_name("2026_11_08_00_world_everlake_import_slice1.sql")
    import custom_sql
    types = {"id": {"ddl": "int unsigned NOT NULL"}, "quest": {"ddl": "int unsigned NOT NULL"}, "VerifiedBuild": {"ddl": "int NOT NULL"}}
    block = stage_block("creature_queststarter", ["id", "quest", "VerifiedBuild"], ["id", "quest"],
                        [{"id": 1, "quest": 2, "VerifiedBuild": 0, "note": "eg-link {skull} {{", "why": "x */ y {0}"}], "f.sql",
                        not_others("creature_queststarter", "quest", ["id", "quest"]), "givers", types)
    assert "'eg-link {skull} {{'" in "\n".join(block)
    text = "\n".join([IMPORT_ROWS_DDL] + block)
    mapping = {t: "p_" + t for t in ("creature_queststarter", IMPORT_ROWS, STAGE)}
    for statement in custom_sql.statements(text):
        sql, _, problems = custom_sql.retarget(statement, mapping)
        assert not problems, (statement, problems)
        assert "`creature_queststarter`" not in sql.replace("'creature_queststarter'", ""), sql
    print("import_sql: ok")
