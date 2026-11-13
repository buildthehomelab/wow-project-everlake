#!/bin/bash
# The world build's inputs, step 1 of 2 (docker-compose.tracker.yml, service tracker-world-copy; runs on every start of
# the tracker app). It runs inside the realm's own image, so what it copies is what that image was built from and what
# its worldserver applies: nothing is downloaded again and nothing can differ.
#
# Copies into /world/incoming (the tracker app's tracker-world volume):
#   TDB_full_world_*.sql          the release dump the worldserver's first start imports
#   core/sql/updates/world        the core's update files
#   core/sql/custom/world         the image's custom files: the core's own, this repository's and the world data's,
#                                 still together (scripts/tracker-world-sort.py tells them apart)
#   image-build.env               the core and world-data commits the image was built from
#
# It starts by removing /world/current, the set of the start before: only step 2 puts a set there, so whatever stops
# either step, no set of another image is left to replay by mistake. A problem is said and ends with exit 0: the
# website does not depend on these files.
set -euo pipefail

out=/world/incoming
sql=/src/TrinityCore/sql
say() { echo "[tracker-world] $*"; }
problem="the copy stopped early"
copied=0
finish() {
    if [ "$copied" != 1 ]; then
        say "WARNING: $problem: no replay inputs from this image"
        rm -rf "$out" || true
    fi
    exit 0
}
trap finish EXIT
give_up() { problem="$*"; exit 0; }

rm -rf /world/current /world/old "$out"
shopt -s nullglob
dumps=(/opt/trinitycore/bin/TDB_full_world_*.sql)
shopt -u nullglob
[ "${#dumps[@]}" = 1 ] || give_up "expected one /opt/trinitycore/bin/TDB_full_world_*.sql, found ${#dumps[@]}"
[ -d "$sql/updates/world" ] && [ -d "$sql/custom/world" ] || give_up "no $sql/updates/world and $sql/custom/world"
[ -f /opt/trinitycore/image-build.env ] || give_up "no /opt/trinitycore/image-build.env"

mkdir -p "$out/core/sql/updates" "$out/core/sql/custom"
cp -r "$sql/updates/world" "$out/core/sql/updates/world"
cp -r "$sql/custom/world" "$out/core/sql/custom/world"
cp "${dumps[0]}" /opt/trinitycore/image-build.env "$out/"
chmod -R a+rX "$out"
copied=1
say "copied $(basename "${dumps[0]}"), $(find "$out/core/sql/updates/world" -name '*.sql' | wc -l | tr -d ' ') update files and" \
    "$(find "$out/core/sql/custom/world" -name '*.sql' | wc -l | tr -d ' ') custom files ($(tr '\n' ' ' < "$out/image-build.env"))"
