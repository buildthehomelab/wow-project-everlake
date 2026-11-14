#!/bin/sh
# Builds the patched client build the cdn service serves (docs/custom-files.md): Blizzard's Forever build plus our
# added files, written into CDN_DIR. Run on the server:
#
#   docker compose run --rm cdn-build
#
# The added files are every files.tsv set under CDN_FILES_DIR (default ./cdn-files): a folder holding files named by
# FileDataID and a files.tsv listing them, as tools/tact/collect.py writes it. With no sets there is nothing to build.
# Every build is content-addressed, so an older build keeps working beside a new one; build.json (what the mini's
# gate2 and the launcher read) names the newest. The running cdn service picks it up without a restart.
# With no file sets but a build already in CDN_DIR (made elsewhere and copied in), that build is made again on the
# pinned Blizzard build from its own files: this is how it follows the launcher to a new game build.
set -eu

CACHE=/cache
mkdir -p "$CACHE/tact"
# Pin the cache to the build the launcher installs (tools/tact/pin.txt, the same file the Mac client's overlay
# command reads), never whatever Blizzard serves today: the launcher only takes a patched build made on exactly its
# own pinned build. A cache pinned to an earlier build is moved to this one. What it already downloaded stays (CDN
# files are named by their hash), and only the new build's indexes are fetched. Builds already in /cdn stay there
# too; build.json names the newest.
PIN_FILE=/app/tools/tact/pin.txt
PIN_BUILD=$(sed -n 1p "$PIN_FILE")
PIN_VERSION=$(sed -n 3p "$PIN_FILE")
[ -n "$PIN_BUILD" ] && [ -n "$PIN_VERSION" ] || { echo "[cdn-build] $PIN_FILE names no build" >&2; exit 1; }
have_build=$(sed -n 1p "$CACHE/tact/build.txt" 2>/dev/null || true)
if [ "$have_build" != "$PIN_BUILD" ]; then
    if [ -n "$have_build" ]; then
        echo "[cdn-build] the cache was pinned to $(sed -n 3p "$CACHE/tact/build.txt"): moving it to $PIN_VERSION"
    fi
    sed -n 1,5p "$PIN_FILE" > "$CACHE/tact/build.txt"
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
    # No file sets here: a build made somewhere else was copied into CDN_DIR as it is (its build.json and its files).
    # Our files are all in that folder, so it is made again on the pinned build from itself.
    if [ ! -f /cdn/build.json ]; then
        echo "[cdn-build] no files to add (no files.tsv under CDN_FILES_DIR) and no earlier build in CDN_DIR: nothing built"
        exit 0
    fi
    made_on=$(python -c 'import json; b=json.load(open("/cdn/build.json")); print(b.get("blizzard_build_key", ""), b.get("version", "?"))')
    if [ "${made_on%% *}" = "$PIN_BUILD" ]; then
        echo "[cdn-build] no file sets under CDN_FILES_DIR, and the build in CDN_DIR is already made on $PIN_VERSION: nothing to do"
        exit 0
    fi
    echo "[cdn-build] no file sets under CDN_FILES_DIR: making the build in CDN_DIR (made on ${made_on#* }) again on $PIN_VERSION, from its own files"
    echo "[cdn-build] (the first run on a new build downloads Blizzard's indexes, ~320 MB, a few minutes)"
    python -I /app/tools/tact/patch.py --cache "$CACHE" --out /cdn --files-from-build /cdn
    chown -R "${HOST_UID:-0}:${HOST_GID:-0}" /cdn
    echo "[cdn-build] done: $(python -c 'import json; b=json.load(open("/cdn/build.json")); print("build", b["build_key"], "on", b["version"], "with", len(b["files"]), "files")')"
    exit 0
fi
echo "[cdn-build] patched build into /cdn (the first run downloads Blizzard's indexes, ~320 MB, a few minutes)"
python -I /app/tools/tact/patch.py --cache "$CACHE" --out /cdn --files-from "$ALL/files.tsv"
chown -R "${HOST_UID:-0}:${HOST_GID:-0}" /cdn
echo "[cdn-build] done: $(python -c 'import json; b=json.load(open("/cdn/build.json")); print("build", b["build_key"], "with", len(b["files"]), "files")')"
