#!/bin/sh
# Builds the patched client build the cdn service serves (docs/custom-files.md): Blizzard's Forever build plus our
# added files, written into CDN_DIR. Run on the server:
#
#   docker compose run --rm cdn-build
#
# The added files are every files.tsv set under CDN_FILES_DIR (default ./cdn-files): a folder holding files named by
# FileDataID and a files.tsv listing them, as tools/tact/collect.py writes it. With no sets there is nothing to build.
# Every build is content-addressed, so an older build keeps working beside a new one; build.json (what the mini's
# gate2 reads) names the newest. The running cdn service picks it up without a restart.
set -eu

CACHE=/cache
mkdir -p "$CACHE/tact"
# Pin the cache to the build the launcher installs (1.60.1.70938, wow-everlake-launcher internal/pin/wowf.json), never
# whatever Blizzard serves today: the launcher only takes a patched build made on exactly its own pinned build.
# A cache pinned to an earlier build is moved to this one. What it already downloaded stays (CDN files are named by
# their hash), and only the new build's indexes are fetched. Builds already in /cdn stay there too; build.json names
# the newest.
PIN_BUILD=3627b099867bfde3e37a17cf44f69cdc
PIN_VERSION=1.60.1.70938
PIN="$PIN_BUILD
3363ac656da5f261cdc675ab28b2744c
$PIN_VERSION
tpr/wow
level3.blizzard.com us.cdn.blizzard.com"
have_build=$(sed -n 1p "$CACHE/tact/build.txt" 2>/dev/null || true)
if [ "$have_build" != "$PIN_BUILD" ]; then
    if [ -n "$have_build" ]; then
        echo "[cdn-build] the cache was pinned to $(sed -n 3p "$CACHE/tact/build.txt"): moving it to $PIN_VERSION"
    fi
    printf '%s\n' "$PIN" > "$CACHE/tact/build.txt"
fi

# all sets into one folder (a FileDataID in two sets: the later set wins)
ALL=/tmp/files
rm -rf "$ALL"; mkdir -p "$ALL"
for list in $(find /files -name files.tsv 2>/dev/null | sort); do
    dir=$(dirname "$list")
    echo "[cdn-build] files from $dir"
    while IFS="$(printf '\t')" read -r fdid rest; do
        case "$fdid" in ''|*[!0-9]*) continue ;; esac
        cp "$dir/$fdid" "$ALL/$fdid"
        printf '%s\t%s\n' "$fdid" "$rest" >> "$ALL/files.tsv"
    done < "$list"
done
if [ ! -s "$ALL/files.tsv" ]; then
    echo "[cdn-build] no files to add (no files.tsv under CDN_FILES_DIR): nothing built"; exit 0
fi
echo "[cdn-build] patched build into /cdn (the first run downloads Blizzard's indexes, ~320 MB, a few minutes)"
python -I /app/tools/tact/patch.py --cache "$CACHE" --out /cdn --files-from "$ALL/files.tsv"
chown -R "${HOST_UID:-0}:${HOST_GID:-0}" /cdn
echo "[cdn-build] done: $(python -c 'import json; b=json.load(open("/cdn/build.json")); print("build", b["build_key"], "with", len(b["files"]), "files")')"
