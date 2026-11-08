"""Terrain heights (MCVT) of 40 random Azeroth/Kalimdor tiles whose files differ between Forever and Classic Era:
real ground change, or the same ground re-exported?"""
import glob, os, random, re, sqlite3, struct, sys
S = sys.argv[1]; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tact"))
import tact
F, E = tact.Tact(S + "/cache-wowf", "wowf", log=lambda *a: None), tact.Tact(S + "/cache-era", "wow_classic_era", log=lambda *a: None)
names = {}
for line in open(S + "/dl/listfile.csv", encoding="utf-8", errors="replace"):
    a, _, b = line.rstrip("\n").partition(";")
    m = re.match(r"world/maps/(azeroth|kalimdor)/\1_(\d+)_(\d+)\.adt$", b.lower())
    if m and a.isdigit():
        names[int(a)] = (m.group(1), int(m.group(2)), int(m.group(3)))
def heights(data):
    out, at = {}, 0
    while at + 8 <= len(data):
        tag, size = data[at:at+4], struct.unpack_from("<I", data, at+4)[0]
        if tag == b"KNCM":
            ix, iy = struct.unpack_from("<II", data, at+8+4)
            base = struct.unpack_from("<3f", data, at+8+104)[2]
            sub = at + 8 + 128
            while sub < at + 8 + size:
                st, ss = data[sub:sub+4], struct.unpack_from("<I", data, sub+4)[0]
                if st == b"TVCM":
                    out[(ix, iy)] = [base + h for h in struct.unpack_from("<145f", data, sub+8)]
                sub += 8 + ss
        at += 8 + size
    return out
def chunks(data):
    seen, at = [], 0
    while at + 8 <= len(data):
        seen.append(data[at:at+4][::-1].decode("latin1")); at += 8 + struct.unpack_from("<I", data, at+4)[0]
    return sorted(set(seen))
fd = {f for f, in F.db.execute("SELECT fdid FROM files")}; ed = {f: c for f, c in E.db.execute("SELECT fdid, ckey FROM files")}
fc = {f: c for f, c in F.db.execute("SELECT fdid, ckey FROM files")}
cand = [f for f in names if f in fc and f in ed and fc[f] != ed[f]]
random.seed(1); pick = random.sample(cand, 40)
summary = []
for f in pick:
    a, b = F.read(f), E.read(f)
    ha, hb = heights(a), heights(b)
    common = ha.keys() & hb.keys()
    d = max((abs(x - y) for k in common for x, y in zip(ha[k], hb[k])), default=-1)
    moved = sum(1 for k in common if max(abs(x - y) for x, y in zip(ha[k], hb[k])) > 0.5)
    summary.append((names[f], len(a), len(b), len(common), round(d, 2), moved))
    print(names[f], "bytes F/E", len(a), len(b), "chunks", len(common), "max dz", round(d, 2), "chunks moved>0.5", moved, flush=True)
f = pick[0]; print("chunk types F", chunks(F.read(f))); print("chunk types E", chunks(E.read(f)))
