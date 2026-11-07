#!/bin/bash
# Extracts maps, vmaps and mmaps for maps that are NOT in the client build's Map.db2 (the client gets them by hotfix),
# such as map 530 on the Forever client. Runs in the everlake-extractors image (docker/extractors.Dockerfile), whose
# extractors carry docker/patches/0010-extractors-loose-files-extra-maps.patch. Start it with
# scripts/extract-extra-map.sh, which also copies the result into data/.
#
#   EXTRA_MAPS   "id:wdtFileDataID:Directory[:parentMapId]" entries, comma separated (e.g. 530:828395:Expansion01)
#   CASC_PRODUCT wowf by default: everything not in /loose (models, liquid tables) comes from this build
#   CASC_REGION  us by default
#   THREADS      nproc by default
#
# Mounts:
#   /loose  read only: the files the client has that the build lacks, named by FileDataID (the WDT and ADTs)
#   /data   read only: the server's data/ (mmaps_generator reads dbc/<locale>/Map.db2 and LiquidType.db2 from it)
#   /out    empty: maps/, vmaps/, mmaps/ for the extra maps (+ the vmap models they use) end up here
#   /cache  the CASC download cache (the extractor service's casc-cache volume)
set -euo pipefail

BIN=/opt/trinitycore/bin
PRODUCT="${CASC_PRODUCT:-wowf}"
REGION="${CASC_REGION:-us}"
THREADS="${THREADS:-$(nproc)}"
OUT=/out

[ -n "${EXTRA_MAPS:-}" ] || { echo "[extra-map] ERROR: EXTRA_MAPS is empty"; exit 1; }
[ -d /loose ] && [ -n "$(ls -A /loose)" ] || { echo "[extra-map] ERROR: /loose is empty"; exit 1; }
[ -d /data/dbc ] || { echo "[extra-map] ERROR: /data/dbc missing (mount the server's data/)"; exit 1; }
[ -d "$OUT" ] && [ -z "$(ls -A "$OUT")" ] || { echo "[extra-map] ERROR: $OUT must be an empty directory"; exit 1; }

# the patched extractors read these (see the patch)
export EXTRACTOR_EXTRA_MAPS="$EXTRA_MAPS"
export EXTRACTOR_ONLY_MAPS
EXTRACTOR_ONLY_MAPS="$(echo "$EXTRA_MAPS" | tr ',' '\n' | cut -d: -f1 | paste -sd, -)"
export EXTRACTOR_LOOSE_FILES=/loose
MAP_IDS="$EXTRACTOR_ONLY_MAPS"

echo "[extra-map] maps $MAP_IDS from WDT/ADT files in /loose, everything else from product $PRODUCT ($REGION), cache /cache"
mkdir -p /cache

echo "[extra-map] === 1/4 mapextractor (maps only)"
cd "$OUT"
"$BIN/mapextractor" -i /cache -o "$OUT" -p "$PRODUCT" -c 1 -r "$REGION" -e 1
ls "$OUT"/maps/*.map >/dev/null 2>&1 || { echo "[extra-map] ERROR: no .map files written"; exit 1; }

echo "[extra-map] === 2/4 vmap4extractor"
mkdir -p "$OUT/.work" && cd "$OUT/.work"
"$BIN/vmap4extractor" -d /cache -p "$PRODUCT" -c -r "$REGION"

echo "[extra-map] === 3/4 vmap4assembler"
mkdir -p "$OUT/vmaps"
"$BIN/vmap4assembler" Buildings "$OUT/vmaps"
cd "$OUT" && rm -rf "$OUT/.work"
# GameObject models are not map data: the server's data/vmaps already has them
rm -f "$OUT/vmaps/GameObjectModels.dtree"

echo "[extra-map] === 4/4 mmaps_generator"
# it reads dbc/<locale>/Map.db2 + LiquidType.db2, and refuses to start without vmaps/0000/*.vmtree (a sanity check
# only): both are linked in from the server's data, read only, and removed again
ln -s /data/dbc "$OUT/dbc"
[ -e "$OUT/vmaps/0000" ] || ln -s /data/vmaps/0000 "$OUT/vmaps/0000"
for id in ${MAP_IDS//,/ }; do
    "$BIN/mmaps_generator" "$id" --input "$OUT" --output "$OUT" --threads "$THREADS"
done
rm "$OUT/dbc"
[ -L "$OUT/vmaps/0000" ] && rm "$OUT/vmaps/0000"
ls "$OUT"/mmaps/*.mmtile >/dev/null 2>&1 || { echo "[extra-map] ERROR: no .mmtile files written"; exit 1; }

echo "[extra-map] done:"
for id in ${MAP_IDS//,/ }; do
    printf '  map %s: %s .map, %s vmtile, %s mmtile\n' "$id" \
        "$(ls "$OUT"/maps/"$(printf %04d "$id")"_*.map 2>/dev/null | wc -l)" \
        "$(ls "$OUT"/vmaps/"$(printf %04d "$id")"/*.vmtile 2>/dev/null | wc -l)" \
        "$(ls "$OUT"/mmaps/"$(printf %04d "$id")"_*.mmtile 2>/dev/null | wc -l)"
done
