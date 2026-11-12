#!/usr/bin/env python3
"""Keeps our own copy of the public WoW Forever data that Everlake's Forever data tools read.

    pin_sources.py                 pin the newest of everything
    pin_sources.py --verify        check every pinned file against its recorded sha256
    pin_sources.py --wowhead-only [--wowhead-max N]   only the Wowhead tooltips
    pin_sources.py --icyveins-only [--icyveins-max N] only Icy Veins' NPC data
    pin_sources.py --only NAME,NAME                  only these GitHub sources (eg-link, forever-db, tc-forever ...)

The folder is $FOREVER_SOURCES, else data/forever-sources in this repo (gitignored). Each source lands in
<folder>/<name>/<commit or build or date>/. manifest.json records where every file came from, its
sha256, and which pin is current, so an import can name exactly what it was built from. A source that hasn't moved is
skipped. Old pins stay until someone deletes them.

CREDITS.md is written from SOURCES and has to travel with anything built from EG Link's data (CC BY 4.0).
"""
import concurrent.futures as cf
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("FOREVER_SOURCES") or os.path.join(os.path.dirname(os.path.dirname(HERE)), "data", "forever-sources")
MANIFEST = os.path.join(ROOT, "manifest.json")
USER_AGENT = "everlake-forever-data"
FOREVER_BUILD = "1.60.1.70790"        # fallback only: pin_wago follows the newest live build wago.tools lists


def newest_forever_build():
    """The newest live Forever client build on wago.tools (product wowf), or FOREVER_BUILD when the list can't be read."""
    try:
        builds = json.loads(fetch("https://wago.tools/api/builds")).get("wowf") or []
        versions = [b["version"] for b in builds if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", b.get("version", ""))]
        return max(versions, key=lambda v: tuple(map(int, v.split(".")))) if versions else FOREVER_BUILD
    except Exception as error:                      # noqa: BLE001 - a list we can't read keeps the known build
        print(f"wago: build list unreadable ({error}); using {FOREVER_BUILD}")
        return FOREVER_BUILD

EG_TABLES = ("npcs", "creatures", "creature_details.enUS", "object_details.enUS", "quests.enUS", "vendors", "trainers",
             "flights", "loot", "objectives", "texts.enUS", "quest_prerequisites", "turn_ins", "item_uses", "quest_scan",
             "item_hotfixes.enUS", "broadcast_text.enUS", "game_rules", "durability")
FOREVER_DB_TABLES = ("npc", "object", "quest", "quest_start", "quest_end", "quest_objective", "quest_prereq", "quest_reward",
                     "spawn", "item", "item_source", "ui_map", "mechanic", "step")
WAGO_TABLES = ("AreaTable", "AreaPOI", "GameObjects", "Light", "LightParams", "SoundAmbience", "TaxiNodes", "TaxiPath",
               "TaxiPathNode", "ZoneIntroMusicTable", "ZoneMusic", "Faction", "FactionTemplate", "SoundKit", "SoundKitEntry",
               "UiMap", "UiMapAssignment", "Map", "CreatureDisplayInfo", "GameObjectDisplayInfo")

SOURCES = {
    "eg-link": {
        "repo": "JIVESCORP/eg-link-output-wowf",
        "licence": "CC BY 4.0",
        "credit": "Data from [Efficient Games](https://efficient.games), licensed under "
                  "[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Changed: compared with TrinityCore rows.",
        "keep": lambda p: p in ("README.md", "DATASETS.md", "LICENSE", "data/index.json")
                          or (p.startswith("data/") and os.path.basename(p)[:-5] in EG_TABLES),
    },
    "forever-db": {
        "repo": "fitzforge/polestar",
        "licence": "GPL-3.0 (tables), CC BY 4.0 (mechanic, step)",
        "credit": "forever-db from [Polestar](https://github.com/fitzforge/polestar), GPL-3.0 for its tables and CC BY 4.0 for mechanic and step. Its NOTICE.md is pinned with it.",
        "keep": lambda p: p in ("forever-db/README.md", "forever-db/NOTICE.md", "forever-db/LICENSE", "forever-db/LICENSE-CC-BY-4.0.txt", "forever-db/index.json")
                          or (p.startswith("forever-db/data/") and os.path.basename(p)[:-6] in FOREVER_DB_TABLES),
    },
    "allthethings": {
        "repo": "ATTWoWAddon/AllTheThings",
        "licence": "MIT",
        "credit": "Zone and vendor notes from [AllTheThings](https://github.com/ATTWoWAddon/AllTheThings), MIT.",
        # every Forever zone and dungeon file
        "keep": lambda p: p == "LICENSE" or (p.startswith(".contrib/.db/forever/") and p.endswith(".lua")
                                             and "/.config/" not in p),
    },
    "questiedb": {
        "repo": "Questie/QuestieDB",
        "licence": "GPL-3.0",
        "credit": "Forever quest, NPC, object, item, drop and zone data and player-recorded QuestieTrace corrections from "
                  "[QuestieDB](https://github.com/Questie/QuestieDB), GPL-3.0. Changed: compared with TrinityCore rows.",
        # everything QuestieDB publishes for Forever: base DB, corrections (hand fixes, generated delta, legacy, player
        # traces), drop tables, quest XP, zones, faction templates, the names in 9 languages, and its notes
        "keep": lambda p: p in ("LICENSE.md", "gpl-3.0.md", "PROVENANCE.md")
                          or (p.startswith(("data/Forever/", "src/corrections/Forever/", "support/Forever/", "l10n/Forever/"))
                              and p.endswith((".lua", ".json", ".md")))
                          or (p.startswith("docs/forever") and p.endswith(".md")),
    },
    "tc-forever": {
        "repo": "advocaite/TrinityCore",
        "branch": "forever",
        "licence": "GPL-2.0",
        "credit": "World data from the [TrinityCore `forever` branch](https://github.com/advocaite/TrinityCore/tree/forever) "
                  "(VMaNGOS vanilla world and sniffs of Forever's beta), GPL-2.0.",
        # the update files that land on top of the full-database release: sql/updates (TrinityCore's own) and sql/custom
        # (the fork's); locale catalogs (tens of MB each) left out
        "keep": lambda p: p == "COPYING" or (re.match(r"sql/(custom|updates)/(world|hotfixes)/(?:[^/]+/)*[^/]+\.sql$", p) and "locale" not in p),
    },
    "norgannondb": {
        "repo": "zmarotrix/NorgannonDB",
        "branch": "v1.4.7",
        "licence": "GPL-3.0; see NOTICE.md for bundled sources",
        "credit": "Quest, NPC, item and recipe data from [NorgannonDB](https://github.com/zmarotrix/NorgannonDB), GPL-3.0. "
                  "Its packed provenance and NOTICE accompany the pin.",
        "files": ("LICENSE", "NOTICE.md", "SPEC.md", "data/info.lua", "data/provenance.lua", "data/quests.lua",
                  "data/npcs.lua", "data/objects.lua", "data/items.lua", "data/recipes.lua"),
    },
    "sakhwoow-forever": {
        "repo": "Sakhwoow/WoWForever",
        "branch": "forever",
        "opt_in": True,
        "licence": "GPL-2.0 (repository); upstream comparison only",
        "credit": "World and hotfix SQL from [Sakhwoow/WoWForever](https://github.com/Sakhwoow/WoWForever/tree/forever), "
                  "kept for upstream comparison.",
        "keep": lambda p: p == "COPYING" or bool(re.fullmatch(r"sql/custom/(world|hotfixes)/[^/]+\.sql", p)),
    },
    "item-history": {
        "repo": "ericbtaylorjr/forever-db",
        "licence": "none stated (reference only until the author agrees)",
        "credit": "Item and spell history per build and hotfix from [forever-db](https://github.com/ericbtaylorjr/forever-db) "
                  "by ericbtaylorjr, used as a reference.",
        "keep": lambda p: p.startswith("data/") and (p.endswith(".jsonl") or p.endswith(".json")),
    },
    "databaseforever": {
        "repo": "EmuForever/DatabaseForever",
        "licence": "none stated (reference only until the author agrees)",
        "credit": "World database of the [EmuForever](https://github.com/EmuForever/EmuForever) server emulator from "
                  "[DatabaseForever](https://github.com/EmuForever/DatabaseForever), used as a reference.",
        # its world tables, one mysqldump each (TrinityCore layout); locale, website (armory_), views and backups left out
        "keep": lambda p: bool(re.match(r"World/[a-z0-9_]+\.sql$", p))
                          and not re.search(r"(_locale|^armory_|^vw_|_bak|_backup_|^updates_include)", os.path.basename(p)[:-4]),
    },
}
# The fork world everything is compared against. FOREVER_TC_REPO / FOREVER_TC_REF switch it, e.g. to Everlake's own core
# (buildthehomelab/wow-trinitycore-everlake, branch everlake) or to the exact commit Everlake's Dockerfile pins.
if os.environ.get("FOREVER_TC_REPO") or os.environ.get("FOREVER_TC_REF"):
    SOURCES["tc-forever"].update(repo=os.environ.get("FOREVER_TC_REPO") or SOURCES["tc-forever"]["repo"],
                                 branch=os.environ.get("FOREVER_TC_REF") or SOURCES["tc-forever"]["branch"])
TC_RELEASE = {"repo": "advocaite/TrinityCore", "tag_prefix": "forever-tdb-"}
FOREVERDB_NET = "https://foreverdb.net/"
EVERLOOT = "https://everloot.app"
ZEPHRAS_TALENTS = "https://zephras.com/data/forever/enUS/talents"
# Blizzard's live Forever hotfix cache, mirrored publicly and refreshed daily (wowsims/forever, MIT, builds from it)
LIVE_HOTFIXES_URL = "https://storage.googleapis.com/raidbots-static/wow/forever/enUS/DBCache.bin"
CREDITS_EXTRA = (
    "Forever's client tables through [wago.tools](https://wago.tools); item, quest, NPC, object and spell tooltips from "
    "[Wowhead](https://www.wowhead.com/forever)'s public tooltip service, as a reference.",
    "Live Forever hotfixes from Blizzard's hotfix cache, through the public mirror that "
    "[wowsims/forever](https://github.com/wowsims/forever) builds from.",
    "Vendor, trainer and quest data from [ForeverDB.net](https://foreverdb.net): Data from ForeverDB.net, GPL-3.0.",
    "Data from [Everloot](https://everloot.app), CC BY-SA 4.0. Kept as source evidence, without applying it to the world.",
    "Talent data: [Zephras](https://zephras.com), CC BY 4.0 for Zephras's contributions; stored without changes.",
    "NPC map points, drops, vendor stock and trainer lists that players' addons recorded, from "
    "[Icy Veins](https://db.icy-veins.com/wow-forever/)' WoW Forever database, as a reference.",
    "Game content such as names and text belongs to Blizzard Entertainment.",
)


def fetch(url, retries=4):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code < 500 and error.code != 429:
                raise
            time.sleep(2 + attempt * 2)
        except OSError:
            if attempt == retries - 1:
                raise
            time.sleep(2 + attempt * 2)
    raise OSError(f"gave up on {url}")


def gh_json(path):
    return json.loads(subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write(folder, relative, data):
    path = os.path.join(folder, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".part"
    with open(temporary, "wb") as handle:
        handle.write(data)
    os.replace(temporary, path)
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def pin_files(name, label, folder, jobs):
    """jobs: (relative path, url). Fails whole if any file fails, so a pin is never partial."""
    def one(job):
        return job[0], write(folder, job[0], fetch(job[1]))
    with cf.ThreadPoolExecutor(8) as pool:
        files = dict(pool.map(one, jobs))
    return {"label": label, "folder": os.path.relpath(folder, ROOT), "pinned": now(), "files": files}


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pin_repo(name, source, manifest):
    repo = source["repo"]
    head = source.get("branch") or gh_json(f"repos/{repo}")["default_branch"]
    commit = gh_json(f"repos/{repo}/commits/{head}")["sha"]
    current = manifest["current"].get(name)
    if current and current["label"] == commit and "files" in source and set(source["files"]) == set(current["files"]):
        print(f"{name}: unchanged at {commit[:10]}")
        return False
    if "files" in source:
        wanted = list(source["files"])
    else:
        tree = gh_json(f"repos/{repo}/git/trees/{commit}?recursive=1")
        if tree.get("truncated"):
            raise SystemExit(f"{name}: tree listing was truncated")
        wanted = [e["path"] for e in tree["tree"] if e["type"] == "blob" and source["keep"](e["path"])]
    if current and current["label"] == commit and set(wanted) == set(current["files"]):
        print(f"{name}: unchanged at {commit[:10]}")      # same commit and the same files kept
        return False
    jobs = [(p, f"https://raw.githubusercontent.com/{repo}/{commit}/" + urllib.request.quote(p)) for p in wanted]
    pin = pin_files(name, commit, os.path.join(ROOT, name, commit[:10]), jobs)
    pin.update(repo=repo, licence=source["licence"])
    record(manifest, name, pin)
    print(f"{name}: pinned {commit[:10]}, {len(jobs)} files, {sum(f['bytes'] for f in pin['files'].values()) >> 20} MB")
    return True


def pin_wago(manifest):
    """One pin per build. A table added to WAGO_TABLES later is fetched into the same pin, the others left as they are."""
    build = newest_forever_build()
    current = manifest["current"].get("wago")
    folder = os.path.join(ROOT, "wago", build)
    if current and current["label"] == build:
        missing = [t for t in WAGO_TABLES if t + ".csv" not in current["files"]]
        if not missing:
            print(f"wago: unchanged at {build}")
            return
        jobs = [(t + ".csv", f"https://wago.tools/db2/{t}/csv?build={build}") for t in missing]
        added = pin_files("wago", build, folder, jobs)
        current["files"].update(added["files"])
        manifest["history"].append({"source": "wago", "label": build, "pinned": added["pinned"], "added": missing})
        print(f"wago: added {', '.join(missing)} to {build}")
        return
    jobs = [(t + ".csv", f"https://wago.tools/db2/{t}/csv?build={build}") for t in WAGO_TABLES]
    pin = pin_files("wago", build, folder, jobs)
    record(manifest, "wago", pin)
    print(f"wago: pinned {build}, {len(jobs)} tables")


def pin_wowhead(manifest):
    """One file a day at most. New ids go in wowhead_npc_ids.txt by hand: the zone page refuses scripts."""
    today = now()[:10]
    current = manifest["current"].get("wowhead")
    if current and current["label"] == today:
        print(f"wowhead: already pinned {today}")
        return
    with open(os.path.join(HERE, "wowhead_npc_ids.txt")) as handle:
        ids = handle.read().split()
    def one(npc):
        return npc, json.loads(fetch(f"https://nether.wowhead.com/forever/tooltip/npc/{npc}"))
    with cf.ThreadPoolExecutor(4) as pool:
        tips = dict(pool.map(one, ids))
    folder = os.path.join(ROOT, "wowhead", today)
    info = write(folder, "npc_tooltips.json", json.dumps(tips, indent=0, sort_keys=True).encode())
    record(manifest, "wowhead", {"label": today, "folder": os.path.relpath(folder, ROOT), "pinned": now(),
                                 "files": {"npc_tooltips.json": info}})
    print(f"wowhead: pinned {len(ids)} NPC tooltips")


def pin_tc_release(manifest):
    """The newest full-database release of the TrinityCore forever branch (a .7z of world + hotfixes SQL)."""
    releases = gh_json(f"repos/{TC_RELEASE['repo']}/releases")
    release = next(r for r in releases if r["tag_name"].startswith(TC_RELEASE["tag_prefix"]))
    current = manifest["current"].get("tc-release")
    if current and current["label"] == release["tag_name"]:
        print(f"tc-release: unchanged at {release['tag_name']}")
        return
    folder = os.path.join(ROOT, "tc-release", release["tag_name"])
    os.makedirs(folder, exist_ok=True)
    files = {}
    for asset in release["assets"]:
        subprocess.run(["gh", "release", "download", release["tag_name"], "-R", TC_RELEASE["repo"], "-p", asset["name"],
                        "-D", folder, "--clobber"], check=True)
        path = os.path.join(folder, asset["name"])
        files[asset["name"]] = {"sha256": sha256(path), "bytes": os.path.getsize(path)}
    record(manifest, "tc-release", {"label": release["tag_name"], "folder": os.path.relpath(folder, ROOT), "pinned": now(),
                                    "files": files, "repo": TC_RELEASE["repo"], "licence": "GPL-2.0"})
    print(f"tc-release: pinned {release['tag_name']}, {len(files)} files")


def pin_live_hotfixes(manifest):
    """Live Forever's hotfix cache (DBCache.bin). It changes in place every day, so a pin is one content: label
    <client build>-<first 12 of its sha256>. A file that doesn't read as a whole hotfix cache is refused, not pinned."""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "live-hotfixes"))
    import dbcache
    data = fetch(LIVE_HOTFIXES_URL)
    build, records = dbcache.parse(data)
    label = f"{build}-{hashlib.sha256(data).hexdigest()[:12]}"
    current = manifest["current"].get("live-hotfixes")
    if current and current["label"] == label:
        print(f"live-hotfixes: unchanged at {label}")
        return
    folder = os.path.join(ROOT, "live-hotfixes", label)
    record(manifest, "live-hotfixes", {"label": label, "folder": os.path.relpath(folder, ROOT), "pinned": now(),
                                       "files": {"DBCache.bin": write(folder, "DBCache.bin", data)}, "build": build,
                                       "records": len(records), "url": LIVE_HOTFIXES_URL,
                                       "licence": "Blizzard data; public mirror (wowsims/forever, MIT, builds from it)"})
    print(f"live-hotfixes: pinned {label}, {len(records)} records")


def pin_snapshot(name, version, payloads, manifest, licence):
    """Keep each validated HTTP response with its URL and hash under a content-derived label."""
    digest = hashlib.sha256()
    for path, (url, data) in sorted(payloads.items()):
        digest.update(f"{path} {url} {hashlib.sha256(data).hexdigest()}\n".encode())
    label = f"{version}-{digest.hexdigest()[:16]}"
    if manifest["current"].get(name, {}).get("label") == label:
        print(f"{name}: unchanged at {label}")
        return
    folder = os.path.join(ROOT, name, label)
    files = {path: dict(write(folder, path, data), url=url) for path, (url, data) in payloads.items()}
    record(manifest, name, {"label": label, "folder": os.path.relpath(folder, ROOT),
                            "pinned": now(), "files": files, "licence": licence})
    print(f"{name}: pinned {label}, {len(files)} files")


def pin_everloot(manifest):
    """Store the complete aggregate rollup and the separate build-specific consensus index."""
    build = newest_forever_build()
    settled_url = f"{EVERLOOT}/api/coverage/settled?build={build}"
    settled = fetch(settled_url)
    coverage = json.loads(settled)
    if coverage.get("schema") != "everloot.settled/1" or coverage.get("build") != build or not coverage.get("dataAsOf"):
        raise ValueError("Everloot: invalid settled coverage response")
    payloads = {"settled.json": (settled_url, settled)}
    offset = 0
    snapshot = None
    while True:
        url = f"{EVERLOOT}/api/rollups/drops?limit=500&offset={offset}"
        data = fetch(url)
        page = json.loads(data)
        stamp, total = page.get("dataAsOf"), page.get("total")
        rows = page.get("rates"), page.get("measuredZeros")
        if page.get("unreachable") is not False or not stamp or type(total) is not int or total < 0 \
                or page.get("offset") != offset or not all(isinstance(group, list) for group in rows) \
                or page.get("attribution", {}).get("licence") != "CC BY-SA 4.0":
            raise ValueError("Everloot: invalid or unavailable drop rollup")
        if snapshot is not None and snapshot != (stamp, total):
            raise ValueError("Everloot: drop rollup changed during paging, retry the pin")
        snapshot = stamp, total
        payloads[f"drops-{offset:09d}.json"] = (url, data)
        count = sum(len(group) for group in rows)
        offset += count
        if offset == total and not page.get("next"):
            break
        if not count or offset >= total or not page.get("next"):
            raise ValueError("Everloot: incomplete drop rollup")
    pin_snapshot("everloot", build, payloads, manifest, "CC BY-SA 4.0 (Everloot player data)")


def pin_zephras_talents(manifest):
    index_url = f"{ZEPHRAS_TALENTS}/index.json"
    index_data = fetch(index_url)
    index = json.loads(index_data)
    build = index["latest"]
    if index.get("format") != "zephras-talents-index/1" or not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", build):
        raise ValueError("Zephras: invalid talents index")
    entry = next(row for row in index["files"] if row["build"] == build)
    url = f"{ZEPHRAS_TALENTS}/{build}.json"
    if entry["url"] != url or index.get("license", {}).get("name") != "CC BY 4.0":
        raise ValueError("Zephras: unexpected export URL or licence")
    data = fetch(url)
    if len(data) != entry["bytes"] or json.loads(data).get("format") != "zephras-talents/1":
        raise ValueError("Zephras: invalid talent export")
    pin_snapshot("zephras-talents", build, {"index.json": (index_url, index_data), "talents.json": (url, data)},
                 manifest, "CC BY 4.0 (Zephras contributions); Blizzard content excluded")


def pin_foreverdb_net(manifest):
    """ForeverDB.net's addon data files, by the version in its manifest; each file is checked against its sha256."""
    listing = json.loads(fetch(FOREVERDB_NET + "downloads/addon-manifest.json"))
    version = listing["data"]["version"]
    current = manifest["current"].get("foreverdb-net")
    if current and current["label"] == version:
        print(f"foreverdb-net: unchanged at {version}")
        return
    folder = os.path.join(ROOT, "foreverdb-net", version)
    jobs = [(f["path"], FOREVERDB_NET + f["url"]) for f in listing["data"]["files"]]
    jobs.append(("ForeverDB.zip", FOREVERDB_NET + listing["addon"]["url"]))   # holds NOTICE.txt, the licence terms
    pin = pin_files("foreverdb-net", version, folder, jobs)
    expected = {f["path"]: f["sha256"] for f in listing["data"]["files"]}
    expected["ForeverDB.zip"] = listing["addon"]["sha256"]
    bad = [p for p, info in pin["files"].items() if info["sha256"] != expected[p]]
    if bad:
        raise SystemExit("foreverdb-net: sha256 mismatch for " + ", ".join(bad))
    pin.update(licence="GPL-3.0 with attribution (section 7(b)): credit \"Data from ForeverDB.net\"")
    record(manifest, "foreverdb-net", pin)
    print(f"foreverdb-net: pinned {version}, {len(jobs)} files")


def pin_questietrace_own(manifest):
    """QuestieTrace recordings that players shared: the SavedVariables or /qlt export files listed (one path or glob
    per line) in questietrace_paths.txt next to this script. Skipped when that file is missing or matches nothing."""
    import glob
    listing = os.path.join(HERE, "questietrace_paths.txt")      # local, gitignored; see questietrace_paths.example.txt
    if not os.path.exists(listing):
        print("questietrace-own: no questietrace_paths.txt, skipped")
        return
    paths = sorted({p for line in open(listing) if line.strip() and not line.startswith("#")
                    for p in glob.glob(os.path.expanduser(line.strip()))})
    if not paths:
        print("questietrace-own: questietrace_paths.txt matches no file, skipped")
        return
    blobs = {f"{i:02d}-{os.path.basename(os.path.dirname(os.path.dirname(p)))}-{os.path.basename(p)}": open(p, "rb").read()
             for i, p in enumerate(paths)}
    digest = hashlib.sha256(b"".join(hashlib.sha256(b).digest() for b in blobs.values())).hexdigest()[:16]
    current = manifest["current"].get("questietrace-own")
    if current and current["label"] == digest:
        print(f"questietrace-own: unchanged at {digest}")
        return
    folder = os.path.join(ROOT, "questietrace-own", now()[:10] + "-" + digest[:8])
    files = {name: write(folder, name, data) for name, data in blobs.items()}
    record(manifest, "questietrace-own", {"label": digest, "folder": os.path.relpath(folder, ROOT), "pinned": now(), "files": files,
                                         "licence": "shared QuestieTrace recordings (QuestieTrace addon, GPL-3.0)"})
    print(f"questietrace-own: pinned {len(files)} files")


WOWHEAD_KINDS = ("quest", "npc", "object", "item", "spell")      # fetch order: what the gap report needs most first
WOWHEAD_RATE = 3.0                                                # requests per second, one at a time
WOWHEAD_MAX = int(os.environ.get("WOWHEAD_MAX", "15000"))         # per run; the first full pull takes several runs
WOWHEAD_REFRESH_DAYS, WOWHEAD_MISSING_DAYS = 30, 7


def forever_ids(manifest):
    """Every Forever id our pinned sources name, by Wowhead kind (no database needed)."""
    ids = {k: set() for k in WOWHEAD_KINDS}
    fdb = manifest["current"].get("forever-db")
    if fdb:
        for table, kind in (("quest", "quest"), ("npc", "npc"), ("object", "object"), ("item", "item")):
            path = os.path.join(ROOT, fdb["folder"], "forever-db", "data", table + ".jsonl")
            if os.path.exists(path):
                with open(path) as handle:
                    ids[kind] |= {json.loads(line)["id"] for line in handle if line.strip()}
    history = manifest["current"].get("item-history")
    if history:
        for name, kind in (("data/items.jsonl", "item"), ("data/spells.jsonl", "spell")):
            path = os.path.join(ROOT, history["folder"], name)
            if os.path.exists(path):
                with open(path) as handle:
                    ids[kind] |= {json.loads(line)["id"] for line in handle if line.strip()}
    eg = manifest["current"].get("eg-link")
    if eg:
        for path in eg["files"]:
            if path.endswith("/quests.enUS.json") and "/wowf/" in path:
                with open(os.path.join(ROOT, eg["folder"], path)) as handle:
                    ids["quest"] |= {int(k) for k in json.load(handle).get("quests", {}) if k.isdigit()}
    return ids


def pin_wowhead_tooltips(manifest, limit=WOWHEAD_MAX):
    """Wowhead's public tooltip service (nether.wowhead.com/forever/tooltip/<kind>/<id>) for every Forever id we know.
    www.wowhead.com itself refuses scripts and is not touched. Wowhead's data is not openly licensed: reference for our
    own server only."""
    pin_incremental("wowhead-tooltips", "Wowhead, reference only (not openly licensed)", WOWHEAD_KINDS, forever_ids(manifest),
                    lambda kind, i: f"https://nether.wowhead.com/forever/tooltip/{kind}/{i}", WOWHEAD_RATE, limit,
                    WOWHEAD_REFRESH_DAYS, WOWHEAD_MISSING_DAYS, manifest, missing=lambda data: not data or "error" in data)


ICYVEINS = "https://db.icy-veins.com"
ICYVEINS_RATE = 2.0                                               # requests per second, one at a time
ICYVEINS_MAX = int(os.environ.get("ICYVEINS_MAX", "20000"))       # per run; about 15,800 NPCs, a full pull is ~2 hours
ICYVEINS_REFRESH_DAYS, ICYVEINS_MISSING_DAYS = 14, 7              # player-recorded data keeps growing: refresh sooner
ICYVEINS_KEEP = ("entity", "children", "relations", "history")    # the rest of a response is link metadata, the same for all


def icyveins_npc_ids():
    """Every NPC id Icy Veins' Forever database lists. Its NPC page names one page per creature type, each paged 50 at a
    time; a page with no id we haven't seen, or a 404 past the first page, ends that type. Paced like the NPC fetches."""
    top = fetch(f"{ICYVEINS}/wow-forever/npcs/").decode()
    types = sorted(set(re.findall(r'href="/wow-forever/npcs/([a-z][a-z0-9-]*)/"', top)))
    if not types:
        raise ValueError("icyveins: the NPC page lists no creature types")
    ids = set()
    for slug in types:
        for page in range(1, 10000):
            time.sleep(1 / ICYVEINS_RATE)
            try:
                html = fetch(f"{ICYVEINS}/wow-forever/npcs/{slug}/?page={page}").decode()
            except urllib.error.HTTPError as error:
                if error.code == 404 and page > 1:       # past the last page
                    break
                raise
            found = {int(i) for i in re.findall(r'href="/wow-forever/npcs/(\d+)"', html)}
            if not found - ids:
                break
            ids |= found
    return ids


def pin_icyveins(manifest, limit=ICYVEINS_MAX):
    """Icy Veins' WoW Forever database (db.icy-veins.com/wow-forever): one JSON per NPC from the API its pages are built
    from, /api/catalog/wowf/npc/<id>. Besides the client's creature row it carries what players' addons recorded on live
    Forever: map points (addon_points: UiMap, x/y in tenths of a percent, reports, players, last build), levels, drops
    with chances, vendor stock with prices, trainer spells, quests given and taken, gossip text.

    The ids are every NPC its lists show plus every NPC our other pins name. Kept per NPC: entity, children, relations
    and history (ICYVEINS_KEEP). robots.txt allows everything; the data states no licence: reference for our own server
    only, never copied into Everlake (import_sql.REFERENCE_ONLY)."""
    ids = icyveins_npc_ids() | forever_ids(manifest)["npc"]
    print(f"icyveins: {len(ids)} NPC ids")
    pin_incremental("icyveins", "Icy Veins, reference only (no licence stated)", ("npc",), {"npc": ids},
                    lambda kind, i: f"{ICYVEINS}/api/catalog/wowf/{kind}/{i}", ICYVEINS_RATE, limit,
                    ICYVEINS_REFRESH_DAYS, ICYVEINS_MISSING_DAYS, manifest,
                    missing=lambda data: not isinstance(data, dict) or not data.get("entity"),
                    keep=lambda data: {k: data[k] for k in ICYVEINS_KEEP if k in data})


def pin_incremental(name, licence, kinds, wanted, url, rate, limit, refresh_days, missing_days, manifest,
                    missing=lambda data: not data, keep=lambda data: data):
    """One JSON per (kind, id) from a public service, a share at a time.

    Each run fetches ids never fetched, then ids older than refresh_days (missing ones after missing_days), at most
    `limit`, one at a time at `rate` per second. Rows go to a new part, <name>/parts/<time>/<kind>.jsonl; the loader
    keeps the newest row per id. A 404 or a response `missing` refuses is recorded as missing; other errors are tried
    again next run."""
    current = manifest["current"].setdefault(name, {"label": "", "folder": name, "pinned": now(), "files": {}, "licence": licence})
    root = os.path.join(ROOT, current["folder"])
    last = {}
    for rel in sorted(current["files"]):
        with open(os.path.join(root, rel)) as handle:
            for line in handle:
                row = json.loads(line)
                last[(row["kind"], row["id"])] = (row["fetched"], row["status"])
    today = datetime.datetime.now(datetime.timezone.utc)
    def stale(key):
        when, status = last[key]
        age = (today - datetime.datetime.fromisoformat(when.replace("Z", "+00:00"))).days
        return age >= (missing_days if status != "ok" else refresh_days)
    todo = [(k, i) for k in kinds for i in sorted(wanted[k]) if (k, i) not in last]
    todo += [key for k in kinds for key in sorted((k, i) for i in wanted[k] if (k, i) in last and stale((k, i)))]
    todo = todo[:limit]
    if not todo:
        print(f"{name}: nothing to fetch ({len(last)} held)")
        return
    part = "parts/" + now().replace(":", "")[:15]
    buffers = {k: [] for k in kinds}
    def flush():
        for kind, rows in buffers.items():
            if rows:
                rel = f"{part}/{kind}.jsonl"
                data = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
                current["files"][rel] = write(root, rel, data)
        current.update(label=part, pinned=now())
        save(manifest)
    counts = {"ok": 0, "missing": 0, "error": 0}
    started = time.time()
    for n, (kind, i) in enumerate(todo, 1):
        status, data = "ok", None
        try:
            data = json.loads(fetch(url(kind, i), retries=3))
            if missing(data):
                status = "missing"
            else:
                data = keep(data)
        except urllib.error.HTTPError as error:
            status = "missing" if error.code == 404 else "error"
        except (OSError, ValueError):
            status = "error"
        counts[status] += 1
        if status != "error":                      # errors are simply tried again next run
            buffers[kind].append({"kind": kind, "id": i, "fetched": now(), "status": status, "data": data})
        if n % 500 == 0:
            flush()
            print(f"  {name}: {n}/{len(todo)} ({counts})", flush=True)
        time.sleep(max(0.0, n / rate - (time.time() - started)))
    flush()
    print(f"{name}: fetched {len(todo)} ({counts}), {len(last) + counts['ok'] + counts['missing']} held")


def record(manifest, name, pin):
    manifest["current"][name] = pin
    manifest["history"].append({"source": name, "label": pin["label"], "pinned": pin["pinned"]})


def load_table(path):
    with open(path) as handle:
        return json.load(handle)


def write_credits():
    lines = ["# Credits", "", "Everlake's Forever data is built from these. Keep this with anything made from them.", ""]
    lines += [f"- {source['credit']}" for source in SOURCES.values()]
    lines += [f"- {line}" for line in CREDITS_EXTRA]
    with open(os.path.join(ROOT, "CREDITS.md"), "w") as handle:
        handle.write("\n".join(lines) + "\n")


def verify(manifest):
    bad = checked = 0
    for name, pin in manifest["current"].items():
        for relative, info in pin["files"].items():
            path = os.path.join(ROOT, pin["folder"], relative)
            checked += 1
            if not os.path.exists(path) or sha256(path) != info["sha256"]:
                print(f"BAD {name} {relative}")
                bad += 1
    print(f"{checked} files checked, {bad} bad")
    return bad == 0


def save(manifest):
    with open(MANIFEST + ".part", "w") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True)
    os.replace(MANIFEST + ".part", MANIFEST)


def main():
    manifest = {"current": {}, "history": []}
    if os.path.exists(MANIFEST):
        manifest = load_table(MANIFEST)
    if "--verify" in sys.argv:
        sys.exit(0 if verify(manifest) else 1)
    os.makedirs(ROOT, exist_ok=True)
    if "--wowhead-only" in sys.argv:                 # pin_sources.py --wowhead-only [--wowhead-max N]
        limit = int(sys.argv[sys.argv.index("--wowhead-max") + 1]) if "--wowhead-max" in sys.argv else WOWHEAD_MAX
        pin_wowhead_tooltips(manifest, limit)
        save(manifest)
        return
    if "--icyveins-only" in sys.argv:                # pin_sources.py --icyveins-only [--icyveins-max N]
        limit = int(sys.argv[sys.argv.index("--icyveins-max") + 1]) if "--icyveins-max" in sys.argv else ICYVEINS_MAX
        pin_icyveins(manifest, limit)
        write_credits()
        save(manifest)
        return
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    for name, source in SOURCES.items():
        if (only is None and not source.get("opt_in")) or (only is not None and name in only):
            pin_repo(name, source, manifest)
            save(manifest)
    if only is not None:
        for name, pinner in {"live-hotfixes": pin_live_hotfixes, "everloot": pin_everloot,
                             "zephras-talents": pin_zephras_talents, "wago": pin_wago}.items():
            if name in only:
                pinner(manifest)
                save(manifest)
        write_credits()
        save(manifest)
        return
    pin_wago(manifest)
    pin_wowhead(manifest)
    pin_tc_release(manifest)
    save(manifest)
    pin_live_hotfixes(manifest)
    save(manifest)
    pin_foreverdb_net(manifest)
    save(manifest)
    pin_questietrace_own(manifest)
    save(manifest)
    pin_wowhead_tooltips(manifest)
    save(manifest)
    pin_icyveins(manifest)
    save(manifest)
    write_credits()
    save(manifest)


if __name__ == "__main__":
    main()
