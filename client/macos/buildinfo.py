#!/usr/bin/env python3
"""Points one product's row of a .build.info at a patched build and our CDN (gate 2).

    buildinfo.py <.build.info> <product> <build key> <CDN key> <CDN host>

.build.info sits next to the game's Data folder. It is a pipe-separated table whose header names each column
with its type ("Build Key!HEX:16"). The row of <product> (wowf for Forever) gets the new build and CDN keys, and
its CDN hosts and servers become <CDN host> only, so every download goes through our CDN. Other rows and
columns are left as they are. Prints the row before and after.
"""
import sys


def main():
    if len(sys.argv) != 6:
        sys.exit(__doc__)
    path, product, build_key, cdn_key, host = sys.argv[1:]
    raw = open(path, "rb").read().decode()
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.split(newline)
    names = [h.split("!")[0] for h in lines[0].split("|")]
    for need in ("Product", "Build Key", "CDN Key", "CDN Hosts", "CDN Servers"):
        if need not in names:
            sys.exit("%s has no %r column (columns: %s)" % (path, need, ", ".join(names)))
    changed = 0
    for i, line in enumerate(lines[1:], 1):
        if not line or line.startswith("#"):
            continue
        cells = line.split("|")
        row = dict(zip(names, cells))
        if row.get("Product") != product:
            continue
        print("before: " + "  ".join("%s=%s" % (k, row[k]) for k in ("Build Key", "CDN Key", "CDN Hosts",
                                                                       "CDN Servers", "Version")
                                     if k in row))
        row.update({"Build Key": build_key, "CDN Key": cdn_key, "CDN Hosts": host,
                    "CDN Servers": "http://%s/?maxhosts=4" % host})
        lines[i] = "|".join(row[n] for n in names)
        print("after:  " + "  ".join("%s=%s" % (k, row[k]) for k in ("Build Key", "CDN Key", "CDN Hosts",
                                                                       "CDN Servers", "Version")
                                     if k in row))
        changed += 1
    if changed != 1:
        sys.exit("expected one %s row in %s, found %d" % (product, path, changed))
    open(path, "wb").write(newline.join(lines).encode())


if __name__ == "__main__":
    main()
