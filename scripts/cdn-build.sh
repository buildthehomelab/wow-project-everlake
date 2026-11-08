#!/bin/sh
# Builds the patched client build the cdn service serves (docs/custom-files.md, docs/china-undead.md):
# Blizzard's Forever build plus our added files, written into CDN_DIR. Run on the server:
#
#   docker compose run --rm cdn-build
#
# Every build is content-addressed, so an older build keeps working beside a new one; build.json (what the
# mini's gate2 reads) names the newest. The running cdn service picks it up without a restart.
# Today's files: the China Undead bodies (tools/looks/china_undead.py).
set -eu

CACHE=/cache
mkdir -p "$CACHE/tact"
# Pin the cache to the build the core and the client run (1.60.1.70790), never whatever Blizzard serves today.
PIN="9006ba6948388dd0d4a0578e64b8a92e
0e139f0e95542dbe2a5462d8a6b2ebae
1.60.1.70790
tpr/wow
level3.blizzard.com us.cdn.blizzard.com"
[ -f "$CACHE/tact/build.txt" ] || printf '%s\n' "$PIN" > "$CACHE/tact/build.txt"
if [ "$(sed -n 3p "$CACHE/tact/build.txt")" != 1.60.1.70790 ]; then
    echo "[cdn-build] the cache is pinned to $(sed -n 3p "$CACHE/tact/build.txt"), not 1.60.1.70790" >&2; exit 1
fi

FILES=/tmp/files
rm -rf "$FILES"
echo "[cdn-build] China Undead files (the first run downloads Blizzard's indexes, ~320 MB, a few minutes)"
python -I /app/tools/looks/china_undead.py --cache "$CACHE" --out "$FILES"
echo "[cdn-build] patched build into /cdn"
python -I /app/tools/tact/patch.py --cache "$CACHE" --out /cdn --files-from "$FILES/files.tsv"
chown -R "${HOST_UID:-0}:${HOST_GID:-0}" /cdn
echo "[cdn-build] done: $(python -c 'import json; b=json.load(open("/cdn/build.json")); print("build", b["build_key"], "with", len(b["files"]), "files")')"
