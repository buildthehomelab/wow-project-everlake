"""Compare two TACT builds' file lists: Forever (wowf) vs Classic Era, grouped by kind."""
import collections, glob, json, os, re, sqlite3, sys

S = sys.argv[1]

def load(cache):
    db = glob.glob(os.path.join(cache, "tact", "*.sqlite"))[0]
    con = sqlite3.connect(db)
    return {f: (c, s) for f, c, s in con.execute("SELECT fdid, ckey, size FROM files")}

wowf, era = load(S + "/cache-wowf"), load(S + "/cache-era")
names = {}
with open(S + "/dl/listfile.csv", encoding="utf-8", errors="replace") as f:
    for line in f:
        a, _, b = line.rstrip("\n").partition(";")
        if a.isdigit():
            names[int(a)] = b.lower()

def kind(path):
    if not path:
        return "unnamed"
    if path.startswith("world/maps/"):
        return "terrain (world/maps)"
    if path.startswith("world/wmo/"):
        return "buildings (world/wmo)"
    for p, k in (("world/", "world models + textures"), ("creature/", "creatures"), ("character/", "characters"),
                 ("item/", "items"), ("interface/", "interface"), ("sound/", "sound"), ("spells/", "spell effects"),
                 ("dbfilesclient/", "game tables (db2)"), ("tileset/", "terrain textures"), ("environments/", "sky"),
                 ("cameras/", "cameras"), ("particles/", "particles"), ("textures/", "textures")):
        if path.startswith(p):
            return k
    return "other"

rows = collections.defaultdict(lambda: collections.Counter())
for fdid in set(wowf) | set(era):
    k = kind(names.get(fdid))
    a, b = wowf.get(fdid), era.get(fdid)
    if a and b:
        st = "same" if a[0] == b[0] else "differ"
    elif b:
        st = "era_only"
    else:
        st = "forever_only"
    rows[k][st] += 1
    rows[k][st + "_mb"] += (b or a)[1] / 1048576
    if st == "differ":
        rows[k]["forever_mb_of_differ"] += a[1] / 1048576

tot = collections.Counter()
for k in sorted(rows, key=lambda k: -(rows[k]["era_only_mb"] + rows[k]["differ_mb"])):
    r = rows[k]
    tot.update(r)
    print("%-26s same %7d | differ %7d (%8.0f MB era) | era-only %7d (%8.0f MB) | forever-only %7d (%8.0f MB)" % (
        k, r["same"], r["differ"], r["differ_mb"], r["era_only"], r["era_only_mb"], r["forever_only"], r["forever_only_mb"]))
r = tot
print("%-26s same %7d | differ %7d (%8.0f MB era) | era-only %7d (%8.0f MB) | forever-only %7d (%8.0f MB)" % (
    "TOTAL", r["same"], r["differ"], r["differ_mb"], r["era_only"], r["era_only_mb"], r["forever_only"], r["forever_only_mb"]))
print("same MB (shared bytes): %.0f" % r["same_mb"])
print("forever build files %d, era build files %d" % (len(wowf), len(era)))

# terrain per map folder, tiles differing
maps = collections.defaultdict(collections.Counter)
tiles = collections.defaultdict(set)
for fdid in set(wowf) | set(era):
    p = names.get(fdid, "")
    m = re.match(r"world/maps/([^/]+)/[^/]*?_(\d+)_(\d+)(_obj0|_obj1|_tex0|_lod)?\.adt$", p)
    if not m:
        continue
    a, b = wowf.get(fdid), era.get(fdid)
    st = "same" if a and b and a[0] == b[0] else "differ" if a and b else "era_only" if b else "forever_only"
    maps[m.group(1)][st] += 1
    if st in ("differ", "era_only"):
        tiles[m.group(1)].add((int(m.group(2)), int(m.group(3))))
print()
print("ADT files per map (same / differ / era-only / forever-only), tiles needing Classic copies")
for mp in sorted(maps, key=lambda m: -sum(maps[m].values()))[:25]:
    c = maps[mp]
    print("%-28s %6d %6d %6d %6d  tiles %d" % (mp, c["same"], c["differ"], c["era_only"], c["forever_only"], len(tiles[mp])))
json.dump({m: sorted(t) for m, t in tiles.items()}, open(S + "/tiles.json", "w"))
