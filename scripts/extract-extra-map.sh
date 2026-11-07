#!/bin/bash
# Server terrain (maps, vmaps, mmaps) for a map the client only gets by hotfix, such as 530 (Outland/Quel'Thalas) on
# the Forever client. The stock extractors only see maps in the build's Map.db2; the patched ones
# (docker/patches/0010-extractors-loose-files-extra-maps.patch) also take:
#   - extra maps from EXTRACTOR_EXTRA_MAPS (map id + WDT FileDataID + directory)
#   - files the build lacks (the WDT and ADTs) from a directory of FileDataID-named files, EXTRACTOR_LOOSE_FILES
# Everything else (buildings, doodads, liquid tables) still comes from the client's own build on Blizzard's CDN, so
# the server sees exactly the files the client draws.
#
# Usage (from the repo root, the stack's folder):
#   scripts/extract-extra-map.sh <loose-files-dir> <id:wdtFileDataID:Directory>[,...]
#   e.g. scripts/extract-extra-map.sh ~/Code/Wow/evermore2-spike/gate2/exp2d-files 530:828395:Expansion01
#
# Env: DATA_DIR (default ./data), CASC_PRODUCT (wowf), CASC_REGION (us), REBUILD=1 rebuilds the extractor image,
#      INSTALL=0 only extracts (result stays in $DATA_DIR/.extra-map-out).
#
# It ADDS files to DATA_DIR: maps/NNNN_*, maps/NNNN.tilelist, vmaps/NNNN/, mmaps/NNNN*, and vmap models (*.vmo)
# that are not there yet (existing models are never replaced). Any NNNN file already there is moved to
# $DATA_DIR/.backup-<time>/ first. Restart the worldserver afterwards.
set -euo pipefail

cd "$(dirname "$0")/.."
LOOSE="${1:?usage: $0 <loose-files-dir> <id:wdtFileDataID:Directory>[,...]}"
EXTRA_MAPS="${2:?usage: $0 <loose-files-dir> <id:wdtFileDataID:Directory>[,...]}"
LOOSE="$(cd "$LOOSE" && pwd)"
DATA="$(cd "${DATA_DIR:-./data}" && pwd)"
IMAGE=everlake-extractors:latest
OUT="$DATA/.extra-map-out"

[ -d "$DATA/dbc" ] && [ -d "$DATA/maps" ] || { echo "ERROR: $DATA has no dbc/ or maps/: run the normal extractor first"; exit 1; }

if [ "${REBUILD:-0}" = 1 ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "== building $IMAGE (tools only)"
    docker build -f docker/extractors.Dockerfile -t "$IMAGE" .
fi

rm -rf "$OUT" && mkdir -p "$OUT"
echo "== extracting $EXTRA_MAPS"
docker run --rm \
    -e EXTRA_MAPS="$EXTRA_MAPS" \
    -e CASC_PRODUCT="${CASC_PRODUCT:-wowf}" \
    -e CASC_REGION="${CASC_REGION:-us}" \
    -v "$LOOSE":/loose:ro \
    -v "$DATA":/data:ro \
    -v "$OUT":/out \
    -v everlake_casc-cache:/cache \
    -v "$PWD/docker/extract-extra-map.sh":/usr/local/bin/extract-extra-map.sh:ro \
    "$IMAGE"

[ "${INSTALL:-1}" = 1 ] || { echo "== INSTALL=0: result in $OUT"; exit 0; }

BACKUP="$DATA/.backup-$(date +%Y%m%d-%H%M%S)"
backup() { # move an existing target out of the way, keeping its path under data/
    local rel="$1"
    [ -e "$DATA/$rel" ] || return 0
    mkdir -p "$BACKUP/$(dirname "$rel")"
    mv "$DATA/$rel" "$BACKUP/$rel"
}

for id in $(echo "$EXTRA_MAPS" | tr ',' '\n' | cut -d: -f1); do
    n=$(printf %04d "$id")
    echo "== installing map $id"
    for f in "$OUT"/maps/"$n"_* "$OUT"/maps/"$n".tilelist "$OUT"/mmaps/"$n".mmap "$OUT"/mmaps/"$n"_*.mmtile; do
        [ -e "$f" ] || continue
        rel="${f#"$OUT"/}"
        backup "$rel"
        cp "$f" "$DATA/$rel"
    done
    if [ -d "$OUT/vmaps/$n" ]; then
        backup "vmaps/$n"
        cp -R "$OUT/vmaps/$n" "$DATA/vmaps/$n"
    fi
done
added=0
for f in "$OUT"/vmaps/*.vmo; do
    [ -e "$f" ] || continue
    [ -e "$DATA/vmaps/$(basename "$f")" ] && continue
    cp "$f" "$DATA/vmaps/" && added=$((added + 1))
done
echo "== $added new vmap models added"
[ -d "$BACKUP" ] && echo "== replaced files saved in $BACKUP"
echo "== done; restart the worldserver to load them"
