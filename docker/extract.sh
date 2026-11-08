#!/bin/bash
# Extracts the server's game data (dbc, gt, cameras, maps, vmaps and optionally mmaps) into /opt/trinitycore/data.
#
# Two sources:
#   CASC_REMOTE=1 (default): straight from Blizzard's CDN, no installed client needed. Downloaded files are kept in
#                            /cache (CascCache inside it), so a second run is fast.
#   CASC_REMOTE=0:           from an installed client mounted at /wow (the folder with .build.info and Data).
#
#   CASC_PRODUCT  wowf (WoW Forever) by default
#   CASC_REGION   us by default
#   EXTRACT_MMAPS=1 also generates mmaps (long; only needed with MMAP_PATHFINDING=1)
#   DBC_ONLY=1    only dbc and gt (mapextractor -e 10), for a client update that changes table contents but no map
#                 files (e.g. 70790 -> 70862); maps, vmaps and mmaps stay as they are
#
# The CDN always serves the newest build. Check that it is the build the server is pinned to before extracting.
set -euo pipefail

OUT=/opt/trinitycore/data
BIN=/opt/trinitycore/bin
PRODUCT="${CASC_PRODUCT:-wowf}"
REGION="${CASC_REGION:-us}"

if [ "${CASC_REMOTE:-1}" = 1 ]; then
    SRC=/cache
    mkdir -p "$SRC"
    MAP_ARGS=(-c 1 -r "$REGION")
    VMAP_ARGS=(-c -r "$REGION")
    echo "[extract] source: Blizzard CDN, product $PRODUCT, region $REGION, cache $SRC"
else
    SRC=/wow
    MAP_ARGS=()
    VMAP_ARGS=()
    if [ ! -f "$SRC/.build.info" ] || [ ! -d "$SRC/Data" ]; then
        echo "[extract] ERROR: $SRC must be the 'World of Warcraft' folder (with .build.info and Data). Check WOW_DIR in .env."
        exit 1
    fi
    echo "[extract] source: installed client at $SRC, product $PRODUCT"
fi

cd "$OUT"
if [ "${DBC_ONLY:-0}" = 1 ]; then
    echo "[extract] === mapextractor, dbc and gt only (DBC_ONLY=1)"
    mark="$(mktemp)"
    "$BIN/mapextractor" -i "$SRC" -o "$OUT" -p "$PRODUCT" "${MAP_ARGS[@]}" -e 10
    # mapextractor exits 0 even when it cannot open the CASC storage: check that it wrote new tables
    if [ -z "$(find "$OUT/dbc" -name '*.db2' -newer "$mark" -print -quit 2>/dev/null)" ]; then
        echo "[extract] ERROR: mapextractor wrote no dbc files, see the messages above."; exit 1
    fi
    rm -f "$mark"
    echo "[extract] done:"
    du -sh "$OUT/dbc" "$OUT/gt" 2>/dev/null
    exit 0
fi
if [ "${SKIP_MAPS:-0}" = 1 ] && [ -d "$OUT/dbc" ] && [ -d "$OUT/maps" ]; then
    echo "[extract] === 1/3 skipped (SKIP_MAPS=1, dbc and maps already there)"
else
    echo "[extract] === 1/3 mapextractor (dbc, gt, cameras, maps)"
    "$BIN/mapextractor" -i "$SRC" -o "$OUT" -p "$PRODUCT" "${MAP_ARGS[@]}"
fi
# mapextractor exits 0 even when it cannot open the CASC storage
if [ ! -d "$OUT/dbc" ] || [ ! -d "$OUT/maps" ]; then
    echo "[extract] ERROR: mapextractor produced no dbc/maps, see the messages above."
    exit 1
fi

echo "[extract] === 2/3 vmap4extractor"
rm -rf "$OUT/.work" && mkdir -p "$OUT/.work" && cd "$OUT/.work"
"$BIN/vmap4extractor" -d "$SRC" -p "$PRODUCT" "${VMAP_ARGS[@]}"

echo "[extract] === 3/3 vmap4assembler"
rm -rf "$OUT/vmaps" && mkdir -p "$OUT/vmaps"
"$BIN/vmap4assembler" Buildings "$OUT/vmaps"
[ -f "$OUT/vmaps/GameObjectModels.dtree" ] || { echo "[extract] ERROR: vmaps incomplete (no GameObjectModels.dtree)"; exit 1; }
cd "$OUT" && rm -rf "$OUT/.work"

if [ "${EXTRACT_MMAPS:-0}" = 1 ]; then
    echo "[extract] === mmaps_generator (long)"
    "$BIN/mmaps_generator" --threads "$(nproc)"
fi

echo "[extract] done:"
du -sh "$OUT"/* 2>/dev/null
