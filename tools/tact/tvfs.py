"""TVFS manifests (vfs-root and its sub-manifests): read, change and write back.

The client finds a WoW file by a path built from its root entry, "<locale+content flags>:<FileDataID><content key>"
in hex, and looks that path up in the TVFS tree: vfs-root's path table leads to a sub-manifest, whose path table
leads to the file's span (encoded key, sizes). A file that is in the root but not in this tree is "not found".

Layout (big endian), from CascLib's CascRootFile_TVFS.cpp (MIT) and checked against the Forever build:
  header       "TVFS", version, header size, ekey size, patch key size, flags (4), path table offset/size,
               VFS table offset/size, container file table offset/size, max depth (2), [EST offset/size]
  path table   a prefix tree. Entry: [0x00 = separator before] [len + name] [0x00 = separator after]
               [0xFF + value]. Value with the top bit set: a folder, its entries follow, low 31 bits = their
               size + 4. Otherwise: offset of the file's VFS entry. An entry without a value continues the path
               into the next entry. After a valued entry the path goes back to the folder's own path.
  VFS table    per file: span count (1), then per span: offset in file (4), size (4), CFT offset (n bytes)
  CFT          per container file: ekey (9), encoded size (4), [EST offset (m bytes)], content size (4),
               [content key (16)], patch record count (1) + its records
  EST          encoding specs, zero-terminated
n and m are 1-4 bytes, the smallest that can address the CFT and EST tables.
"""
import struct

FOLDER = 0x80000000


def offset_size(table_size):
    if table_size > 0xFFFFFF:
        return 4
    if table_size > 0xFFFF:
        return 3
    if table_size > 0xFF:
        return 2
    return 1


class Entry:
    __slots__ = ("pre", "name", "post", "children", "vfs")

    def __init__(self, pre=False, name=None, post=None, children=None, vfs=None):
        self.pre, self.name, self.post, self.children, self.vfs = pre, name, post, children, vfs

    def has_value(self):
        return self.children is not None or self.vfs is not None


class Manifest:
    def __init__(self, data):
        (magic, self.version, self.header_size, self.ekey_size, self.pkey_size, self.flags, pt_off, pt_size,
         vfs_off, vfs_size, cft_off, cft_size, self.max_depth) = struct.unpack_from(">4sBBBBIIIIIIIH", data, 0)
        if magic != b"TVFS" or self.ekey_size != 9 or self.flags != 7 or self.header_size != 46:
            raise ValueError("TVFS layout not supported")
        est_off, est_size = struct.unpack_from(">II", data, 38)
        self.est = data[est_off:est_off + est_size]
        self.cft = bytearray(data[cft_off:cft_off + cft_size])
        self.vfs = bytearray(data[vfs_off:vfs_off + vfs_size])
        self.layout = (pt_off, vfs_off, cft_off, est_off)
        self.tree = self._parse(data, pt_off, pt_off + pt_size)
        if self.serialize_tree() != data[pt_off:pt_off + pt_size]:
            raise ValueError("path table did not round-trip")

    # --- path table --------------------------------------------------------------------------------------

    def _parse(self, data, at, end):
        out = []
        while at < end:
            e = Entry()
            if data[at] == 0:
                e.pre, at = True, at + 1
            if at < end and data[at] != 0xFF:
                n = data[at]
                e.name, at = data[at + 1:at + 1 + n], at + 1 + n
            if at < end and data[at] == 0:
                e.post, at = "explicit", at + 1
            if at < end:
                if data[at] == 0xFF:
                    value = struct.unpack_from(">I", data, at + 1)[0]
                    at += 5
                    if value & FOLDER:
                        stop = at + (value & ~FOLDER) - 4
                        e.children = self._parse(data, at, stop)
                        at = stop
                    else:
                        e.vfs = value
                elif e.post is None:
                    e.post = "implicit"
            out.append(e)
        return out

    def serialize_tree(self, entries=None):
        entries = self.tree if entries is None else entries
        out = bytearray()
        for e in entries:
            if e.pre:
                out += b"\0"
            if e.name is not None:
                out += bytes([len(e.name)]) + e.name
            if e.post == "explicit":
                out += b"\0"
            if e.children is not None:
                body = self.serialize_tree(e.children)
                out += b"\xff" + struct.pack(">I", FOLDER | (len(body) + 4)) + body
            elif e.vfs is not None:
                out += b"\xff" + struct.pack(">I", e.vfs)
        return bytes(out)

    def files(self, entries=None, prefix=b""):
        """(path, VFS offset) for every file, the path being the names joined without separators."""
        entries = self.tree if entries is None else entries
        path = prefix
        for e in entries:
            if e.name:
                path += e.name
            if e.children is not None:
                yield from self.files(e.children, path)
                path = prefix
            elif e.vfs is not None:
                yield path, e.vfs
                path = prefix

    # --- VFS and CFT -------------------------------------------------------------------------------------

    @property
    def cft_offset_size(self):
        return offset_size(len(self.cft))

    @property
    def est_offset_size(self):
        return offset_size(len(self.est))

    def cft_entry_size(self):
        """Length of an entry without patch records (ekey, esize, EST offset, csize, ckey, patch count 0)."""
        return 9 + 4 + self.est_offset_size + 4 + 16 + 1

    def spans(self, vfs_offset):
        """[(offset in file, size, CFT offset)] of one file."""
        n = self.vfs[vfs_offset]
        width = 8 + self.cft_offset_size
        out = []
        for i in range(n):
            at = vfs_offset + 1 + i * width
            off, size = struct.unpack_from(">II", self.vfs, at)
            out.append((off, size, int.from_bytes(self.vfs[at + 8:at + width], "big")))
        return out

    def container(self, cft_offset):
        """(ekey 9 bytes, encoded size, EST offset, content size, content key) of a CFT entry."""
        e = self.cft[cft_offset:cft_offset + self.cft_entry_size()]
        m = self.est_offset_size
        return (e[:9], struct.unpack_from(">I", e, 9)[0], int.from_bytes(e[13:13 + m], "big"),
                struct.unpack_from(">I", e, 13 + m)[0], e[17 + m:33 + m])

    def est_offset(self, spec):
        spec = spec.encode() + b"\0"
        at = self.est.find(spec)
        while at > 0 and self.est[at - 1] != 0:
            at = self.est.find(spec, at + 1)
        if at < 0:
            raise KeyError("encoding spec %r is not in the manifest" % spec)
        return at

    # --- changes -----------------------------------------------------------------------------------------

    def add_file(self, path, ekey, esize, csize, ckey, spec):
        """Add a one-span file at `path`, splitting a name where the new path branches off."""
        if offset_size(len(self.cft) + self.cft_entry_size()) != self.cft_offset_size:
            raise ValueError("adding a container entry would widen the CFT offsets")
        cft_at = len(self.cft)
        m = self.est_offset_size
        self.cft += (ekey[:9] + struct.pack(">I", esize) + self.est_offset(spec).to_bytes(m, "big")
                     + struct.pack(">I", csize) + ckey + b"\0")  # last byte: no patch records
        vfs_at = len(self.vfs)
        self.vfs += bytes([1]) + struct.pack(">II", 0, csize) + cft_at.to_bytes(self.cft_offset_size, "big")
        self._insert(self.tree, path, vfs_at)

    def _insert(self, entries, rest, vfs_at):
        """Insert `rest` into a folder's entry list, keeping the tree a prefix tree."""
        i = 0
        while i < len(entries):
            # a chain: entries without a value, ending in a valued one, form one path below this folder
            j = i
            while j < len(entries) and not entries[j].has_value():
                j += 1
            chain = entries[i:j + 1]
            names = [e.name or b"" for e in chain]
            joined = b"".join(names)
            if not joined and chain[-1].children is not None:  # an unnamed folder (the top of a sub-manifest)
                return self._insert(chain[-1].children, rest, vfs_at)
            common = 0
            while common < min(len(joined), len(rest)) and joined[common] == rest[common]:
                common += 1
            if common == 0:
                if joined > rest:
                    entries.insert(i, self._leaf(rest, vfs_at))
                    return
                i = j + 1
                continue
            if common == len(joined) and chain[-1].children is not None and len(rest) > common:
                return self._insert(chain[-1].children, rest[common:], vfs_at)
            if common == len(joined):
                raise ValueError("path %r already exists" % rest)
            # split the chain where the new path branches off: the shared part becomes a folder holding the
            # old remainder and the new leaf, in order
            k, at = 0, 0
            while at + len(names[k]) <= common:
                at += len(names[k])
                k += 1
            head, tail_name = names[k][:common - at], names[k][common - at:]
            old_rest = [Entry(name=tail_name, post=chain[k].post, children=chain[k].children,
                              vfs=chain[k].vfs)] + chain[k + 1:]
            new_leaf = self._leaf(rest[common:], vfs_at)
            kids = [new_leaf] + old_rest if rest[common:] < joined[common:] else old_rest + [new_leaf]
            entries[i:j + 1] = chain[:k] + [Entry(pre=chain[k].pre, name=head or None, children=kids)]
            self.max_depth = max(self.max_depth, self.depth())
            return
        entries.append(self._leaf(rest, vfs_at))

    @staticmethod
    def _leaf(name, vfs_at):
        if not name or len(name) > 255:
            raise ValueError("leaf name of %d bytes" % len(name))
        return Entry(name=name, vfs=vfs_at)

    def repoint(self, old_ekey, ekey, esize, csize, ckey):
        """Change the container entry of old_ekey (e.g. a sub-manifest we rewrote) to a new file.

        Entries are found through the files' spans: an entry's length varies with its patch records."""
        hits = {c for _path, v in self.files() for _o, _s, c in self.spans(v) if self.cft[c:c + 9] == old_ekey[:9]}
        if not hits:
            raise KeyError("no container entry for %s" % old_ekey.hex())
        m = self.est_offset_size
        for at in hits:
            self.cft[at:at + 9] = ekey[:9]
            struct.pack_into(">I", self.cft, at + 9, esize)
            struct.pack_into(">I", self.cft, at + 13 + m, csize)
            self.cft[at + 17 + m:at + 33 + m] = ckey

    # --- writing -----------------------------------------------------------------------------------------

    def depth(self, entries=None):
        """Deepest folder nesting of the path table (the header's max depth)."""
        entries = self.tree if entries is None else entries
        return max([1 + self.depth(e.children) for e in entries if e.children is not None] or [0])

    def build(self):
        """The manifest bytes, tables in the same order as Blizzard's file."""
        tables = {"path": self.serialize_tree(), "vfs": bytes(self.vfs), "cft": bytes(self.cft), "est": self.est}
        order = sorted(zip(self.layout, ("path", "vfs", "cft", "est")))
        at, offsets, body = self.header_size, {}, b""
        for _, name in order:
            offsets[name] = at
            body += tables[name]
            at += len(tables[name])
        header = struct.pack(">4sBBBBIIIIIIIHII", b"TVFS", self.version, self.header_size, self.ekey_size,
                             self.pkey_size, self.flags, offsets["path"], len(tables["path"]), offsets["vfs"],
                             len(tables["vfs"]), offsets["cft"], len(tables["cft"]), self.max_depth,
                             offsets["est"], len(tables["est"]))
        return header + body
