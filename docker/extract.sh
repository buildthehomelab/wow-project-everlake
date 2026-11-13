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
#   MMAPS_ONLY=1  only the navigation meshes (mmaps) the bots and MMAP_PATHFINDING=1 need, from the maps and vmaps
#                 already in the data folder (long; no download)
#                 Skipped when data/mmaps already has files, unless MMAPS_FORCE=1.
#   MMAP_THREADS  threads for mmaps_generator (default: every core; fewer on a host that also runs a realm)
#   DBC_ONLY=1    only dbc and gt (mapextractor -e 10), for a client update that changes table contents but no map
#                 files (e.g. 70790 -> 70862); maps, vmaps and mmaps stay as they are
#   MAP_COPIES    server-only maps made from a client map, "<new id>:<source id> ..." (default "3200:230": the Ring of
#                 Law arena, an arena copy of Blackrock Depths; its Map row comes from the hotfixes database, so the
#                 client files have no map 3200). Done after every extract and mmaps run; "" turns it off.
#   MAP_COPIES_ONLY=1  only those copies, from the maps, vmaps and mmaps already in the data folder (seconds)
#
# The CDN always serves the newest build. Check that it is the build the server is pinned to before extracting.
set -euo pipefail

OUT=/opt/trinitycore/data
BIN=/opt/trinitycore/bin
PRODUCT="${CASC_PRODUCT:-wowf}"
REGION="${CASC_REGION:-us}"

# Map, vmap and mmap files are named by map id and hold no id inside (maps/MMMM_XX_YY.map, maps/MMMM.tilelist,
# vmaps/MMMM/MMMM*, mmaps/MMMM.mmap, mmaps/MMMM_XX_YY.mmtile), so a server-only map is the source map's files under the
# new id. An old copy is removed first, so the copy always matches the source as extracted now.
copy_maps() {
    local pair src dst f n
    for pair in ${MAP_COPIES-3200:230}; do
        [[ "$pair" =~ ^([0-9]{1,4}):([0-9]{1,4})$ ]] \
            || { echo "[extract] ERROR: MAP_COPIES entry '$pair' is not <new id>:<source id>"; return 1; }
        dst=$(printf '%04d' "$((10#${BASH_REMATCH[1]}))"); src=$(printf '%04d' "$((10#${BASH_REMATCH[2]}))")
        [ "$dst" != "$src" ] || { echo "[extract] ERROR: MAP_COPIES entry '$pair' copies a map onto itself"; return 1; }
        n=0
        if [ -d "$OUT/maps" ]; then
            rm -f "$OUT/maps/$dst.tilelist" "$OUT/maps/${dst}"_*.map
            for f in "$OUT/maps/$src.tilelist" "$OUT/maps/${src}"_*.map; do
                [ -f "$f" ] || continue
                cp "$f" "$OUT/maps/$dst${f##*/"$src"}"; n=$((n + 1))
            done
        fi
        if [ -d "$OUT/vmaps/$src" ]; then
            rm -rf "${OUT:?}/vmaps/$dst" && mkdir -p "$OUT/vmaps/$dst"
            for f in "$OUT/vmaps/$src"/*; do
                [ -f "$f" ] || continue
                f=${f##*/}
                cp "$OUT/vmaps/$src/$f" "$OUT/vmaps/$dst/${f/#$src/$dst}"; n=$((n + 1))
            done
        fi
        if [ -d "$OUT/mmaps" ]; then
            rm -f "$OUT/mmaps/$dst.mmap" "$OUT/mmaps/${dst}"_*.mmtile
            for f in "$OUT/mmaps/$src.mmap" "$OUT/mmaps/${src}"_*.mmtile; do
                [ -f "$f" ] || continue
                cp "$f" "$OUT/mmaps/$dst${f##*/"$src"}"; n=$((n + 1))
            done
        fi
        if [ "$n" = 0 ]; then
            echo "[extract] WARNING: map $src has no maps, vmaps or mmaps here, so map $dst has none either"
        else
            echo "[extract] map $dst: $n files copied from map $src"
        fi
    done
}

# MAP_COPIES_ONLY=1: only the server-only map copies, from what the data folder already has
if [ "${MAP_COPIES_ONLY:-0}" = 1 ]; then
    echo "[extract] === server-only map copies (MAP_COPIES=${MAP_COPIES-3200:230})"
    copy_maps
    exit 0
fi

# MMAPS_ONLY=1: only the mmaps, from the maps and vmaps already extracted (same call as EXTRACT_MMAPS=1 below)
if [ "${MMAPS_ONLY:-0}" = 1 ]; then
    [ -d "$OUT/maps" ] && [ -d "$OUT/vmaps" ] || { echo "[extract] ERROR: mmaps need maps and vmaps first (run the extractor once without MMAPS_ONLY)"; exit 1; }
    if [ -n "$(ls -A "$OUT/mmaps" 2>/dev/null)" ] && [ "${MMAPS_FORCE:-0}" != 1 ]; then
        echo "[extract] mmaps already there: left as they are (MMAPS_FORCE=1 builds them again)"
        copy_maps; exit 0
    fi
    echo "[extract] === mmaps_generator only (long)"
    cd "$OUT"
    "$BIN/mmaps_generator" --threads "${MMAP_THREADS:-$(nproc)}"
    copy_maps
    echo "[extract] done:"; du -sh "$OUT/mmaps"
    exit 0
fi

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
    # mapextractor skips table files that already exist, so extract into an empty folder and swap it in afterwards
    NEW="$OUT/.dbc-new"
    echo "[extract] === mapextractor, dbc and gt only (DBC_ONLY=1), into $NEW"
    rm -rf "$NEW" && mkdir -p "$NEW"
    rc=0; "$BIN/mapextractor" -i "$SRC" -o "$NEW" -p "$PRODUCT" "${MAP_ARGS[@]}" -e 10 || rc=$?
    # mapextractor exits 1 when it fails, e.g. when it can read nothing from the storage (no locales: wrong product or
    # path); the core at the old pin fdcf518 exited 0 then, so the files are checked as well
    if [ "$rc" != 0 ] || [ -z "$(find "$NEW/dbc" -name '*.db2' -print -quit 2>/dev/null)" ] \
        || [ -z "$(find "$NEW/gt" -type f -print -quit 2>/dev/null)" ]; then
        echo "[extract] ERROR: mapextractor failed (exit $rc) or wrote no dbc or gt files, see the messages above. ./data is unchanged."
        rm -rf "$NEW"; exit 1
    fi
    # old folders aside, new ones in; if a move fails, put the old ones back so dbc and gt stay one build
    rm -rf "$OUT/dbc.old" "$OUT/gt.old"
    if ! { { [ ! -d "$OUT/dbc" ] || mv "$OUT/dbc" "$OUT/dbc.old"; } && { [ ! -d "$OUT/gt" ] || mv "$OUT/gt" "$OUT/gt.old"; } \
           && mv "$NEW/dbc" "$OUT/dbc" && mv "$NEW/gt" "$OUT/gt"; }; then
        echo "[extract] ERROR: could not swap in the new dbc and gt, putting the old ones back."
        for d in dbc gt; do
            if [ -d "$OUT/$d.old" ]; then rm -rf "${OUT:?}/$d"; mv "$OUT/$d.old" "$OUT/$d"; fi
        done
        exit 1
    fi
    rm -rf "$NEW" "$OUT/dbc.old" "$OUT/gt.old"
    echo "[extract] done (restart the worldservers to load the new tables):"
    du -sh "$OUT/dbc" "$OUT/gt" 2>/dev/null
    exit 0
fi
if [ "${SKIP_MAPS:-0}" = 1 ] && [ -d "$OUT/dbc" ] && [ -d "$OUT/maps" ]; then
    echo "[extract] === 1/3 skipped (SKIP_MAPS=1, dbc and maps already there)"
else
    echo "[extract] === 1/3 mapextractor (dbc, gt, cameras, maps)"
    rc=0; "$BIN/mapextractor" -i "$SRC" -o "$OUT" -p "$PRODUCT" "${MAP_ARGS[@]}" || rc=$?
    # mapextractor exits 1 when it fails, e.g. when it can read nothing from the storage (no locales: wrong product or
    # path), and 2 when tiles of Eastern Kingdoms or Kalimdor could not be read (a client that is not complete); the core
    # at the old pin fdcf518 exited 0 in both of these cases
    if [ "$rc" != 0 ]; then
        echo "[extract] ERROR: mapextractor failed (exit $rc), see the messages above. dbc and maps in ./data may be incomplete; vmaps and mmaps were not rebuilt."
        exit "$rc"
    fi
fi
# a run that wrote no dbc or maps; at the old core pin fdcf518, mapextractor exited 0 when it could not open the storage
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
    "$BIN/mmaps_generator" --threads "${MMAP_THREADS:-$(nproc)}"
fi

copy_maps

echo "[extract] done:"
du -sh "$OUT"/* 2>/dev/null
