#!/usr/bin/env python3
"""The China ("low violence") Undead bodies as files of their own, for a per-character choice (docs/china-undead.md).

    python3 tools/looks/china_undead.py --cache <tact cache pinned to wowf> --out <dir>

Blizzard's build keeps two copies of some files under ONE FileDataID: the normal one, and a censored one in a root
block flagged LowViolence (0x80) that the client only reads when its overrideArchive setting is on (the China
client). The China Undead model has no exposed bones. To offer it per character, both have to exist side by side,
so this copies the China model of each sex and its 7 skin files (the mesh, in levels of detail) under new
FileDataIDs, and points the model's skin list (SFID chunk) at the new skin ids. Everything else the model names is
left as it is: its skeleton (SKID) is byte for byte the normal one, and its textures are the character's own.

Writes <dir>/<FileDataID> for every file and <dir>/files.tsv, ready for `tools/tact/patch.py --files-from`.
Every China file is checked against its content key.
"""
import argparse
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tact"))
import tact  # noqa: E402

# Our FileDataIDs: far above Blizzard's (8.6 million in November 2026), 954xxxxx like the other Everlake ids.
FIRST_FDID = 95450001

# sex -> (model, its skins in SFID order: 00, lod01-lod06), from the normal and China models' own SFID chunks
MODELS = {
    "male": ("character/scourge/male/scourgemale_hd.m2", 959310,
             [959362, 1066547, 1066546, 2126393, 4876492, 4876493, 4876494]),
    "female": ("character/scourge/female/scourgefemale_hd.m2", 997378,
               [997389, 1080445, 1080444, 2132581, 4876495, 4876496, 4876497]),
}
SKELETONS = {"male": 2140228, "female": 2140222}


def low_violence_files(t):
    """{FileDataID: (content key, encoded key, archive, offset, size)} of the build's LowViolence enUS files."""
    build = tact.config(t.stored("config", t.build).decode())
    cdn = tact.config(t.stored("config", t.cdn).decode())
    enc = {}
    for ckey, ekey in tact.encoding_entries(tact.blte(t.stored("data", build["encoding"][1]))):
        enc.setdefault(ckey, ekey)
    where = {}
    for n, name in enumerate(cdn["archives"]):
        for ekey, size, offset in tact.index_entries(t.stored("data", name, ".index")):
            where.setdefault(ekey, (n, offset, size))
    for name in cdn.get("file-index", []):
        for ekey, size, _ in tact.index_entries(t.stored("data", name, ".index")):
            where.setdefault(ekey, (tact.LOOSE, 0, size))
    root_ekey = enc[bytes.fromhex(build["root"][0])]
    data = tact.blte(t.raw(root_ekey, *where[root_ekey]))
    # same walk as tact.root_entries, keeping the LowViolence blocks instead of the normal ones
    first, second = struct.unpack_from("<II", data, 4)
    if first < 100:
        at, version = first, second
        total, named = struct.unpack_from("<II", data, 12)
    else:
        at, version, total, named = 12, 1, first, second
    out = {}
    while at < len(data):
        if version >= 2:
            count, locale, f1, f2, f3 = struct.unpack_from("<IIIIB", data, at)
            flags, at = f1 | f2 | (f3 << 17), at + 17
        else:
            count, flags, locale = struct.unpack_from("<III", data, at)
            at += 12
        block = at
        at += count * 20
        if not (total != named and flags & tact.NO_NAME_HASH):
            at += count * 8
        if not (flags & tact.LOW_VIOLENCE and locale & tact.ENUS):
            continue
        fdid = -1
        for i, delta in enumerate(struct.unpack_from("<%di" % count, data, block)):
            fdid += delta + 1
            ckey = data[block + count * 4 + i * 16:block + count * 4 + i * 16 + 16]
            ekey = enc.get(ckey)
            if ekey in where and fdid not in out:
                out[fdid] = (ckey, ekey) + where[ekey]
    return out


def read_china(t, lv, fdid):
    ckey, ekey, archive, offset, size = lv[fdid]
    data = tact.blte(t.raw(ekey, archive, offset, size))
    if hashlib.md5(data).digest() != ckey:
        raise SystemExit("China copy of %d doesn't match its content key" % fdid)
    return data


def set_skins(model, skins):
    """The model with its SFID chunk (skin FileDataIDs) replaced; every other byte unchanged."""
    at = 0
    while at + 8 <= len(model):
        cid, size = model[at:at + 4], struct.unpack_from("<I", model, at + 4)[0]
        if cid == b"SFID":
            old = struct.unpack_from("<%dI" % (size // 4), model, at + 8)
            if len(old) != len(skins):
                raise SystemExit("SFID lists %d skins, expected %d" % (len(old), len(skins)))
            return model[:at + 8] + struct.pack("<%dI" % len(skins), *skins) + model[at + 8 + size:]
        at += 8 + size
    raise SystemExit("model has no SFID chunk")


def chunk(model, cid):
    at = 0
    while at + 8 <= len(model):
        size = struct.unpack_from("<I", model, at + 4)[0]
        if model[at:at + 4] == cid:
            return model[at + 8:at + 8 + size]
        at += 8 + size
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True, help="tact cache folder, pinned to the Forever build (wowf)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    t = tact.Tact(args.cache, product="wowf", log=lambda *a: None)
    print("build %s: reading the LowViolence root blocks" % t.version)
    lv = low_violence_files(t)
    print("%d LowViolence enUS files" % len(lv))
    os.makedirs(args.out, exist_ok=True)
    rows, fdid = [], FIRST_FDID
    for sex, (path, model_id, skin_ids) in MODELS.items():
        model = read_china(t, lv, model_id)
        sfid = struct.unpack("<7I", chunk(model, b"SFID"))
        if list(sfid) != skin_ids:
            raise SystemExit("%s: China SFID %s, expected %s" % (sex, sfid, skin_ids))
        if struct.unpack("<I", chunk(model, b"SKID"))[0] != SKELETONS[sex]:
            raise SystemExit("%s: China model uses another skeleton" % sex)
        if SKELETONS[sex] in lv and read_china(t, lv, SKELETONS[sex]) != t.read(SKELETONS[sex]):
            raise SystemExit("%s: the China skeleton differs from the normal one" % sex)
        new_model, new_skins = fdid, list(range(fdid + 1, fdid + 1 + len(skin_ids)))
        fdid += 1 + len(skin_ids)
        for skin_id, new in zip(skin_ids, new_skins):
            data = read_china(t, lv, skin_id)
            open(os.path.join(args.out, str(new)), "wb").write(data)
            rows.append((new, "skin", "%s (China copy of %d)" % (path.replace(".m2", "") + "_skin", skin_id)))
        data = set_skins(model, new_skins)
        open(os.path.join(args.out, str(new_model)), "wb").write(data)
        rows.append((new_model, "m2", "%s (China copy of %d)" % (path, model_id)))
        print("%s: model %d -> %d (%d bytes), skins %s -> %d-%d" % (sex, model_id, new_model, len(data), skin_ids,
                                                                  new_skins[0], new_skins[-1]))
    with open(os.path.join(args.out, "files.tsv"), "w") as f:
        for new, kind, note in sorted(rows):
            f.write("%d\t%s\t%s\n" % (new, kind, note))
    print("wrote %d files and files.tsv to %s" % (len(rows), args.out))


if __name__ == "__main__":
    main()
