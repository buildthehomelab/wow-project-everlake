#!/usr/bin/env bash
# The revision of the files this repository itself puts into the server image: the Dockerfile and everything it
# COPYs from this folder (docker/patches, the entrypoint and extract scripts, the sql/everlake files it names).
#
#   tools/ci/image-rev.sh           prints it (8 hex characters)
#   tools/ci/image-rev.sh --write   also writes it into docker-compose.ptr.yml
#
# Why: the PTR image's tag used to name only the core commit and the world data commit. A change to one of these
# files then built nothing: the tag already existed, so the PTR started the old image at once (the realm build
# change of 2026-11-14 never reached it). The revision is the tag's third part, so such a change makes a new tag and
# the PTR builds it on its next start. Docker's layer cache keeps that build short while the core commit is the same.
# tools/ci/check-repo.sh (CI) fails when docker-compose.ptr.yml does not carry the current revision.
set -euo pipefail
cd "$(dirname "$0")/../.."
export LC_ALL=C

# Sources of every COPY that takes files from this folder (not from another build stage), continuation lines joined
sources() {
    sed -e ':a' -e '/\\$/N; s/\\\n/ /; ta' Dockerfile | awk '
        $1 == "COPY" {
            from = 0
            for (i = 2; i <= NF; i++) if ($i ~ /^--from=/) from = 1
            if (from) next
            for (i = 2; i < NF; i++) if ($i !~ /^--/) print $i
        }'
}

files() {
    echo Dockerfile
    local s
    while read -r s; do
        s="${s%/}"
        if [ -d "$s" ]; then
            find "$s" -type f
        elif [ -f "$s" ]; then
            echo "$s"
        else
            echo "image-rev: the Dockerfile copies $s, which does not exist" >&2
            exit 1
        fi
    done < <(sources)
}

list="$(files | sort -u)"
rev="$(while read -r f; do printf '%s %s\n' "$f" "$(git hash-object --no-filters -- "$f")"; done <<<"$list" \
        | git hash-object --stdin | cut -c1-8)"

if [ "${1:-}" = --write ]; then
    # the three tags (ptr-<core>-<world data>-<revision>) and the build argument
    sed -i.tmp -E \
        -e "s/(ptr-\\$\\{PTR_TC_COMMIT:-[0-9a-f]{40}\\}-\\$\\{PTR_WORLD_DATA_COMMIT:-[0-9a-f]{40}\\})(-[0-9a-f]{8})?/\\1-$rev/" \
        -e "s/^( *IMAGE_REV: )\"[0-9a-f]{8}\"/\\1\"$rev\"/" docker-compose.ptr.yml
    rm -f docker-compose.ptr.yml.tmp
fi
if [ "${1:-}" = --files ]; then
    echo "$list"
fi
echo "$rev"
