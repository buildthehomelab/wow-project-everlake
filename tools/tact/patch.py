#!/usr/bin/env python3
"""A game build that is Blizzard's plus our own files (gate 2, docs/custom-files.md).

    python3 tools/tact/patch.py --cache <tact cache> --out <dir> FDID=FILE [FDID=FILE ...]
    python3 tools/tact/patch.py --cache <tact cache> --selftest

<tact cache> is the folder `tact.py --cache` downloads into, already pinned to the build to patch (product wowf).

A FileDataID the build already has gets our bytes instead of Blizzard's; a new FileDataID is added. The client
finds a file through this chain, so these are rewritten and everything else is Blizzard's, untouched:

  build config   names vfs-root, vfs-1 and encoding                      -> new build config
  vfs-root/vfs-1 the TVFS manifest; its ".root" entry names the root      -> its .root entry repointed
  root           FileDataID -> content key                                -> our files' content keys
  encoding       content key -> encoded key, encoded key -> encoding spec -> entries for every new file
  CDN config     names the loose-file index                               -> new CDN config
  file-index     encoded key -> size, for files stored on their own       -> entries for every new file

Every new file is stored on its own (not in an archive), BLTE-encoded and named by its encoded key, exactly as
Blizzard's CDN stores its loose files. <out> is laid out like the CDN (<cdn path>/config, <cdn path>/data), so
tools/tact/cdn.py can serve it with everything else passed through to Blizzard.

--selftest rebuilds the encoding file, the loose-file index, the root and the TVFS manifest from Blizzard's own
copies with nothing added and checks the result is byte for byte the same, then round-trips the BLTE encoder.
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tact  # noqa: E402

GAME_ESPEC = "b:256K*=z"  # how our game files are encoded (Blizzard uses it for small files, e.g. vfs-root)


def md5(data):
    return hashlib.md5(data).digest()


# --- BLTE ----------------------------------------------------------------------------------------

def _units(text):
    m = re.fullmatch(r"(\d+)([KM]?)", text)
    if not m:
        raise ValueError("encoding spec size %r" % text)
    return int(m.group(1)) * {"": 1, "K": 1024, "M": 1024 * 1024}[m.group(2)]


def _split_top(text):
    """Split on commas that are not inside braces."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return out


def _frame(raw, mode):
    if mode == "n":
        return b"N" + raw
    if mode == "z" or mode.startswith("z:"):
        level = 9
        m = re.match(r"z:\{(\d+)", mode)
        if m:
            level = int(m.group(1))
        return b"Z" + zlib.compress(raw, level)
    raise ValueError("encoding mode %r is not supported" % mode)


def blte_encode(data, spec):
    """Encode `data` as the encoding spec says. Returns (BLTE bytes, encoded key)."""
    if not spec.startswith("b:"):
        blob = b"BLTE" + bytes(4) + _frame(data, spec)
        return blob, md5(blob)
    inner = spec[2:]
    if inner.startswith("{") and inner.endswith("}"):
        inner = inner[1:-1]
    pieces, at = [], 0
    for element in _split_top(inner):
        size, _, mode = element.partition("=")
        if size == "*":
            pieces.append((data[at:], mode))
            at = len(data)
        elif size.endswith("*"):
            step = _units(size[:-1])
            while at < len(data):
                pieces.append((data[at:at + step], mode))
                at += step
        else:
            step, count = (size.split("*") + ["1"])[:2]
            for _ in range(int(count)):
                pieces.append((data[at:at + _units(step)], mode))
                at += _units(step)
    if at < len(data):
        raise ValueError("encoding spec %s covers %d of %d bytes" % (spec, at, len(data)))
    frames = [(_frame(raw, mode), len(raw)) for raw, mode in pieces]
    header = struct.pack(">4sIB", b"BLTE", 12 + 24 * len(frames), 0x0F) + len(frames).to_bytes(3, "big")
    header += b"".join(struct.pack(">II", len(f), n) + md5(f) for f, n in frames)
    return header + b"".join(f for f, _ in frames), md5(header)


# --- root (FileDataID -> content key), version 2 --------------------------------------------------

def root_set(data, files):
    """The root with `files` ({FileDataID: content key}) set: existing ids changed in place, new ids added."""
    magic, hsize, version, total, named = struct.unpack_from("<4sIIII", data, 0)
    if magic != b"TSFM" or hsize != 24 or version != 2:
        raise ValueError("root layout not supported (%r, header %d, version %d)" % (magic, hsize, version))
    out, seen, template, at = bytearray(data), set(), None, hsize
    while at < len(data):
        count, locale, f1, f2, f3 = struct.unpack_from("<IIIIB", data, at)
        flags, body = f1 | f2 | (f3 << 17), at + 17
        if (template is None and locale & tact.ENUS and flags & tact.NO_NAME_HASH
                and not flags & tact.LOW_VIOLENCE):
            template = (locale, f1, f2, f3)
        fdid = -1
        for i, delta in enumerate(struct.unpack_from("<%di" % count, data, body)):
            fdid += delta + 1
            if fdid in files:
                o = body + count * 4 + i * 16
                out[o:o + 16] = files[fdid]
                seen.add(fdid)
        at = body + count * 20 + (0 if (total != named and flags & tact.NO_NAME_HASH) else count * 8)
    new = sorted(set(files) - seen)
    if new:
        if template is None:
            raise ValueError("root has no block to copy for new files")
        deltas, prev = [], -1
        for fdid in new:
            deltas.append(fdid - prev - 1)
            prev = fdid
        out += struct.pack("<IIIIB", len(new), *template)
        out += struct.pack("<%di" % len(new), *deltas) + b"".join(files[f] for f in new)
        struct.pack_into("<I", out, 12, total + len(new))
    return bytes(out), new


# --- TVFS manifest -------------------------------------------------------------------------------

def tvfs_repoint(data, old_ekey, old_ckey, ekey, esize, csize, ckey):
    """The manifest with the container entry of (old_ekey, old_ckey) changed to the new file."""
    (magic, _ver, _hsize, ekey_size, _pkey_size, flags, _pto, _pts, _vto, _vts, cft_off, cft_size,
     _depth) = struct.unpack_from(">4sBBBBIIIIIIIH", data, 0)
    if magic != b"TVFS" or ekey_size != 9 or flags != 7:
        raise ValueError("TVFS layout not supported")
    at = data.find(old_ekey[:9], cft_off, cft_off + cft_size)
    if at < 0 or data.find(old_ekey[:9], at + 1, cft_off + cft_size) >= 0:
        raise ValueError("the entry is missing or not unique in the manifest")
    if data[at + 18:at + 34] != old_ckey:
        raise ValueError("the entry's layout is not ekey, esize, spec, csize, ckey")
    out = bytearray(data)
    out[at:at + 9] = ekey[:9]
    struct.pack_into(">I", out, at + 9, esize)
    struct.pack_into(">I", out, at + 14, csize)
    out[at + 18:at + 34] = ckey
    return bytes(out), struct.unpack_from(">I", data, at + 9)[0]


# --- encoding ------------------------------------------------------------------------------------

class Encoding:
    """The encoding file, parsed far enough to add entries and write it back."""

    def __init__(self, data):
        if data[:2] != b"EN":
            raise ValueError("not an encoding file")
        (self.version, ckey_size, ekey_size, self.ce_kb, self.ek_kb, ce_pages, ek_pages, self.unk,
         spec_size) = struct.unpack_from(">BBBHHIIBI", data, 2)
        if ckey_size != 16 or ekey_size != 16:
            raise ValueError("encoding key sizes")
        self.specs = data[22:22 + spec_size].split(b"\0")[:-1]
        at = 22 + spec_size + ce_pages * 32
        page = self.ce_kb * 1024
        self.ce = []
        for p in range(ce_pages):
            o, end = at + p * page, at + (p + 1) * page
            while o + 22 <= end and data[o]:
                n = 22 + data[o] * 16
                self.ce.append(data[o:o + n])
                o += n
        at += ce_pages * page + ek_pages * 32
        page = self.ek_kb * 1024
        self.ek = []
        for p in range(ek_pages):
            o, end = at + p * page, at + (p + 1) * page
            while o + 25 <= end and data[o:o + 16] != bytes(16):
                self.ek.append(data[o:o + 25])
                o += 25
        self.trailer = data[at + ek_pages * page:]
        self.ckeys = {e[6:22] for e in self.ce}
        self.ekeys = {e[:16] for e in self.ek}

    def spec_index(self, spec):
        spec = spec.encode()
        if spec not in self.specs:
            self.specs.append(spec)
        return self.specs.index(spec)

    def add(self, ckey, ekey, csize, esize, spec):
        if ckey not in self.ckeys:
            self.ce.append(bytes([1]) + csize.to_bytes(5, "big") + ckey + ekey)
            self.ckeys.add(ckey)
        if ekey not in self.ekeys:
            self.ek.append(ekey + struct.pack(">I", self.spec_index(spec)) + esize.to_bytes(5, "big"))
            self.ekeys.add(ekey)

    @staticmethod
    def _pages(entries, page, key, last_marker=b""):
        pages, cur = [], b""
        for e in entries:
            if len(cur) + len(e) > page:
                pages.append(cur)
                cur = b""
            cur += e
        if cur or not pages:
            pages.append(cur)
        if last_marker and len(pages[-1]) + len(last_marker) <= page:
            pages[-1] += last_marker
        pages = [p.ljust(page, b"\0") for p in pages]
        index = b"".join(key(p) + md5(p) for p in pages)
        return pages, index

    def build(self):
        self.ce.sort(key=lambda e: e[6:22])
        self.ek.sort(key=lambda e: e[:16])
        ce_pages, ce_index = self._pages(self.ce, self.ce_kb * 1024, lambda p: p[6:22])
        ek_pages, ek_index = self._pages(self.ek, self.ek_kb * 1024, lambda p: p[:16],
                                         bytes(16) + b"\xff\xff\xff\xff" + bytes(5))
        specs = b"".join(s + b"\0" for s in self.specs)
        header = b"EN" + struct.pack(">BBBHHIIBI", self.version, 16, 16, self.ce_kb, self.ek_kb, len(ce_pages),
                                     len(ek_pages), self.unk, len(specs))
        sizes = [len(header), len(specs), len(ce_index), len(ce_pages) * self.ce_kb * 1024, len(ek_index),
                 len(ek_pages) * self.ek_kb * 1024]
        trailer = ("b:{%d=n,%d=z,%d=n,%d=n,%d=n,%d=n,*=z}" % tuple(sizes)).encode()
        return header + specs + ce_index + b"".join(ce_pages) + ek_index + b"".join(ek_pages) + trailer


# --- loose-file index ----------------------------------------------------------------------------

def index_build(entries):
    """A loose-file index (no offsets): [(encoded key, size)] -> (index bytes, its name)."""
    entries = sorted(entries)
    per = 4096 // 20
    blocks = [entries[i:i + per] for i in range(0, len(entries), per)] or [[]]
    raw = [b"".join(k + struct.pack(">I", s) for k, s in b).ljust(4096, b"\0") for b in blocks]
    toc = b"".join(b[-1][0] if b else bytes(16) for b in blocks) + b"".join(md5(r)[:8] for r in raw)
    body = struct.pack("<8BI", 1, 0, 0, 4, 0, 4, 16, 8, len(entries))
    footer = md5(toc)[:8] + body + md5(body + bytes(8))[:8]
    return b"".join(raw) + toc + footer, md5(footer).hex()


# --- the build -----------------------------------------------------------------------------------

class Build:
    def __init__(self, cache, log=print):
        self.dir = os.path.join(cache, "tact")
        self.log = log
        pin = open(os.path.join(self.dir, "build.txt")).read().splitlines()
        self.build_key, self.cdn_key, self.version, self.path, hosts = pin[:5]
        self.hosts = hosts.split()
        self.build_text = self.config(self.build_key).decode()
        self.cdn_text = self.config(self.cdn_key).decode()
        self.build = tact.config(self.build_text)
        self.cdn = tact.config(self.cdn_text)

    def url(self, kind, name, suffix=""):
        return "http://%s/%s/%s/%s/%s/%s%s" % (self.hosts[0], self.path, kind, name[:2], name[2:4], name, suffix)

    def stored(self, kind, name, suffix=""):
        path = os.path.join(self.dir, kind, name + suffix)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = tact.get(self.url(kind, name, suffix))
            open(path + ".part", "wb").write(data)
            os.replace(path + ".part", path)
        return open(path, "rb").read()

    def config(self, name):
        return self.stored("config", name)

    def loose(self, ekey_hex):
        """A loose CDN file (BLTE) by encoded key, kept in the cache."""
        return self.stored("data", ekey_hex)

    def load(self):
        b = self.build
        self.log("reading encoding (%s MB)" % (int(b["encoding-size"][0]) >> 20))
        self.enc_raw = self.loose(b["encoding"][1])
        self.encoding = tact.blte(self.enc_raw)
        if md5(self.encoding).hex() != b["encoding"][0]:
            raise RuntimeError("encoding doesn't match its content key")
        root_ckey = bytes.fromhex(b["root"][0])
        self.root_ekey = next(e for c, e in tact.encoding_entries(self.encoding) if c == root_ckey)
        self.log("reading root")
        self.root_blte = self.loose(self.root_ekey.hex())
        self.root = tact.blte(self.root_blte)
        if md5(self.root) != root_ckey:
            raise RuntimeError("root doesn't match its content key")
        self.vfs_blte = self.loose(b["vfs-root"][1])
        self.vfs = tact.blte(self.vfs_blte)
        if md5(self.vfs).hex() != b["vfs-root"][0] or b["vfs-1"] != b["vfs-root"]:
            raise RuntimeError("vfs-root doesn't match, or vfs-1 is not the same manifest")
        self.file_index = self.stored("data", self.cdn["file-index"][0], ".index")

    def selftest(self):
        self.load()
        ok = True

        def check(name, good):
            nonlocal ok
            self.log("%-44s %s" % (name, "same" if good else "DIFFERENT"))
            ok = ok and good

        enc = Encoding(self.encoding)
        check("encoding rebuilt with nothing added", enc.build() == self.encoding)
        entries = [(k, s) for k, s, _o in tact.index_entries(self.file_index)]
        data, name = index_build(entries)
        check("loose-file index rebuilt", data == self.file_index and name == self.cdn["file-index"][0])
        check("root with nothing set", root_set(self.root, {})[0] == self.root)
        same, _ = tvfs_repoint(self.vfs, self.root_ekey, bytes.fromhex(self.build["root"][0]), self.root_ekey,
                               struct.unpack_from(">I", self.vfs, self.vfs.find(self.root_ekey[:9], 46) + 9)[0],
                               len(self.root), bytes.fromhex(self.build["root"][0]))
        check("TVFS .root entry rewritten with its own values", same == self.vfs)
        for spec, sample in (("b:256K*=z", self.vfs), ("b:{256K*=z}", self.root[:700000]), ("z", b"x" * 1000),
                             ("b:{22=n,100=z,*=z}", self.encoding[:5000])):
            blob, ekey = blte_encode(sample, spec)
            check("BLTE %s decodes back" % spec, tact.blte(blob) == sample)
        return ok

    def patch(self, files, out):
        """files: {FileDataID: bytes}. Writes the patched build under out; returns its summary."""
        self.load()
        b, cdn_root = self.build, os.path.join(out, self.path)
        enc = Encoding(self.encoding)
        written = {}

        def put(kind, name, data, suffix=""):
            path = os.path.join(cdn_root, kind, name[:2], name[2:4], name + suffix)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").write(data)
            written[name + suffix] = len(data)

        def store(content, spec):
            blob, ekey = blte_encode(content, spec)
            if tact.blte(blob) != content:
                raise RuntimeError("BLTE round trip failed")
            put("data", ekey.hex(), blob)
            enc.add(md5(content), ekey, len(content), len(blob), spec)
            return blob, ekey

        ours = {}
        for fdid, content in sorted(files.items()):
            _blob, ekey = store(content, GAME_ESPEC)
            ours[fdid] = {"ckey": md5(content).hex(), "ekey": ekey.hex(), "size": len(content)}
        root, added = root_set(self.root, {f: bytes.fromhex(v["ckey"]) for f, v in ours.items()})
        root_blob, root_ekey = store(root, "b:{256K*=z}")
        old_tvfs_esize = struct.unpack_from(">I", self.vfs, self.vfs.find(self.root_ekey[:9], 46) + 9)[0]
        vfs, _ = tvfs_repoint(self.vfs, self.root_ekey, bytes.fromhex(b["root"][0]), root_ekey,
                              len(root_blob) + (old_tvfs_esize - len(self.root_blte)), len(root), md5(root))
        vfs_blob, vfs_ekey = store(vfs, "b:256K*=z")
        enc_content = enc.build()
        trailer = enc_content[enc_content.rindex(b"b:{"):].decode()
        enc_blob, enc_ekey = blte_encode(enc_content, trailer)
        if tact.blte(enc_blob) != enc_content:
            raise RuntimeError("encoding round trip failed")
        put("data", enc_ekey.hex(), enc_blob)

        loose = {k: s for k, s, _o in tact.index_entries(self.file_index)}
        for name, size in written.items():
            if "." not in name:
                loose[bytes.fromhex(name)] = size
        index, index_name = index_build(list(loose.items()))
        put("data", index_name, index, ".index")

        def replace(text, key, value):
            new, n = re.subn(r"(?m)^%s = .*$" % re.escape(key), "%s = %s" % (key, value), text)
            if n != 1:
                raise RuntimeError("config line %s found %d times" % (key, n))
            return new

        text = self.build_text
        text = replace(text, "root", md5(root).hex())
        text = replace(text, "encoding", "%s %s" % (md5(enc_content).hex(), enc_ekey.hex()))
        text = replace(text, "encoding-size", "%d %d" % (len(enc_content), len(enc_blob)))
        for key in ("vfs-root", "vfs-1"):
            text = replace(text, key, "%s %s" % (md5(vfs).hex(), vfs_ekey.hex()))
            text = replace(text, key + "-size", "%d %d" % (len(vfs), len(vfs_blob)))
        build_key = md5(text.encode()).hex()
        put("config", build_key, text.encode())
        cdn_text = replace(self.cdn_text, "file-index", index_name)
        cdn_text = replace(cdn_text, "file-index-size", str(len(index)))
        cdn_key = md5(cdn_text.encode()).hex()
        put("config", cdn_key, cdn_text.encode())

        summary = {"blizzard_build_key": self.build_key, "blizzard_cdn_key": self.cdn_key, "version": self.version,
                   "cdn_path": self.path, "blizzard_hosts": self.hosts, "build_key": build_key,
                   "cdn_key": cdn_key, "files": {str(f): v for f, v in ours.items()},
                   "added_file_data_ids": added, "written": written}
        json.dump(summary, open(os.path.join(out, "build.json"), "w"), indent=2)
        return summary


def verify(out, build, files):
    """Look our files up through the patched chain, as the client would, and check their bytes."""
    summary = json.load(open(os.path.join(out, "build.json")))
    root = os.path.join(out, summary["cdn_path"])

    def ours(kind, name, suffix=""):
        return open(os.path.join(root, kind, name[:2], name[2:4], name + suffix), "rb").read()

    conf = tact.config(ours("config", summary["build_key"]).decode())
    cdn = tact.config(ours("config", summary["cdn_key"]).decode())
    enc = tact.blte(ours("data", conf["encoding"][1]))
    assert md5(enc).hex() == conf["encoding"][0], "encoding content key"
    vfs = tact.blte(ours("data", conf["vfs-root"][1]))
    assert md5(vfs).hex() == conf["vfs-root"][0], "vfs-root content key"
    loose = {k: s for k, s, _o in tact.index_entries(ours("data", cdn["file-index"][0], ".index"))}
    ckey_to_ekey = dict(tact.encoding_entries(enc))
    root_ckey = bytes.fromhex(conf["root"][0])
    root_ekey = ckey_to_ekey[root_ckey]
    at = vfs.find(root_ekey[:9], 46)
    assert at > 0 and vfs[at + 18:at + 34] == root_ckey, "vfs-root .root entry"
    assert root_ekey in loose, "root in the loose-file index"
    rootdata = tact.blte(ours("data", root_ekey.hex()))
    assert md5(rootdata) == root_ckey, "root content key"
    found = dict(tact.root_entries(rootdata))
    shared = []
    for fdid, content in files.items():
        ckey = found[fdid]
        assert ckey == md5(content), "file %d content key in the root" % fdid
        ekey = ckey_to_ekey[ckey]
        if ekey not in loose:
            shared.append(fdid)  # Blizzard already ships these exact bytes; the client fetches their copy
            continue
        data = tact.blte(ours("data", ekey.hex()))
        assert data == content, "file %d bytes" % fdid
    original = dict(tact.root_entries(build.root))
    changed = sum(1 for f, c in original.items() if found.get(f) != c and f not in files)
    assert changed == 0, "%d files we didn't touch changed" % changed
    note = (" (%s: same bytes as a Blizzard file, so Blizzard's copy is used)" % ", ".join(map(str, shared))
            if shared else "")
    return "verified: %d files through build %s, every other file still Blizzard's%s" % (
        len(files), summary["build_key"], note)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", required=True, help="tact cache folder, pinned to the build to patch")
    ap.add_argument("--out", help="folder for the patched build (laid out like the CDN)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("files", nargs="*", metavar="FDID=FILE")
    args = ap.parse_args()
    build = Build(args.cache)
    if args.selftest:
        sys.exit(0 if build.selftest() else 1)
    if not args.out or not args.files:
        ap.error("--out and at least one FDID=FILE are needed")
    files = {}
    for item in args.files:
        fdid, _, path = item.partition("=")
        files[int(fdid)] = open(path, "rb").read()
    summary = build.patch(files, args.out)
    print("build key %s, CDN key %s (Blizzard's: %s, %s)" % (summary["build_key"], summary["cdn_key"],
                                                            summary["blizzard_build_key"],
                                                            summary["blizzard_cdn_key"]))
    print(verify(args.out, build, files))


if __name__ == "__main__":
    main()
