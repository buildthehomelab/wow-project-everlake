#!/usr/bin/env python3
"""The game's local storage (Data/data: data.NNN archives, .idx key tables, shmem), read and checked.

    casc_local.py inspect <Data folder>             prints what the files contain and whether every checksum matches
    casc_local.py install <Data folder> <dir>       adds the BLTE files in <dir> (named by encoded key); backs up first
    casc_local.py undo <Data folder>                reverses the newest install
    casc_local.py selftest                          install into a fake storage, read back, undo

Gate 2 (docs/custom-files.md): the client never streams map terrain; a map's files must already be in local
storage, as Blizzard's installer leaves them. This module reads that storage the way CascLib (MIT) does and checks
our understanding against a real install before anything is written:

  NNNNNNNNNN.idx  one key table per bucket (the first 2 hex digits), the last 8 are a version; the newest counts.
                  Header: guarded block (size, Jenkins hash) around version 7, bucket, sizes of the fields.
                  Entries (9-byte encoded key, 5-byte archive+offset, 4-byte size) either as one guarded block, or
                  in 0x200-byte pages from 0x1000 on, each entry behind its own 32-bit hash.
  data.NNN        the stored files, each behind a 30-byte header: encoded key (reversed), size, 2 flag bytes,
                  a Jenkins hash of those, and a checksum mixing in the file's offset.
"""
import os
import re
import struct
import sys

MASK = 0xFFFFFFFF


def _rot(x, k):
    return ((x << k) | (x >> (32 - k))) & MASK


def hashlittle2(data, pc=0, pb=0):
    """Bob Jenkins' lookup3 hashlittle2 (byte-wise, the same results as the aligned C version)."""
    length = len(data)
    a = b = c = (0xDEADBEEF + length + pc) & MASK
    c = (c + pb) & MASK
    i = 0
    while length > 12:
        a = (a + struct.unpack_from("<I", data, i)[0]) & MASK
        b = (b + struct.unpack_from("<I", data, i + 4)[0]) & MASK
        c = (c + struct.unpack_from("<I", data, i + 8)[0]) & MASK
        a = (a - c) & MASK; a ^= _rot(c, 4); c = (c + b) & MASK
        b = (b - a) & MASK; b ^= _rot(a, 6); a = (a + c) & MASK
        c = (c - b) & MASK; c ^= _rot(b, 8); b = (b + a) & MASK
        a = (a - c) & MASK; a ^= _rot(c, 16); c = (c + b) & MASK
        b = (b - a) & MASK; b ^= _rot(a, 19); a = (a + c) & MASK
        c = (c - b) & MASK; c ^= _rot(b, 4); b = (b + a) & MASK
        length -= 12
        i += 12
    if length == 0:
        return c, b
    tail = data[i:] + bytes(12 - length)
    a = (a + struct.unpack_from("<I", tail, 0)[0]) & MASK
    b = (b + struct.unpack_from("<I", tail, 4)[0]) & MASK
    c = (c + struct.unpack_from("<I", tail, 8)[0]) & MASK
    c ^= b; c = (c - _rot(b, 14)) & MASK
    a ^= c; a = (a - _rot(c, 11)) & MASK
    b ^= a; b = (b - _rot(a, 25)) & MASK
    c ^= b; c = (c - _rot(b, 16)) & MASK
    a ^= c; a = (a - _rot(c, 4)) & MASK
    b ^= a; b = (b - _rot(a, 14)) & MASK
    c ^= b; c = (c - _rot(b, 24)) & MASK
    return c, b


def hashlittle(data, initval=0):
    return hashlittle2(data, initval, 0)[0]


def bucket_of(ekey):
    x = 0
    for byte in ekey[:9]:
        x ^= byte
    return (x & 0xF) ^ (x >> 4)


OFFSET_TABLE = (0x049396B8, 0x72A82A9B, 0xEE626CCA, 0x9917754F, 0x15DE40B1, 0xF5A8A9B6, 0x421EAC7E, 0xA9D55C9A,
                0x317FD40C, 0x04FAF80D, 0x3D6BE971, 0x52933CFD, 0x27F64B7D, 0xC6F5C11B, 0xD5757E3A, 0x6C388745)


def entry_header(ekey, size, offset, flags=b"\0\0"):
    """The 30-byte header in front of a stored file, as Blizzard's installer writes it (CascLib's VerifyHeaderSpan).
    size: the BLTE size plus these 30 bytes; offset: where the header starts in its data.NNN."""
    head = ekey[::-1] + struct.pack("<I", size) + flags
    jenkins = struct.pack("<I", hashlittle(head, 0x3D6BE971))
    head += jenkins
    v = (offset + 30) & MASK
    encoded = struct.pack("<I", OFFSET_TABLE[v & 0xF] ^ v)
    hashed = bytearray(4)
    for i, byte in enumerate(head):
        hashed[i & 3] ^= byte
    checksum = bytes(hashed[(len(head) + j) & 3] ^ encoded[(len(head) + j) & 3] for j in range(4))
    return head + checksum


class Index:
    """One .idx key table."""

    def __init__(self, path):
        self.path = path
        self.data = data = open(path, "rb").read()
        size, hsh = struct.unpack_from("<II", data, 0)
        self.header_ok = size == 16 and hashlittle(data[8:8 + size]) == hsh
        (self.version, self.bucket, self.flags, self.size_bytes, self.offset_bytes, self.key_bytes, self.segment_bits,
         self.max_offset) = struct.unpack_from("<HBBBBBBQ", data, 8)
        self.entry_len = self.key_bytes + self.offset_bytes + self.size_bytes
        self.entries = []      # (ekey9, archive, offset, size, where in the file)
        self.layout = None
        self.bad = 0
        at = 8 + 16
        at = (at + 15) & ~15   # the entries' guarded block starts at the next 16-byte boundary
        self._continuous(at) or self._paged()

    def _parse(self, raw, where):
        key = raw[:self.key_bytes]
        loc = int.from_bytes(raw[self.key_bytes:self.key_bytes + self.offset_bytes], "big")
        size = struct.unpack_from("<I", raw, self.key_bytes + self.offset_bytes)[0]
        return key, loc >> self.segment_bits, loc & ((1 << self.segment_bits) - 1), size, where

    def _continuous(self, at):
        if at + 8 > len(self.data):
            return False
        size, hsh = struct.unpack_from("<II", self.data, at)
        if not size or at + 8 + size > len(self.data):
            return False
        hi = lo = 0
        for i in range(0, size - size % self.entry_len, self.entry_len):
            hi, lo = hashlittle2(self.data[at + 8 + i:at + 8 + i + self.entry_len], hi, lo)
        if hi != hsh:
            return False
        self.layout = "continuous"
        self.block_at, self.block_size = at, size
        for i in range(0, size - size % self.entry_len, self.entry_len):
            self.entries.append(self._parse(self.data[at + 8 + i:at + 8 + i + self.entry_len], at + 8 + i))
        return True

    def _paged(self):
        self.layout = "paged"
        step = (self.entry_len + 3) & ~3
        self.empty = 0
        for page in range(0x1000, len(self.data), 0x200):
            at = page
            while at + 4 + self.entry_len < page + 0x200:
                hsh = struct.unpack_from("<I", self.data, at)[0]
                if hsh == 0:
                    self.empty += 1
                    at += 4 + step
                    continue
                raw = self.data[at + 4:at + 4 + self.entry_len + 1]
                if (hashlittle(raw) | 0x80000000) != hsh:
                    self.bad += 1
                else:
                    self.entries.append(self._parse(raw, at))
                at += 4 + step


def newest_indexes(folder):
    best = {}
    for name in os.listdir(folder):
        m = re.fullmatch(r"([0-9a-f]{2})([0-9a-f]{8})\.idx", name)
        if m:
            bucket, version = int(m.group(1), 16), int(m.group(2), 16)
            if bucket not in best or version > best[bucket][0]:
                best[bucket] = (version, name)
    return {b: os.path.join(folder, n) for b, (v, n) in sorted(best.items())}


def inspect(data_root):
    folder = os.path.join(data_root, "data")
    print("hash self-test:", hex(hashlittle(b"")), hex(hashlittle(b"Four score and seven years ago")),
          hex(hashlittle(b"Four score and seven years ago", 1)), "(expect 0xdeadbeef 0x17770551 0xcd628161)")
    archives = sorted(n for n in os.listdir(folder) if re.fullmatch(r"data\.\d{3}", n))
    print("archives: %d, last %s; sizes of the last three: %s" % (
        len(archives), archives[-1] if archives else "-",
        [(n, os.path.getsize(os.path.join(folder, n))) for n in archives[-3:]]))
    for extra in sorted(n for n in os.listdir(folder) if not n.startswith("data.") and not n.endswith(".idx")):
        p = os.path.join(folder, extra)
        head = open(p, "rb").read(512 if extra == "shmem" else 64)
        print("other file %s, %d bytes, starts %s" % (extra, os.path.getsize(p), head.hex()))
    idx = newest_indexes(folder)
    print("index files: %d buckets" % len(idx))
    samples = []
    for bucket, path in idx.items():
        ix = Index(path)
        keys = [e[0] for e in ix.entries]
        print("  %s: %d bytes, header ok %s, v%d bucket %d flags %d, sizes key/offset/size %d/%d/%d, segment bits %d, "
              "max offset %#x, layout %s, entries %d, bad %d%s, sorted %s, buckets right %s" % (
                  os.path.basename(path), len(ix.data), ix.header_ok, ix.version, ix.bucket, ix.flags, ix.key_bytes,
                  ix.offset_bytes, ix.size_bytes, ix.segment_bits, ix.max_offset, ix.layout, len(ix.entries), ix.bad,
                  (", empty %d" % ix.empty) if ix.layout == "paged" else "", keys == sorted(keys),
                  all(bucket_of(k) == bucket for k in keys)))
        shift = {}
        for k in keys[:2000]:
            d = (bucket_of(k) - bucket) % 16
            shift[d] = shift.get(d, 0) + 1
        print("    bucket formula off by (count of 2000 keys): %s" % shift)
        if bucket in (0, 7) and ix.entries:
            print("    bytes 0x18..0x40: %s" % ix.data[0x18:0x40].hex())
            print("    first page head: %s" % ix.data[0x1000:0x1040].hex())
        for e in ix.entries[:1] + ix.entries[len(ix.entries) // 2:len(ix.entries) // 2 + 1] + ix.entries[-1:]:
            samples.append(e)
    print("stored file headers (30 bytes before each file):")
    ok_j = ok_c = 0
    for key, archive, offset, size, _where in samples[:24]:
        path = os.path.join(folder, "data.%03d" % archive)
        if not os.path.exists(path):
            print("  data.%03d missing" % archive)
            continue
        with open(path, "rb") as f:
            f.seek(offset)
            head = f.read(34)
        ekey_rev, hsize = head[:16], struct.unpack_from("<I", head, 16)[0]
        mine = entry_header(ekey_rev[::-1], hsize, offset, head[20:22])
        j, c = mine[22:26] == head[22:26], mine[26:30] == head[26:30]
        ok_j += j
        ok_c += c
        print("  data.%03d @%d: key matches %s, size %d (index %d), flags %s, jenkins %s, checksum %s, then %r" % (
            archive, offset, ekey_rev[::-1][:9] == key, hsize, size, head[20:22].hex(), j, c, head[30:34]))
        print("    raw %d %d %s" % (archive, offset, head[:30].hex()))
    print("headers: jenkins right %d, checksum right %d, of %d" % (ok_j, ok_c, min(len(samples), 24)))


def entry_bytes(key, archive, offset, size, segment_bits=30):
    """One 18-byte index entry: 9-byte key, 5-byte archive and offset (big endian), 4-byte size (little endian)."""
    return key[:9] + ((archive << segment_bits) | offset).to_bytes(5, "big") + struct.pack("<I", size)


def rebuild_index(ix, add):
    """The bytes of index `ix` with entries `add` (18-byte raw entries) added, sorted, re-hashed, same file size."""
    if ix.layout != "continuous" or ix.entry_len != 18 or not ix.header_ok:
        raise ValueError("%s: only the continuous version 7 layout is written" % ix.path)
    old = ix.data[ix.block_at + 8:ix.block_at + 8 + ix.block_size]
    tail = ix.data[ix.block_at + 8 + ix.block_size:]
    if tail.strip(b"\0"):
        raise ValueError("%s: data after the entries; not touching it" % ix.path)
    entries = sorted([old[i:i + 18] for i in range(0, len(old), 18)] + list(add))
    raw = b"".join(entries)
    hi = lo = 0
    for e in entries:
        hi, lo = hashlittle2(e, hi, lo)
    out = ix.data[:ix.block_at] + struct.pack("<II", len(raw), hi) + raw
    if len(out) > len(ix.data):
        raise ValueError("%s: no room for %d more entries" % (ix.path, len(add)))
    return out + bytes(len(ix.data) - len(out))


def install(data_root, files, log=print):
    """Put files [(encoded key, BLTE bytes)] into local storage: a new data.NNN for them, entries added in place to
    the newest index of their buckets (shmem names those versions, so the names stay). Backs up what it changes in
    <Data>/everlake-backup/<n>, with undo.json. Returns the backup folder."""
    import hashlib
    import json
    import time
    folder = os.path.join(data_root, "data")
    idx = newest_indexes(folder)
    parsed = {b: Index(p) for b, p in idx.items()}
    have = {e[0] for ix in parsed.values() for e in ix.entries}
    todo = []
    for ekey, blob in files:
        head = struct.unpack_from(">I", blob, 4)[0]
        if blob[:4] != b"BLTE" or hashlib.md5(blob[:head] if head else blob).digest() != ekey:
            raise ValueError("%s: not the BLTE file of that key" % ekey.hex())
        if ekey[:9] in have:
            log("  %s already in local storage, skipped" % ekey.hex())
            continue
        todo.append((ekey, blob))
    if not todo:
        log("nothing to add")
        return None
    numbers = [int(n[5:]) for n in os.listdir(folder) if re.fullmatch(r"data\.\d{3}", n)]
    archive = max(numbers) + 1
    if archive >= 1 << (40 - 30):
        raise ValueError("no free archive number")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(data_root, "everlake-backup", stamp)
    os.makedirs(backup)
    adds, offset, blob_all = {}, 0, bytearray()
    for ekey, blob in todo:
        size = 30 + len(blob)
        blob_all += entry_header(ekey, size, offset) + blob
        adds.setdefault(bucket_of(ekey), []).append(entry_bytes(ekey, archive, offset, size))
        offset += size
    if offset >= 1 << 30:
        raise ValueError("files too large for one archive")
    new_indexes = {b: rebuild_index(parsed[b], add) for b, add in adds.items()}   # all checks before any write
    undo = {"archive": "data.%03d" % archive, "indexes": []}
    for b in new_indexes:
        name = os.path.basename(idx[b])
        open(os.path.join(backup, name), "wb").write(parsed[b].data)
        undo["indexes"].append(name)
    json.dump(undo, open(os.path.join(backup, "undo.json"), "w"), indent=1)
    path = os.path.join(folder, "data.%03d" % archive)
    with open(path + ".part", "wb") as f:
        f.write(blob_all)
    os.replace(path + ".part", path)
    for b, data in new_indexes.items():
        with open(idx[b] + ".part", "wb") as f:
            f.write(data)
        os.replace(idx[b] + ".part", idx[b])
    log("wrote %d files (%d bytes) to data.%03d, %d index files updated; backup %s" % (
        len(todo), len(blob_all), archive, len(new_indexes), backup))
    check(data_root, [e for e, _b in todo], log)
    return backup


def check(data_root, ekeys, log=print):
    """Find each file through the index and read it back from its archive, checking every hash on the way."""
    import hashlib
    folder = os.path.join(data_root, "data")
    idx = {b: Index(p) for b, p in newest_indexes(folder).items()}
    bad = 0
    for ekey in ekeys:
        ix = idx[bucket_of(ekey)]
        found = [e for e in ix.entries if e[0] == ekey[:9]]
        if not ix.header_ok or ix.layout != "continuous" or len(found) != 1:
            log("  %s: not found in index %s" % (ekey.hex(), os.path.basename(ix.path)))
            bad += 1
            continue
        _k, archive, offset, size, _w = found[0]
        with open(os.path.join(folder, "data.%03d" % archive), "rb") as f:
            f.seek(offset)
            raw = f.read(size)
        blob = raw[30:]
        head = struct.unpack_from(">I", blob, 4)[0]
        ok = (raw[:30] == entry_header(ekey, size, offset) and blob[:4] == b"BLTE"
              and hashlib.md5(blob[:head] if head else blob).digest() == ekey)
        bad += not ok
        if not ok:
            log("  %s: bad bytes in data.%03d at %d" % (ekey.hex(), archive, offset))
    log("read back %d files: %s" % (len(ekeys), "all good" if not bad else "%d BAD" % bad))
    return not bad


def undo(data_root, log=print):
    """Reverse the newest install: restore its index files, remove its archive."""
    import json
    root = os.path.join(data_root, "everlake-backup")
    stamps = sorted(os.listdir(root)) if os.path.isdir(root) else []
    if not stamps:
        log("nothing to undo")
        return
    backup = os.path.join(root, stamps[-1])
    plan = json.load(open(os.path.join(backup, "undo.json")))
    folder = os.path.join(data_root, "data")
    for name in plan["indexes"]:
        data = open(os.path.join(backup, name), "rb").read()
        with open(os.path.join(folder, name) + ".part", "wb") as f:
            f.write(data)
        os.replace(os.path.join(folder, name) + ".part", os.path.join(folder, name))
    archive = os.path.join(folder, plan["archive"])
    if os.path.exists(archive):
        os.remove(archive)
    os.rename(backup, backup + "-undone")
    log("restored %d index files, removed %s" % (len(plan["indexes"]), plan["archive"]))


def selftest(log=print):
    """Build a small fake storage, install into it, read it back with the same reader that checked a real install."""
    import hashlib
    import tempfile
    root = tempfile.mkdtemp()
    folder = os.path.join(root, "data")
    os.makedirs(folder)
    rng = hashlib.sha256(b"everlake").digest()
    fake = []
    for b in range(16):
        keys = []
        n = 0
        while len(keys) < 20:
            k = hashlib.md5(rng + bytes([b, n % 256, n // 256])).digest()
            n += 1
            if bucket_of(k) == b:
                keys.append(entry_bytes(k, 0, 1000 * len(keys), 100))
        header = struct.pack("<HBBBBBBQ", 7, b, 0, 4, 5, 9, 30, 0xFFC0000000)
        body = struct.pack("<II", 16, hashlittle(header)) + header + bytes(8)
        raw = b"".join(sorted(keys))
        hi = lo = 0
        for e in sorted(keys):
            hi, lo = hashlittle2(e, hi, lo)
        data = body + struct.pack("<II", len(raw), hi) + raw
        open(os.path.join(folder, "%02x%08x.idx" % (b, 0x22)), "wb").write(data + bytes(4096 - len(data)))
        fake.append(keys)
    open(os.path.join(folder, "data.000"), "wb").write(bytes(100))
    files = []
    for i in range(5):
        content = b"everlake test file %d" % i
        blob = b"BLTE" + bytes(4) + b"N" + content
        files.append((hashlib.md5(blob).digest(), blob))
    ok = all(Index(p).header_ok and Index(p).layout == "continuous" for p in newest_indexes(folder).values())
    install(root, files, log)
    good = check(root, [e for e, _b in files], log)
    undo(root, log)
    restored = all(len(Index(p).entries) == 20 for p in newest_indexes(folder).values())
    log("selftest: fake storage readable %s, install read back %s, undo restored %s" % (ok, good, restored))
    return ok and good and restored and not os.path.exists(os.path.join(folder, "data.001"))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "inspect":
        inspect(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "selftest":
        sys.exit(0 if selftest() else 1)
    elif len(sys.argv) == 4 and sys.argv[1] == "install":
        # install <Data folder> <folder of files named by their encoded key>
        src = sys.argv[3]
        files = [(bytes.fromhex(n), open(os.path.join(src, n), "rb").read()) for n in sorted(os.listdir(src))
                 if re.fullmatch(r"[0-9a-f]{32}", n)]
        sys.exit(0 if install(sys.argv[2], files) is not None or not files else 1)
    elif len(sys.argv) == 3 and sys.argv[1] == "undo":
        undo(sys.argv[2])
    else:
        sys.exit(__doc__)
