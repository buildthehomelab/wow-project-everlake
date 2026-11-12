#!/usr/bin/env python3
"""Loads the pinned Forever sources into acore_forever, one src_<source> table each, as they come.

    load_sources.py --sources DIR              load every source whose pin changed since the last load
    load_sources.py --sources DIR --force      load them all again
    load_sources.py --sources DIR --only questiedb,forever-db

DIR holds manifest.json and the pinned files (pin_sources.py). Connection from the environment: FOREVER_DB_USER,
FOREVER_DB_PASS, FOREVER_DB_HOST (127.0.0.1), FOREVER_DB_PORT (3306), FOREVER_DB_NAME (acore_forever). The login only
needs rights on acore_forever.

Every src_ table has the same shape, so later steps read them all the same way:

    tbl   the source's own table or file name      n    row number within tbl (keeps the source's order)
    k     the source's key as text, when it has one
    id    the entity id (quest, NPC, item ...)     ref  a second id (the giver of a quest_start row, the map of a spawn)
    data  the row as JSON, unchanged

A source is loaded into src_<name>__new and then swapped in with one RENAME, so readers never see half a load.
src_pins records which pin each table came from. The TrinityCore world is not here: load_tc.py loads it into tc_ tables.
"""
import argparse
import csv
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# where the pinned files live: $FOREVER_SOURCES, else data/forever-sources in this repo (gitignored)
SOURCES = os.environ.get("FOREVER_SOURCES") or os.path.join(os.path.dirname(os.path.dirname(HERE)), "data", "forever-sources")
sys.path.insert(0, HERE)
import lua_data  # noqa: E402

BATCH_BYTES = 4 << 20
QUEST_TABLES = ("quest_start", "quest_end", "quest_objective", "quest_prereq", "quest_reward", "mechanic", "step", "note")


def connect(database=None):
    import pymysql
    return pymysql.connect(host=os.environ.get("FOREVER_DB_HOST", "127.0.0.1"), port=int(os.environ.get("FOREVER_DB_PORT", 3306)),
                           user=os.environ["FOREVER_DB_USER"], password=os.environ["FOREVER_DB_PASS"],
                           database=database or os.environ.get("FOREVER_DB_NAME", "acore_forever"), charset="utf8mb4",
                           autocommit=False, connect_timeout=30, read_timeout=600, write_timeout=600)


def as_id(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d{1,18}", value):
        return int(value)
    return None


# ---------------------------------------------------------------- readers: each yields (tbl, k, id, ref, data)

def read_forever_db(pin, folder):
    for path in sorted(p for p in pin["files"] if p.endswith(".jsonl")):
        tbl = os.path.basename(path)[:-6]
        with open(os.path.join(folder, path), encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if tbl in QUEST_TABLES or (tbl.startswith("quest_") and "quest" in row):
                    yield tbl, row.get("id"), as_id(row.get("quest")), as_id(row.get("id") or row.get("target") or row.get("pre")), row
                elif tbl == "spawn":
                    yield tbl, None, as_id(row.get("id")), as_id(row.get("map")), row
                else:
                    yield tbl, row.get("id"), as_id(row.get("id")), None, row


def read_eg_link(pin, folder):
    for path in sorted(p for p in pin["files"] if re.match(r"data/[^/]+/[^/]+/[^/]+\.json$", p)):
        _, product, build, name = path.split("/")
        with open(os.path.join(folder, path), encoding="utf-8") as handle:
            doc = json.load(handle)
        for key, block in doc.items():
            if key == "meta" or not isinstance(block, (dict, list)):
                yield name[:-5] + "." + key, f"{product}/{build}", None, None, block if isinstance(block, dict) else {"value": block}
                continue
            items = block.items() if isinstance(block, dict) else enumerate(block)
            for rid, row in items:
                yield name[:-5], f"{product}/{build}/{rid}", as_id(rid), None, dict(row, _build=build, _product=product) if isinstance(row, dict) else {"value": row, "_build": build, "_product": product}


def read_questiedb(pin, folder):
    """Every Lua data table in QuestieDB's Forever files. tbl = "<path>:<table>" (for example
    "src/corrections/Forever/traces/foreverNpcTraces.lua:ForeverNpcTraces:Load" or "data/Forever/foreverNpcDB.lua:QuestieDB.npcData");
    rows keyed by the table's own keys (entity ids for the databases). JSON and Markdown files are stored whole."""
    for path in sorted(pin["files"]):
        full = os.path.join(folder, path)
        if path.endswith(".lua"):
            for name, value in lua_data.tables(open(full, encoding="utf-8").read()).items():
                tbl = f"{path}:{name}"
                if isinstance(value, dict):
                    for key, row in value.items():
                        yield tbl, key, as_id(key), None, row if isinstance(row, (dict, list)) else {"value": row}
                elif isinstance(value, list):
                    for i, row in enumerate(value, 1):
                        yield tbl, str(i), None, None, row if isinstance(row, (dict, list)) else {"value": row}
        elif path.endswith(".json"):
            yield path, None, None, None, json.load(open(full, encoding="utf-8"))
        else:
            yield path, None, None, None, {"text": open(full, encoding="utf-8").read()}


def read_foreverdb_net(pin, folder):
    for path in sorted(p for p in pin["files"] if p.endswith(".lua")):
        name = os.path.basename(path)[:-4]
        for var, value in lua_data.assignments(open(os.path.join(folder, path), encoding="utf-8").read()).items():
            tbl = f"{name}.{var}"
            if isinstance(value, dict):
                for key, row in value.items():
                    yield tbl, key, as_id(key), None, row if isinstance(row, (dict, list)) else {"value": row}
            elif isinstance(value, list):
                for row in value:
                    first = row[0] if isinstance(row, list) and row else None
                    yield tbl, None, as_id(first), None, row if isinstance(row, (dict, list)) else {"value": row}
            else:
                yield tbl, None, None, None, {"value": value}


def read_norgannondb(pin, folder):
    """Read generated tables without running addon Lua, keeping each entity's upstream provenance."""
    def read(path):
        with open(os.path.join(folder, path), encoding="utf-8") as handle:
            return handle.read()

    source_names = {1: "questie", 2: "pfquest", 3: "questie+pfquest", 4: "collector"}
    provenance = lua_data.assignments(read("data/provenance.lua"))["packedProvenance"]
    info = lua_data.assignments(read("data/info.lua"))["info"]
    yield "info", None, None, None, info
    for kind in ("quests", "npcs", "objects", "items"):
        origins = {}
        exceptions = provenance["except"].get(kind, {})
        if isinstance(exceptions, list):
            exceptions = dict(enumerate(exceptions, 1))
        for code, encoded in exceptions.items():
            if len(encoded) % 4 or any(not 40 <= ord(char) < 104 for char in encoded):
                raise ValueError(f"NorgannonDB: invalid packed provenance for {kind}")
            for a, b, c, d in zip(encoded[::4], encoded[1::4], encoded[2::4], encoded[3::4]):
                rid = ((ord(a) - 40) * 64 + ord(b) - 40) * 4096 + (ord(c) - 40) * 64 + ord(d) - 40
                origins[rid] = source_names[int(code)]
        default = source_names[provenance["default"][kind]]
        count = 0
        for line in read(f"data/{kind}.lua").split("\n"):
            if line.startswith("R("):
                # The generated call is R(id, name, optional long string of fields).
                rid, name, *packed = lua_data.parse_value("{" + line[2:-1] + "}")
                fields = lua_data.parse_value("{" + packed[0] + "}") if packed else {}
                yield kind, rid, rid, None, dict(fields, name=name, _provenance=origins.get(rid, default))
                count += 1
        if count != info["stats"][kind]:
            raise ValueError(f"NorgannonDB: expected {info['stats'][kind]} {kind}, read {count}")
    recipe_text = re.sub(r"^do local function f\(\) ", "", read("data/recipes.lua"), flags=re.M)
    tables = lua_data.assignments(recipe_text)
    recipes = tables["recipes"]
    if len(recipes) != info["stats"]["recipes"]:
        raise ValueError("NorgannonDB: unexpected recipe count")
    for key, row in recipes.items():
        yield "recipes", key, as_id(key), as_id(row.get("item")), row
    # schema 1.5: what each class learns (from trainers the Collector saw, quests, books, levels); k = CLASS:spell
    for cls, spells in (tables.get("training") or {}).items():
        for spell, row in spells.items():
            yield "training", f"{cls}:{spell}", as_id(spell), None, dict(row, **{"class": cls})
    if "data/world.lua" in (pin.get("files") or ["data/world.lua"]):
        # one generated table per line; only the ones the gap tools read (the rest are map and UI data)
        wanted = {"instances": "instances", "lootTables": "loot_tables"}
        found = {}
        for line in read("data/world.lua").split("\n"):
            m = re.match(r"do local function f\(\) NorgannonDB\.(\w+) = (.*) end f\(\) end$", line)
            if m and m.group(1) in wanted:
                found[m.group(1)] = lua_data.parse_value(m.group(2))
        if set(found) != set(wanted) or len(found["instances"]) != info["stats"]["instances"]:
            raise ValueError("NorgannonDB: world.lua lacks instances or loot tables, or the instance count is off")
        for key, row in found["instances"].items():
            # instance key ("deadmines", "sm-cathedral"); id = its area, when known; one boss list per wing
            yield "instances", key, as_id(row.get("area")), None, row
        for key, row in found["lootTables"].items():
            yield "loot_tables", key, as_id(key), None, row


def read_everloot(pin, folder):
    for path in sorted(pin["files"]):
        with open(os.path.join(folder, path), encoding="utf-8") as handle:
            page = json.load(handle)
        if path == "settled.json":
            yield "settled", page["build"], None, None, page
            continue
        for group in ("rates", "measuredZeros"):
            for row in page[group]:
                yield group, None, as_id(row.get("itemId")), as_id(row.get("sourceNpcId") or row.get("sourceObjectId")), \
                    dict(row, _dataAsOf=page["dataAsOf"], _attribution=page["attribution"])


def read_zephras_talents(pin, folder):
    with open(os.path.join(folder, "index.json"), encoding="utf-8") as handle:
        index = json.load(handle)
    with open(os.path.join(folder, "talents.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    yield "export", index["latest"], None, None, data
    yield "index", index["latest"], None, None, index


def read_allthethings(pin, folder):
    for path in sorted(p for p in pin["files"] if p.endswith(".lua")):
        yield "file", path, None, None, {"path": path, "text": open(os.path.join(folder, path), encoding="utf-8").read()}


def read_wago(pin, folder):
    for path in sorted(p for p in pin["files"] if p.endswith(".csv")):
        with open(os.path.join(folder, path), newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                yield path[:-4], row.get("ID"), as_id(row.get("ID")), None, row


def read_wowhead(pin, folder):
    for path in pin["files"]:
        tips = json.load(open(os.path.join(folder, path), encoding="utf-8"))
        for npc, tip in tips.items():
            yield "npc_tooltip", npc, as_id(npc), None, tip


def read_item_history(pin, folder):
    for path in sorted(pin["files"]):
        full = os.path.join(folder, path)
        tbl = path[len("data/"):].rsplit(".", 1)[0]
        if path.endswith(".jsonl"):
            with open(full, encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        row = json.loads(line)
                        yield tbl, None, as_id(row.get("id") if isinstance(row, dict) else None), None, row
        else:
            yield tbl, None, None, None, json.load(open(full, encoding="utf-8"))


def read_questietrace_own(pin, folder):
    """Shared QuestieTrace recordings, mined by questietrace.py: tbl merchants / gossip / trainers / quest_dialogs / loot."""
    import questietrace
    for path in sorted(pin["files"]):
        for session in questietrace.sessions_in(os.path.join(folder, path)):
            for tbl, rows in questietrace.mine(session).items():
                for row in rows:
                    key = row.get("npc") or row.get("quest") or row.get("item")
                    yield tbl, None, as_id(key), as_id(row.get("item") if tbl in ("merchants", "loot") else None), dict(row, file=path)


def read_wowhead_tooltips(pin, folder):
    """Wowhead tooltips, newest row per (kind, id) across all parts: tbl = kind (quest, npc, object, item, spell)."""
    newest = {}
    for path in sorted(pin["files"]):
        with open(os.path.join(folder, path), encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                newest[(row["kind"], row["id"])] = row
    for (kind, rid), row in sorted(newest.items()):
        yield kind, str(rid), rid, None, row


ICYVEINS_REF = {"addon_points": "ui_map_id", "addon_levels": "ui_map_id", "addon_drops": "item_id", "addon_sells": "item_id",
                "addon_trains": "spell_id", "addon_quests": "quest_id", "objective_of_quests": "id"}


def read_icyveins(pin, folder):
    """Icy Veins' NPC data, newest fetch per NPC across all parts (missing ones left out). tbl "npc" = the creature row
    (entity, children, history); every other tbl is one of its relations, one row each, id = the NPC: addon_points
    (ref UiMap), addon_levels (ref UiMap), addon_drops / addon_sells (ref item), addon_trains (ref spell), addon_quests
    (ref quest; starts / ends), objective_of_quests (ref quest), addon_loot, addon_services, addon_gossip."""
    newest = {}
    for path in sorted(pin["files"]):
        with open(os.path.join(folder, path), encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                newest[row["id"]] = row
    for npc, row in sorted(newest.items()):
        if row["status"] != "ok":
            continue
        data = row["data"]
        yield "npc", str(npc), npc, None, dict({k: v for k, v in data.items() if k != "relations"}, _fetched=row["fetched"])
        for tbl, items in sorted((data.get("relations") or {}).items()):
            for item in items or ():
                yield tbl, None, npc, as_id(item.get(ICYVEINS_REF.get(tbl, ""))), dict(item, _fetched=row["fetched"])


def read_live_hotfixes(pin, folder):
    """Live Forever's hotfix cache, every record of every push in file order: tbl = the table hash as 0xXXXXXXXX
    (DB2 name hash), k = "<record>@<push>", id = record id, ref = push id (-1: sent with every connection).
    data = push, unique id, status (1 valid, 2 removed, 3 invalid, 4 not public), region and the record bytes as hex.
    The bytes stay raw: decoding needs the client build's table layouts."""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "live-hotfixes"))
    import dbcache
    _, records = dbcache.read(os.path.join(folder, "DBCache.bin"))
    for r in records:
        yield (f"0x{r.table:08X}", f"{r.record}@{r.push}", r.record, r.push,
               {"push": r.push, "unique": r.unique, "status": r.status, "region": r.region, "data": r.data.hex()})


READERS = {
    "forever-db": read_forever_db, "eg-link": read_eg_link, "questiedb": read_questiedb, "foreverdb-net": read_foreverdb_net,
    "allthethings": read_allthethings, "wago": read_wago, "wowhead": read_wowhead, "item-history": read_item_history,
    "questietrace-own": read_questietrace_own, "wowhead-tooltips": read_wowhead_tooltips,
    "live-hotfixes": read_live_hotfixes, "norgannondb": read_norgannondb,
    "everloot": read_everloot, "zephras-talents": read_zephras_talents, "icyveins": read_icyveins,
}


# ---------------------------------------------------------------- loading

def files_digest(pin):
    """Same commit but a different set of pinned files (a widened pin) still counts as a change."""
    import hashlib
    listing = "\n".join(f"{p} {info['sha256']}" for p, info in sorted(pin["files"].items()))
    return hashlib.sha256(listing.encode()).hexdigest()


def table_name(source):
    return "src_" + re.sub(r"[^a-z0-9]", "_", source.lower())


def load(conn, source, pin, folder):
    final = table_name(source)
    new, old = final + "__new", final + "__old"
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS `{new}`")
        cur.execute(f"""CREATE TABLE `{new}` (
            tbl VARCHAR(191) NOT NULL, n INT UNSIGNED NOT NULL, k VARCHAR(191) NULL, id BIGINT NULL, ref BIGINT NULL,
            data JSON NOT NULL, PRIMARY KEY (tbl, n), KEY by_id (tbl, id), KEY by_k (tbl, k), KEY by_ref (tbl, ref)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        counters, batch, size, total = {}, [], 0, 0
        sql = f"INSERT INTO `{new}` (tbl, n, k, id, ref, data) VALUES (%s, %s, %s, %s, %s, %s)"
        for tbl, k, rid, ref, data in READERS[source](pin, folder):
            n = counters[tbl] = counters.get(tbl, 0) + 1
            text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            key = None if k is None else str(k)[:191]
            batch.append((tbl[:191], n, key, rid, ref, text))
            size += len(text) + 64
            if size >= BATCH_BYTES:
                cur.executemany(sql, batch)
                total += len(batch)
                batch, size = [], 0
        if batch:
            cur.executemany(sql, batch)
            total += len(batch)
        conn.commit()
        cur.execute(f"DROP TABLE IF EXISTS `{old}`")
        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s", (final,))
        if cur.fetchone()[0]:
            cur.execute(f"RENAME TABLE `{final}` TO `{old}`, `{new}` TO `{final}`")
            cur.execute(f"DROP TABLE `{old}`")
        else:
            cur.execute(f"RENAME TABLE `{new}` TO `{final}`")
        cur.execute("""REPLACE INTO src_pins (source, label, folder, licence, loaded_at, row_count, tables_json, files_digest)
                       VALUES (%s, %s, %s, %s, UTC_TIMESTAMP(), %s, %s, %s)""",
                    (source, str(pin["label"]), pin["folder"], pin.get("licence"), total, json.dumps(counters), files_digest(pin)))
        conn.commit()
    return total, counters


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sources", default=SOURCES, help="folder with manifest.json and the pinned files")
    ap.add_argument("--only", help="comma-separated source names")
    ap.add_argument("--force", action="store_true", help="load even when the pin hasn't changed")
    args = ap.parse_args()
    with open(os.path.join(args.sources, "manifest.json")) as handle:
        current = json.load(handle)["current"]
    wanted = [s for s in READERS if s in current and (not args.only or s in args.only.split(","))]
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS src_pins (
            source VARCHAR(64) PRIMARY KEY, label VARCHAR(191) NOT NULL, folder VARCHAR(255) NOT NULL, licence VARCHAR(255) NULL,
            loaded_at DATETIME NOT NULL, row_count INT UNSIGNED NOT NULL, tables_json JSON NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        try:
            cur.execute("ALTER TABLE src_pins ADD COLUMN files_digest CHAR(64) NULL")
        except Exception:
            pass                                   # already there
        cur.execute("SELECT source, label, files_digest FROM src_pins")
        loaded = {s: (label, digest) for s, label, digest in cur.fetchall()}
    conn.commit()
    failed = []
    for source in wanted:
        pin = current[source]
        if not args.force and loaded.get(source) == (str(pin["label"]), files_digest(pin)):
            print(f"{source}: already loaded at {str(pin['label'])[:12]}")
            continue
        started = time.time()
        try:
            total, counters = load(conn, source, pin, os.path.join(args.sources, pin["folder"]))
        except Exception as error:      # one bad upstream file never stops the other sources; the old table stays
            conn.rollback()
            failed.append(source)
            print(f"{source}: FAILED ({type(error).__name__}: {error}); its previous load is kept", file=sys.stderr)
            continue
        print(f"{source}: {total} rows in {len(counters)} tables, {time.time() - started:.0f} s ({str(pin['label'])[:12]})")
    conn.close()
    if failed:
        sys.exit(f"failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
