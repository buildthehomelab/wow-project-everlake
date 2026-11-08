#!/usr/bin/env bash
# Do docker/patches still apply to a TrinityCore commit? Same order and rules as the Dockerfile.
#   tools/ci/check-patches.sh                 the core pinned in the Dockerfile
#   tools/ci/check-patches.sh <commit> [repo] another commit, e.g. the forever-bots core
# Fetches one commit (depth 1, a few hundred MB) into $TC_DIR (default: a temporary folder).
set -eu
here="$(cd "$(dirname "$0")/../.." && pwd)"
commit="${1:-$(sed -nE 's/^ARG TC_COMMIT=([0-9a-f]{40})$/\1/p' "$here/Dockerfile")}"
repo="${2:-$(sed -nE 's/^ARG TC_REPO=(.+)$/\1/p' "$here/Dockerfile")}"
dir="${TC_DIR:-$(mktemp -d)}"

echo "fetching $repo @ $commit"
git init -q "$dir"
git -C "$dir" remote add origin "$repo" 2>/dev/null || git -C "$dir" remote set-url origin "$repo"
git -C "$dir" fetch -q --depth 1 origin "$commit"
git -C "$dir" checkout -q --force FETCH_HEAD
git -C "$dir" clean -qfd

fail=0
apply() {
    if git -C "$dir" apply "$1"; then echo "ok    ${1#"$here"/}"; else echo "FAIL  ${1#"$here"/}"; fail=1; fi
}
for p in "$here"/docker/patches/*.patch; do [ -e "$p" ] && apply "$p"; done
if [ -d "$dir/src/modules/PlayerbotV2" ]; then
    for p in "$here"/docker/patches/playerbot/*.patch; do [ -e "$p" ] && apply "$p"; done
else
    echo "no PlayerbotV2 in this core: docker/patches/playerbot skipped (as in the Dockerfile)"
fi
git -C "$dir" checkout -q --force FETCH_HEAD && git -C "$dir" clean -qfd
exit $fail
