#!/bin/bash
# Which image the live realm runs, without editing .env. The everlake app runs everlake-trinitycore:live (realm 1, the
# login server, the extractor); the PTR app builds and runs ptr-<core commit>-<world data commit>. Promoting points the
# `live` tag at the image the PTR ran and keeps the one before as `live-previous`; restart the everlake app afterwards
# (TrueNAS Apps UI). Nothing is rebuilt or deleted; tags only move. Realm 2 keeps REALM2_IMAGE_TAG.
#
#   sudo scripts/promote.sh            the image of the PTR's worldserver container (running or stopped) becomes `live`
#   sudo scripts/promote.sh <tag>      everlake-trinitycore:<tag> becomes `live` (for example a ptr-... tag)
#   sudo scripts/promote.sh rollback   `live` and `live-previous` swap (run again to undo the rollback)
#   sudo scripts/promote.sh status     what `live`, `live-previous` and the PTR run, and what each was built from
#
# First use: when `live` does not exist yet, the image live's worldserver is running now is kept as `live-previous`,
# and an EVERLAKE_IMAGE_TAG line in .env (which would override the `live` tag) is commented out, with a dated backup.
set -euo pipefail

REPO=everlake-trinitycore
HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${ENV_FILE:-$HERE/../.env}"
DOCKER="${DOCKER:-docker}"

die() { echo "promote: $*" >&2; exit 1; }

image_id() { $DOCKER image inspect --format '{{.Id}}' "$1" 2>/dev/null || true; }

# The image of a compose service's container: a running one first, else the newest stopped one. Service names are
# unique across this folder's compose files (worldserver = the live realm, worldserver-ptr = the PTR, worldserver2 =
# realm 2), so no project name is needed.
service_image() {
    local filter=(--filter "label=com.docker.compose.service=$1") c
    c="$($DOCKER ps "${filter[@]}" --format '{{.ID}}' | head -1)"
    [ -n "$c" ] || c="$($DOCKER ps -a "${filter[@]}" --format '{{.ID}}' | head -1)"
    [ -n "$c" ] && $DOCKER inspect --format '{{.Image}}' "$c" 2>/dev/null || true
}

# What an image was built from (/opt/trinitycore/image-build.env, written by the Dockerfile), on one line
built_from() {
    local info
    info="$($DOCKER run --rm --entrypoint cat "$1" /opt/trinitycore/image-build.env 2>/dev/null || true)"
    [ -n "$info" ] || { echo "(no image-build.env: built before it existed)"; return; }
    local core wd bots
    core="$(sed -n 's/^TC_COMMIT=//p' <<<"$info")"; wd="$(sed -n 's/^WORLD_DATA_COMMIT=//p' <<<"$info")"
    bots="$(sed -n 's/^PLAYERBOTS=//p' <<<"$info")"
    local wds=none
    [ -z "$wd" ] || wds="${wd:0:10}"
    echo "core ${core:0:10}, world data $wds, bots ${bots:-?}"
}

describe() {  # <label> <image ref or id>
    local id
    id="$(image_id "$2")"
    if [ -z "$id" ]; then printf '  %-14s none\n' "$1"; return; fi
    local tags
    tags="$($DOCKER image inspect --format '{{join .RepoTags " "}}' "$id" 2>/dev/null)"
    printf '  %-14s %s  [%s]\n' "$1" "${id:7:12}" "$tags"
    printf '  %-14s %s\n' "" "$(built_from "$id")"
}

env_override() { [ -f "$ENV_FILE" ] && sed -n 's/^EVERLAKE_IMAGE_TAG=\(..*\)$/\1/p' "$ENV_FILE" | tail -1 || true; }

# An EVERLAKE_IMAGE_TAG line in .env wins over the `live` default of docker-compose.yml: comment it out once.
retire_env_override() {
    local value
    value="$(env_override)"
    [ -n "$value" ] || return 0
    [ "$value" = live ] && return 0
    local backup
    backup="$ENV_FILE.bak-$(date +%Y%m%d-%H%M%S)"
    cp -p "$ENV_FILE" "$backup"
    sed -i.tmp "s|^EVERLAKE_IMAGE_TAG=.*|# EVERLAKE_IMAGE_TAG=$value  (replaced by the live tag, scripts/promote.sh $(date +%F))|" "$ENV_FILE"
    rm -f "$ENV_FILE.tmp"
    echo "promote: .env set EVERLAKE_IMAGE_TAG=$value, which would override the live tag: commented out (backup $backup)"
}

status() {
    echo "live realm (everlake app):"
    describe live "$REPO:live"
    describe live-previous "$REPO:live-previous"
    local running ptr
    running="$(service_image worldserver)"
    if [ -n "$running" ]; then describe "running now" "$running"; else printf '  %-14s %s\n' "running now" "no worldserver container"; fi
    echo "PTR (everlake-ptr app):"
    ptr="$(service_image worldserver-ptr)"
    if [ -n "$ptr" ]; then describe "ran" "$ptr"; else printf '  %-14s %s\n' "ran" "no worldserver-ptr container"; fi
    local override
    override="$(env_override)"
    [ -z "$override" ] || [ "$override" = live ] || echo "NOTE: .env sets EVERLAKE_IMAGE_TAG=$override, so the everlake app runs that, not live (promote retires it)."
}

promote() {
    local source=$1 source_id live_id
    source_id="$(image_id "$source")"
    [ -n "$source_id" ] || die "no image $source"
    $DOCKER run --rm --entrypoint test "$source_id" -f /opt/trinitycore/etc/worldserver.conf.d/playerbot.conf.dist \
        || die "$source has no bots (built without PLAYERBOTS=1): not promoting it"
    live_id="$(image_id "$REPO:live")"
    if [ "$live_id" = "$source_id" ]; then
        echo "promote: $REPO:live is already that image ($(built_from "$source_id"))."
        retire_env_override
        return 0
    fi
    if [ -n "$live_id" ]; then
        $DOCKER tag "$REPO:live" "$REPO:live-previous"
    else
        # first use: keep what live runs now as the way back
        local running
        running="$(service_image worldserver)"
        if [ -n "$running" ]; then $DOCKER tag "$running" "$REPO:live-previous"; echo "promote: first use, the image live runs now is kept as live-previous"; fi
    fi
    $DOCKER tag "$source_id" "$REPO:live"
    retire_env_override
    echo "promote: $REPO:live is now $(built_from "$source_id")"
    status
    echo
    echo "Now restart the everlake app in the TrueNAS Apps UI. Way back: sudo scripts/promote.sh rollback, then restart it again."
}

rollback() {
    local live_id prev_id
    live_id="$(image_id "$REPO:live")"; prev_id="$(image_id "$REPO:live-previous")"
    [ -n "$prev_id" ] || die "no $REPO:live-previous to go back to"
    [ -n "$live_id" ] || die "no $REPO:live"
    $DOCKER tag "$prev_id" "$REPO:live"
    $DOCKER tag "$live_id" "$REPO:live-previous"
    retire_env_override
    echo "promote: rolled back, $REPO:live is now $(built_from "$prev_id")"
    status
    echo
    echo "Now restart the everlake app in the TrueNAS Apps UI."
}

case "${1:-ptr}" in
    status) status ;;
    rollback) rollback ;;
    ptr)
        source="$(service_image worldserver-ptr)"
        [ -n "$source" ] || die "no worldserver-ptr container: start the everlake-ptr app first (it builds and runs the image to promote)"
        promote "$source" ;;
    -h|--help|help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) promote "$REPO:$1" ;;
esac
