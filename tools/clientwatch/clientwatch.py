#!/usr/bin/env python3
"""Keeps up with Blizzard's WoW Forever client: finds new builds and checks them against ours (docs/client-watch.md).

    python3 tools/clientwatch/clientwatch.py builds                 the Forever builds, and which are newer than ours
    python3 tools/clientwatch/clientwatch.py check 1.60.1.70862 ... static checks of those builds against ours
    python3 tools/clientwatch/clientwatch.py run                    both: every build newer than ours is checked

Common options:
    --cache DIR      downloads (wago.tools CSVs, WoWDBDefs, core files); default ~/.cache/everlake-clientwatch.
                     Point it at tools/era/hotfix_kit.py's --cache to share the CSVs.
    --out DIR        writes report.md and report.json there (check/run)
    --source DIR     another checkout whose sql/everlake/*hotfixes*.sql and tools/era/kits/*.json count too
                     (a branch not merged yet); repeatable
    --baseline VER   the build we run; default: the "client 1.60.1.N" note in the Dockerfile
    --tc-commit SHA  the core we run; default: TC_COMMIT from .env, .env.example or the Dockerfile

Exit status: 0 = nothing newer, or every newer build passed (or waits for data); 1 = a check failed.
Set GITHUB_TOKEN to lift GitHub's anonymous rate limit (60 requests an hour; one run needs about 15).
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checks  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VERSIONS = "http://us.patch.battle.net:1119/%s/%s"
WAGO_BUILDS = "https://wago.tools/api/builds"
TC_REPO = "advocaite/TrinityCore"
TC_BRANCHES = ["forever", "forever-bots"]
OPCODE_FILES = re.compile(r"(Opcodes|Protocol/|WorldSession\.cpp|Packets/)")


def get(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers={**checks.UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


GITHUB_SEEN = {}


def github(path):
    if path in GITHUB_SEEN:
        return GITHUB_SEEN[path]
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    GITHUB_SEEN[path] = json.loads(get("https://api.github.com/" + path, headers))
    return GITHUB_SEEN[path]


# --- what we run -----------------------------------------------------------------------------------------------

def read_env(path):
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            m = re.match(r"\s*([A-Z_]+)=(.*)", line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"')
    return out


def ours(repo, baseline=None, tc_commit=None):
    """{"build", "tc_commit", "tc_branch", "client_build"} of the server in this checkout."""
    docker = open(os.path.join(repo, "Dockerfile"), encoding="utf-8").read()
    env = read_env(os.path.join(repo, ".env")) or read_env(os.path.join(repo, ".env.example"))
    if not baseline:
        m = re.search(r"client (\d+\.\d+\.\d+\.\d+)", docker)
        if not m:
            raise SystemExit("no 'client 1.60.1.N' note in the Dockerfile: pass --baseline")
        baseline = m.group(1)
    if not tc_commit:
        m = re.search(r"ARG TC_COMMIT=(\w+)", docker)
        tc_commit = env.get("TC_COMMIT") or (m and m.group(1))
    m = re.search(r'TrinityCore "([\w-]+)" branch', docker)
    return {"build": baseline, "tc_commit": tc_commit, "tc_branch": m.group(1) if m else "forever",
            "client_build": env.get("CLIENT_BUILD") or ""}


# --- the watcher -----------------------------------------------------------------------------------------------

def blizzard_versions(product):
    """{version: [where]} from Blizzard's version server: what the launcher installs now (versions) and what it
    pre-downloads (bgdl)."""
    out = {}
    for kind in ("versions", "bgdl"):
        try:
            text = get(VERSIONS % (product, kind), timeout=30)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if getattr(e, "code", 0) != 404:  # no bgdl for a product = nothing pre-downloading
                checks.log("  blizzard %s: %s" % (kind, e))
            continue
        header = None
        for line in text.splitlines():
            if not line or line.startswith("##"):
                continue
            cells = line.split("|")
            if header is None:
                header = [c.split("!")[0] for c in cells]
                continue
            row = dict(zip(header, cells))
            if row.get("VersionsName"):
                out.setdefault(row["VersionsName"], {}).setdefault(kind, set()).add(row.get("Region", "?"))
    return {v: ["%s (%s)" % ("live" if k == "versions" else "pre-download", " ".join(sorted(r)))
                for k, r in sorted(w.items(), reverse=True)] for v, w in out.items()}


def find_builds(product, base):
    """[{version, build, first_seen, blizzard, newer}] newest first: wago.tools' build history plus Blizzard's own
    version server (which has a new build first, before wago.tools has processed it)."""
    seen = {}
    try:
        for b in json.loads(get(WAGO_BUILDS)).get(product, []):
            seen.setdefault(b["version"], {"version": b["version"], "first_seen": b.get("created_at", ""),
                                           "build_config": b.get("build_config", ""), "blizzard": []})
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
        checks.log("  wago builds: %s" % e)
    for v, where in blizzard_versions(product).items():
        seen.setdefault(v, {"version": v, "first_seen": "", "build_config": "", "blizzard": []})["blizzard"] = where
    out = sorted(seen.values(), key=lambda b: checks.build_number(b["version"]), reverse=True)
    for b in out:
        b["build"] = checks.build_number(b["version"])
        b["newer"] = b["build"] > checks.build_number(base)
    return out


# --- the core fork ---------------------------------------------------------------------------------------------

def core_check(pin, version):
    """What advocaite/TrinityCore did for the build after our pinned commit: build_info, auth keys, opcodes."""
    number = str(checks.build_number(version))
    res = {"branches": {}, "build_info": [], "auth_key": [], "opcodes": [], "mentions": [], "error": None}
    seen = set()
    try:
        for branch in TC_BRANCHES:
            cmp = github("repos/%s/compare/%s...%s" % (TC_REPO, pin, branch))
            res["branches"][branch] = {"ahead": cmp.get("ahead_by", 0), "behind": cmp.get("behind_by", 0)}
            for c in cmp.get("commits", [])[-40:]:
                sha = c["sha"]
                if sha in seen:
                    continue
                seen.add(sha)
                title = c["commit"]["message"].split("\n")[0]
                tag = "%s %s (%s)" % (sha[:8], title, branch)
                if c["commit"]["message"].find(number) >= 0:
                    res["mentions"].append(tag)
                if len(c.get("parents", [])) > 1:
                    continue  # merges: their changes come with the merged commits
                files = github("repos/%s/commits/%s" % (TC_REPO, sha)).get("files", [])
                for f in files:
                    patch = f.get("patch", "")
                    if number in patch and "build_info" in patch:
                        res["build_info"].append("%s: %s" % (tag, f["filename"]))
                    if number in patch and "build_auth_key" in patch:
                        res["auth_key"].append("%s: %s" % (tag, f["filename"]))
                    if OPCODE_FILES.search(f["filename"]):
                        res["opcodes"].append("%s: %s" % (tag, f["filename"]))
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, KeyError) as e:
        res["error"] = str(e)
    return res


# --- report ----------------------------------------------------------------------------------------------------

MANUAL = [
    "**Opcodes.** A new build can move client messages (70790 added two at 0x71/0x72, "
    "docker/patches/0001-classic-70790-client-messages.patch). Nothing in the public data shows this: only a login "
    "with the new client (the L3 smoke test) and the server's packet log do. Look for unknown or mis-sized "
    "opcodes in Server.log after character create, enter world, cast, loot, mail, auction.",
    "**Auth key.** The core has no build_auth_key for Forever builds; we run with "
    "Network.SkipBuildAuthKeyCheck = 1 (docker/entrypoint.sh), so a missing key does not block a login.",
    "**Gate 2 custom files.** tools/tact/patch.py rewrites one build's build config, root, encoding and TVFS "
    "manifests. A patched build made from the old build does not carry over: rebuild it from the new build "
    "(about 300 MB of indexes from Blizzard's CDN) and re-run collect.py, since the new build may now ship files "
    "the patch added.",
    "**Hotfix cache on the client.** Rows changed inside a push the client already has don't reach it (Test 1). "
    "Whether the client drops its hotfix cache (DBCache.bin) on a build change is not checked: after an update, "
    "confirm in game that the kits' rows still arrive (Death Coil in the spellbook, map 530 loads).",
    "**Server data.** The server's dbc/maps/vmaps/mmaps come from the build that was live when extract ran. If "
    "layouts are unchanged the old data keeps working; re-extracting is only needed for a layout change or new "
    "map data.",
]


def level_order(level):
    return {"FAIL": 0, "WARN": 1, "TODO": 2, "INFO": 3}.get(level, 4)


def report(run, results):
    """Markdown report of a run."""
    o = run["ours"]
    lines = ["# Forever client watch, %s" % run["time"], "",
             "We run **%s**, core %s `%s`%s." % (o["build"], o["tc_branch"], (o["tc_commit"] or "?")[:10],
                                                (", CLIENT_BUILD override %s" % o["client_build"])
                                                if o["client_build"] else ""), ""]
    if run.get("builds"):
        lines += ["## Builds", "", "| Version | Seen by wago.tools (UTC) | On Blizzard's version server | Newer |",
                  "|---|---|---|---|"]
        for b in run["builds"][:8]:
            lines.append("| %s | %s | %s | %s |" % (b["version"], b["first_seen"] or "-",
                                                    ", ".join(b["blizzard"]) or "-", "yes" if b["newer"] else ""))
        lines.append("")
    if not results:
        lines += ["No build newer than ours: nothing to check.", ""]
    for r in results:
        s, c = r["static"], r["core"]
        lines += ["## %s: %s" % (r["version"], s["status"]), ""]
        lines += ["### Static checks", ""]
        items = sorted(s["items"], key=lambda x: level_order(x[0]))
        for level, text in items:
            lines.append("- **%s** %s" % (level, text))
        for p in s["pending"]:
            lines.append("- **PENDING** %s" % p)
        if not items and not s["pending"]:
            lines.append("- everything matched")
        ours_changed = [x for x in s["layout"] if x["tier"] == "ours"]
        server_changed = [x for x in s["layout"] if x["tier"] == "server"]
        lines += ["", "Layouts (WoWDBDefs): %d tables our hotfixes and kits use, %s changed; %d tables the core "
                  "loads, %s changed; %d other tables changed." % (
                      len(s["ours"]), len(ours_changed) or "none", len(s["server"]),
                      len(server_changed) or "none", len([x for x in s["layout"] if x["tier"] == "other"]))]
        lines += ["", "Rows we send as hotfixes: %d in %d tables (%d replace a row of %s, the rest use our own IDs); "
                  "%d of them differ between the builds (Blizzard added, changed or removed the row)."
                  % (s["override_count"], s["override_tables"], s["override_blizzard"], s["base"], len(s["rows"]))]
        lines += ["", "| Table | %s | %s | Added | Removed |" % (s["base"], s["new"]), "|---|---|---|---|---|"]
        for t in s["ids"]:
            lines.append("| %s | %d | %d | %s | %s |" % (
                t["table"], t["base_count"], t["new_count"], fmt_ids(t["added"]), fmt_ids(t["removed"])))
        lines += ["", "### Core fork (%s)" % TC_REPO, ""]
        if c["error"]:
            lines.append("- **PENDING** GitHub: %s" % c["error"])
        for b, v in c["branches"].items():
            lines.append("- `%s` is %d commit(s) ahead of our pin" % (b, v["ahead"])
                         + (" and %d behind" % v["behind"] if v["behind"] else ""))
        if c["build_info"]:
            lines += ["- build_info for %s: %s" % (r["version"], "; ".join(c["build_info"])),
                      "  Moving the pin to that commit (or setting CLIENT_BUILD=%s in .env) lets the server accept "
                      "the build." % checks.build_number(r["version"])]
        elif not c["error"]:
            lines.append("- **TODO** no build_info for %s in the fork after our pin: set CLIENT_BUILD=%s in .env "
                         "(docker/entrypoint.sh writes the row) or wait for the fork"
                         % (r["version"], checks.build_number(r["version"])))
        if c["auth_key"]:
            lines.append("- auth key: %s" % "; ".join(c["auth_key"]))
        applied = [o for o in c["opcodes"] if o[:8] in run.get("patch_shas", {})]
        todo = [o for o in c["opcodes"] if o not in applied]
        for o in applied:
            lines.append("- opcode change after our pin, already applied as %s: %s"
                         % (run["patch_shas"][o[:8]], o))
        if todo:
            lines.append("- **TODO** opcode/protocol files changed after our pin (review): %s" % "; ".join(todo))
        for m in c["mentions"]:
            if not any(m.split(" ")[0] in x for x in c["build_info"]):
                lines.append("- commit naming the build: %s" % m)
        lines.append("")
    if results:
        lines += ["## Needs a person", ""] + ["- " + m for m in MANUAL] + [
            "- **Live check (L3).** On the Mac mini, after Battle.net updates the game: "
            "`client/macos/everlake-client.sh smoke` (planned, docs/client-watch.md).", ""]
    return "\n".join(lines)


def fmt_ids(pairs, limit=12):
    if not pairs:
        return "-"
    shown = ", ".join("%d %s" % (i, n) if n else str(i) for i, n in pairs[:limit])
    return shown + (" (+%d more)" % (len(pairs) - limit) if len(pairs) > limit else "")


# --- main ------------------------------------------------------------------------------------------------------

def our_files(repo, sources):
    sql, kits = [], []
    for root in [repo] + (sources or []):
        sql += glob.glob(os.path.join(root, "sql", "everlake", "*hotfixes*.sql"))
        kits += glob.glob(os.path.join(root, "tools", "era", "kits", "*.json"))
    dedup = lambda paths: list({os.path.basename(p): p for p in sorted(paths)}.values())  # noqa: E731
    return dedup(sql), dedup(kits)


def applied_patches(repo, sources):
    """{short sha: patch file} of the core commits docker/patches already applies (format-patch "From <sha>")."""
    out = {}
    for root in [repo] + (sources or []):
        for p in glob.glob(os.path.join(root, "docker", "patches", "*.patch")):
            with open(p, encoding="utf-8", errors="replace") as f:
                m = re.match(r"From ([0-9a-f]{40}) ", f.readline())
            if m:
                out[m.group(1)[:8]] = os.path.basename(p)
    return out


def run_checks(args, run, versions):
    dbd = checks.DBD(args.cache)
    wago = checks.Wago(args.cache)
    sql, kits = our_files(args.repo, args.source)
    run["sql_files"] = [os.path.basename(p) for p in sql]
    run["kit_files"] = [os.path.basename(p) for p in kits]
    run["patch_shas"] = applied_patches(args.repo, args.source)
    core = checks.server_tables(args.cache, TC_REPO, run["ours"]["tc_commit"])
    results = []
    for v in versions:
        checks.log("checking %s against %s" % (v, run["ours"]["build"]))
        s = checks.static_check(run["ours"]["build"], v, dbd, wago, sql, kits, core)
        if core is None:
            s["pending"].append("could not read DB2Stores.cpp of core %s" % run["ours"]["tc_commit"])
        c = core_check(run["ours"]["tc_commit"], v)
        results.append({"version": v, "static": s, "core": c})
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["builds", "check", "run"])
    ap.add_argument("versions", nargs="*")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--source", action="append")
    ap.add_argument("--cache", default=os.path.expanduser("~/.cache/everlake-clientwatch"))
    ap.add_argument("--out")
    ap.add_argument("--product", default="wowf")
    ap.add_argument("--baseline")
    ap.add_argument("--tc-commit")
    ap.add_argument("--limit", type=int, default=3, help="run: check at most this many newer builds (newest first)")
    ap.add_argument("--json", action="store_true", help="builds: print JSON")
    args = ap.parse_args()

    run = {"time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "ours": ours(args.repo, args.baseline, args.tc_commit)}
    if args.command in ("builds", "run"):
        run["builds"] = find_builds(args.product, run["ours"]["build"])
    if args.command == "builds":
        if args.json:
            print(json.dumps(run, indent=1))
        else:
            for b in run["builds"][:10]:
                print("%-14s %-20s %-4s %s" % (b["version"], b["first_seen"] or "-", "NEW" if b["newer"] else "",
                                               ", ".join(b["blizzard"])))
        return 0
    versions = args.versions if args.command == "check" else \
        [b["version"] for b in run["builds"] if b["newer"]][:args.limit]
    results = run_checks(args, run, versions) if versions else []
    text = report(run, results)
    status = "NONE" if not results else "FAIL" if any(r["static"]["status"] == "FAIL" for r in results) else \
        "PENDING" if any(r["static"]["status"] == "PENDING" for r in results) else "PASS"
    run["status"] = status
    run["results"] = results
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
            f.write(text)
        with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
            json.dump(run, f, indent=1, default=list)
    print(text)
    print("status: %s" % status, file=sys.stderr)
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
