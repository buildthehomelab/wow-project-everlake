"""Row-by-row compare of game tables (wago.tools CSVs): Forever vs Classic Era."""
import collections, csv, json, os, sys, time, urllib.request
csv.field_size_limit(1 << 30)
S, FOREVER, ERA = sys.argv[1], sys.argv[2], sys.argv[3]
TABLES = sys.argv[4].split(",")
WAGO = "https://wago.tools/db2/%s/csv?build=%s"

def load(table, build):
    path = os.path.join(S, "wago", "%s-%s.csv" % (table, build))
    if not os.path.exists(path):
        try:
            req = urllib.request.Request(WAGO % (table, build), headers={"User-Agent": "everlake-measure/1.0"})
            data = urllib.request.urlopen(req, timeout=300).read()
        except Exception as e:
            print("  %s %s: %s" % (table, build, e), file=sys.stderr)
            return None
        open(path, "wb").write(data)
        time.sleep(0.5)
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        r = csv.reader(f)
        try:
            head = next(r)
        except StopIteration:
            return None
        return head, list(r)

out = {}
for t in TABLES:
    a, b = load(t, FOREVER), load(t, ERA)
    if not a or not b:
        print("%-28s missing (%s)" % (t, "forever" if not a else "era"))
        out[t] = {"missing": "forever" if not a else "era"}
        continue
    ha, hb = a[0], b[0]
    if "ID" not in ha or "ID" not in hb:
        print("%-28s no ID column" % t)
        continue
    common = [c for c in ha if c in hb]
    ia, ib = [ha.index(c) for c in common], [hb.index(c) for c in common]
    ka, kb = ha.index("ID"), hb.index("ID")
    ra = {row[ka]: tuple(row[i] for i in ia) for row in a[1] if len(row) == len(ha)}
    rb = {row[kb]: tuple(row[i] for i in ib) for row in b[1] if len(row) == len(hb)}
    both = ra.keys() & rb.keys()
    differ = [k for k in both if ra[k] != rb[k]]
    cols = collections.Counter()
    for k in differ:
        for c, x, y in zip(common, ra[k], rb[k]):
            if x != y:
                cols[c] += 1
    r = {"forever": len(ra), "era": len(rb), "same": len(both) - len(differ), "differ": len(differ),
         "era_only": len(rb.keys() - ra.keys()), "forever_only": len(ra.keys() - rb.keys()),
         "cols_only_forever": [c for c in ha if c not in hb], "cols_only_era": [c for c in hb if c not in ha],
         "top_cols": cols.most_common(6)}
    out[t] = r
    print("%-28s F %7d E %7d | same %7d differ %6d era-only %6d forever-only %6d | %s" % (
        t, r["forever"], r["era"], r["same"], r["differ"], r["era_only"], r["forever_only"],
        ", ".join("%s %d" % c for c in r["top_cols"][:4])), flush=True)
json.dump(out, open(os.path.join(S, "tables-%s.json" % TABLES[0]), "w"), indent=1)
