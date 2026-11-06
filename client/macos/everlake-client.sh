#!/bin/bash
# Sets up a Mac to play the Forever client on an Everlake server, and starts it.
#
#   ./everlake-client.sh setup <server address> <path to forever_root_ca.crt> [game folder]
#   ./everlake-client.sh play  [game folder]
#   ./everlake-client.sh undo  [game folder]
#
# setup (asks for your password once, for the hosts file):
#   1. hosts entry: trinity.actual.battle.net -> the server
#   2. trusts the server's root CA (macOS asks to confirm; the CA only covers *.actual.battle.net)
#   3. builds keypatch.dylib (needs Apple's command-line tools: xcode-select --install)
#   4. makes "World of Warcraft Everlake.app", an ad-hoc signed copy of the game that can load keypatch.dylib.
#      The original app is never changed. Run setup again after Battle.net updates the game.
#   5. writes WTF/Everlake.wtf (your Config.wtf + the Everlake portal)
# play: starts the copy with the server key patch; log in with your Everlake account in the game.
# undo: removes the hosts entry, the CA trust and the copy.
#
# Based on jibay442/forever_docker's macOS launcher (GPL-2.0), see docs/client-connection.md.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PORTAL=trinity.actual.battle.net
MARK="# everlake"
SUPPORT="$HOME/Library/Application Support/Everlake"
DYLIB="$SUPPORT/libeverlake_keypatch.dylib"
COPY_NAME="World of Warcraft Everlake.app"
WTF_NAME=Everlake.wtf
CA_NAME="Forever Private Root CA"
# TrinityCore's stock EnterEncryptedMode key (public half) and the region group the server uses
SERVER_KEY="${EVERLAKE_SERVER_KEY:-02596F0D0C061A8B30745988FD72C59E29EC367FB0F341F28E0F08D037BAFC69}"
REGION_GROUP="${EVERLAKE_REGION_GROUP:-8}"

say() { printf '\033[1m[everlake]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[everlake] %s\033[0m\n' "$*" >&2; exit 1; }

# The game folder: the one holding "World of Warcraft.app" (e.g. /Applications/World of Warcraft/_forever_)
find_game() {
    if [ -n "${1:-}" ]; then
        [ -d "$1/World of Warcraft.app" ] || die "no 'World of Warcraft.app' in $1"
        echo "$1"; return
    fi
    local d found=()
    for d in "/Applications/World of Warcraft"/_*_ "$HOME/Applications/World of Warcraft"/_*_; do
        [ -d "$d/World of Warcraft.app" ] && found+=("$d")
    done
    [ "${#found[@]}" -eq 1 ] || die "found ${#found[@]} game folders (${found[*]:-none}); pass the folder holding 'World of Warcraft.app'"
    echo "${found[0]}"
}

game_build() {
    plutil -extract CFBundleVersion raw -o - "$1/World of Warcraft.app/Contents/Info.plist" 2>/dev/null || echo unknown
}

setup_hosts() {
    local addr="$1"
    if grep -q "$MARK" /etc/hosts; then
        sudo sed -i '' "/$MARK/d" /etc/hosts
    fi
    printf '%s\t%s\t%s\n' "$addr" "$PORTAL" "$MARK" | sudo tee -a /etc/hosts >/dev/null
    sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder 2>/dev/null || true
    say "hosts: $PORTAL -> $addr"
}

setup_ca() {
    local crt="$1"
    [ -f "$crt" ] || die "CA certificate not found: $crt"
    # macOS (LibreSSL) and OpenSSL 3 both print "Permitted:" under "X509v3 Name Constraints"
    openssl x509 -in "$crt" -noout -text | grep -A2 "Name Constraints" | grep -q "DNS:actual.battle.net" \
        || die "$crt is not limited to actual.battle.net: not an Everlake CA"
    security add-trusted-cert -r trustRoot -k "$HOME/Library/Keychains/login.keychain-db" "$crt"
    say "CA trusted (login keychain)"
}

build_dylib() {
    command -v clang >/dev/null || die "clang missing: run xcode-select --install"
    mkdir -p "$SUPPORT"
    clang -O2 -dynamiclib -arch arm64 -arch x86_64 -o "$DYLIB" "$HERE/keypatch.c"
    codesign --force -s - "$DYLIB"
    xattr -c "$DYLIB" 2>/dev/null || true
    say "built $DYLIB"
}

make_copy() {
    local game="$1" src="$1/World of Warcraft.app" tmp="$1/.everlake-copy.tmp" copy="$1/$COPY_NAME"
    local ent="$SUPPORT/entitlements.plist" exe f
    say "copying the game app (build $(game_build "$game"))..."
    rm -rf "$tmp"
    ditto "$src" "$tmp"
    xattr -cr "$tmp"
    cat > "$ent" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>com.apple.security.cs.allow-jit</key><true/>
<key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
<key>com.apple.security.cs.disable-executable-page-protection</key><true/>
<key>com.apple.security.cs.disable-library-validation</key><true/>
<key>com.apple.security.cs.allow-dyld-environment-variables</key><true/>
<key>com.apple.security.device.audio-input</key><true/>
<key>com.apple.security.get-task-allow</key><true/>
</dict></plist>
EOF
    say "signing the copy (ad hoc)..."
    # nested code first: helper apps, then the files next to the executable, then the app itself
    if [ -d "$tmp/Contents/Helpers" ]; then
        for f in "$tmp/Contents/Helpers"/*; do codesign --force --deep -s - "$f"; done
    fi
    exe="$(plutil -extract CFBundleExecutable raw -o - "$tmp/Contents/Info.plist")"
    for f in "$tmp/Contents/MacOS"/*; do
        [ -f "$f" ] && [ "$(basename "$f")" != "$exe" ] && codesign --force -s - "$f"
    done
    codesign --force -s - --entitlements "$ent" "$tmp"
    rm -rf "$copy"
    mv "$tmp" "$copy"
    say "made $copy"
}

write_wtf() {
    local dir="$1/WTF" out
    mkdir -p "$dir"
    out="$dir/$WTF_NAME"
    { [ -f "$dir/Config.wtf" ] && grep -v -E '^SET (portal|textLocale|audioLocale) ' "$dir/Config.wtf" | tr -d '\r' || true
      printf 'SET portal "%s"\nSET textLocale "enUS"\nSET audioLocale "enUS"\n' "$PORTAL"
    } > "$out.tmp"
    mv "$out.tmp" "$out"
    say "wrote $out"
}

cmd="${1:-}"; shift || true
case "$cmd" in
    setup)
        [ $# -ge 2 ] || die "usage: $0 setup <server address> <forever_root_ca.crt> [game folder]"
        GAME="$(find_game "${3:-}")"
        say "game folder: $GAME (build $(game_build "$GAME"))"
        setup_hosts "$1"
        setup_ca "$2"
        build_dylib
        make_copy "$GAME"
        write_wtf "$GAME"
        say "done. Start with: $0 play"
        ;;
    play)
        GAME="$(find_game "${1:-}")"
        [ -d "$GAME/$COPY_NAME" ] || die "no game copy: run setup first"
        [ -f "$DYLIB" ] || die "no keypatch.dylib: run setup first"
        LOG="$SUPPORT/keypatch.log"; : > "$LOG"
        say "starting the game (key patch log: $LOG)"
        open -n -a "$GAME/$COPY_NAME" \
            --env "DYLD_INSERT_LIBRARIES=$DYLIB" \
            --env "FOREVER_SERVER_KEY=$SERVER_KEY" \
            --env "FOREVER_REGION_GROUP=$REGION_GROUP" \
            --env "FOREVER_PATCH_LOG=$LOG" \
            --args -config "$WTF_NAME"
        say "first realm login can fail with 'server identity check failed': click Reconnect"
        ;;
    undo)
        if grep -q "$MARK" /etc/hosts; then sudo sed -i '' "/$MARK/d" /etc/hosts; say "hosts entry removed"; fi
        security delete-certificate -c "$CA_NAME" "$HOME/Library/Keychains/login.keychain-db" 2>/dev/null \
            && say "CA removed" || true
        GAME="$(find_game "${1:-}" 2>/dev/null || true)"
        if [ -n "$GAME" ]; then
            rm -rf "${GAME:?}/$COPY_NAME" "${GAME:?}/WTF/$WTF_NAME"
            say "game copy removed"
        fi
        rm -rf "${SUPPORT:?}"
        ;;
    *)
        sed -n '2,17p' "$0"; exit 1
        ;;
esac
