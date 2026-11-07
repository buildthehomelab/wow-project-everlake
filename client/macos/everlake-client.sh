#!/bin/bash
# Sets up a Mac to play the Forever client on an Everlake server, and starts it.
#
#   ./everlake-client.sh setup <server address> <path to forever_root_ca.crt> [game folder]
#   ./everlake-client.sh play  <account email> [game folder]
#   ./everlake-client.sh check [game folder]
#   ./everlake-client.sh undo  [game folder]
#   ./everlake-client.sh gate2 [game folder]       (then: play <account email> gate2, check gate2)
#
# setup (asks for your password once, for the hosts file):
#   1. hosts entry: trinity.actual.battle.net -> 127.0.0.1, and remembers the server address. play runs
#      forward.py, which passes 127.0.0.1:1119/8081/8085 on to the server: since macOS 15 the re-signed game
#      copy isn't allowed onto the local network, but Terminal is, and 127.0.0.1 needs no permission.
#   2. trusts the server's root CA (macOS asks to confirm; the CA only covers *.actual.battle.net)
#   3. builds keypatch.dylib (needs Apple's command-line tools: xcode-select --install)
#   4. makes "World of Warcraft Everlake.app", an ad-hoc signed copy of the game that can load keypatch.dylib.
#      The original app is never changed. Run setup again after Battle.net updates the game.
#   5. writes WTF/Everlake.wtf (your Config.wtf + the Everlake portal)
# play: starts the forwarder, asks for your Everlake password, logs in to the server and hands the game a login
#       ticket (login.py, the way Battle.net does it), then starts the copy with the server key patch.
# check: prints everything that has to be right for the game to reach the server, and sends the report to the
#        server (report-drop service, port 8099) so nobody has to copy it by hand.
# undo: stops the forwarder, removes the hosts entry, the CA trust and the copy.
# gate2 (docs/custom-files.md, experiment 1): makes a test game folder in Application Support from APFS clones
#       (instant, no extra disk space; the Battle.net install is never changed) whose .build.info points at the
#       patched build and at the server's CDN (tools/tact/cdn.py on port 80, reached through the forwarder). The
#       build keys come from the server. Afterwards the word gate2 stands for the test folder: play <email> gate2.
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
SERVER_FILE="$SUPPORT/server.txt"
FORWARD_PID="$SUPPORT/forward.pid"
FORWARD_LOG="$SUPPORT/forward.log"
GATE2_FILE="$SUPPORT/gate2/game.txt"

say() { printf '\033[1m[everlake]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[everlake] %s\033[0m\n' "$*" >&2; exit 1; }

# The game folder: the one holding "World of Warcraft.app" (e.g. /Applications/World of Warcraft/_forever_).
# Prints it, or a reason on stderr and returns 1. (No exit in here: macOS bash 3.2 ends the whole script when a
# function in $(...) exits under set -e, whatever follows it.)
find_game() {
    if [ "${1:-}" = gate2 ]; then  # the test folder the gate2 command made
        if [ ! -f "$GATE2_FILE" ]; then echo "no gate2 test folder: run gate2 first" >&2; return 1; fi
        set -- "$(cat "$GATE2_FILE")"
    fi
    if [ -n "${1:-}" ]; then
        if [ ! -d "$1/World of Warcraft.app" ]; then
            echo "no 'World of Warcraft.app' in $1" >&2; return 1
        fi
        echo "$1"; return 0
    fi
    local d found=()
    for d in "/Applications/World of Warcraft"/_*_ "$HOME/Applications/World of Warcraft"/_*_; do
        if [ -d "$d/World of Warcraft.app" ]; then found+=("$d"); fi
    done
    if [ "${#found[@]}" -ne 1 ]; then
        echo "found ${#found[@]} game folders; pass the folder holding 'World of Warcraft.app'" >&2; return 1
    fi
    echo "${found[0]}"
}

game_build() {
    plutil -extract CFBundleVersion raw -o - "$1/World of Warcraft.app/Contents/Info.plist" 2>/dev/null || echo unknown
}

setup_hosts() {
    local addr="$1"
    mkdir -p "$SUPPORT"
    echo "$addr" > "$SERVER_FILE"
    if grep -q "$MARK" /etc/hosts; then
        sudo sed -i '' "/$MARK/d" /etc/hosts
    fi
    printf '%s\t%s\t%s\n' 127.0.0.1 "$PORTAL" "$MARK" | sudo tee -a /etc/hosts >/dev/null
    sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder 2>/dev/null || true
    say "hosts: $PORTAL -> 127.0.0.1 (forwarded to the server at $addr)"
}

server_addr() { cat "$SERVER_FILE" 2>/dev/null || true; }

stop_forward() {
    if [ -f "$FORWARD_PID" ] && kill -0 "$(cat "$FORWARD_PID")" 2>/dev/null; then
        kill "$(cat "$FORWARD_PID")" 2>/dev/null || true
        sleep 0.5
    fi
    rm -f "$FORWARD_PID"
}

start_forward() {
    local addr="$1"; shift
    stop_forward
    # extra ports (gate2 adds 80, the CDN) on top of forward.py's default 1119 8081 8085
    if [ $# -gt 0 ]; then set -- 1119 8081 8085 "$@"; fi
    nohup python3 "$HERE/forward.py" "$addr" "$@" > "$FORWARD_LOG" 2>&1 &
    echo $! > "$FORWARD_PID"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        nc -z -G 1 127.0.0.1 8081 2>/dev/null && { say "forwarder running (log: $FORWARD_LOG)"; return 0; }
        sleep 0.5
    done
    cat "$FORWARD_LOG" >&2
    die "the forwarder did not start"
}

setup_ca() {
    local crt="$1"
    [ -f "$crt" ] || die "CA certificate not found: $crt"
    # macOS (LibreSSL) and OpenSSL 3 both print "Permitted:" under "X509v3 Name Constraints"
    openssl x509 -in "$crt" -noout -text | grep -A2 "Name Constraints" | grep -q "DNS:actual.battle.net" \
        || die "$crt is not limited to actual.battle.net: not an Everlake CA"
    security add-trusted-cert -r trustRoot -k "$HOME/Library/Keychains/login.keychain-db" "$crt"
    mkdir -p "$SUPPORT"
    cp "$crt" "$SUPPORT/forever_root_ca.crt"   # login.py checks the login server against it
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

gate2_folder_report() {
    # Logs and data writes of one game folder since gate2 made the test folder (mark).
    local label="$1" game="$2" mark="$3" root
    root="$(dirname "$game")"
    say "gate2 [$label] $game"
    say "gate2 [$label] logs written since gate2 ran:"
    { find "$game/Logs" -maxdepth 1 -type f -newer "$mark" 2>/dev/null || true; } | while read -r f; do
        printf '    %s\t%s\t%s\n' "$(stat -f '%Sm' -t '%H:%M:%S' "$f")" "$(stat -f %z "$f")" "$(basename "$f")"
    done || true
    say "gate2 [$label] every log written since gate2 ran, last 25 lines each (raw):"
    { find "$game/Logs" -maxdepth 1 -type f -newer "$mark" -size +0 2>/dev/null || true; } | while read -r f; do
        echo "  -- $(basename "$f")"
        tail -n 25 "$f" 2>/dev/null | grep -v -E "Fully Compacted|Table [A-Za-z]+ RecID" | cut -c1-260 | sed 's/^/    /' || true
    done || true
    say "gate2 [$label] Tact.log (last 40 lines):"
    tail -n 40 "$game/Logs/Tact.log" 2>/dev/null | cut -c1-260 | sed 's/^/    /' || true
    say "gate2 [$label] hotfixes for our map and zones (Map, MapDifficulty, AreaTable), last 20:"
    grep -a -h -E "Table (Map|MapDifficulty|AreaTable) " "$game/Logs/Hotfix.log" 2>/dev/null | tail -n 20 | cut -c1-200 | sed 's/^/    /' || true
    say "gate2 [$label] streaming, storage, map and error lines (last 50):"
    grep -a -h -i -E "WOW519|streaming|stream.*(fail|error)|resident|loose|not found|unable to|failed to|map ?id|mapid|wdt|new world|transfer|worldport|disconnect" \
        "$game/Logs"/*.log 2>/dev/null | grep -v -E "IBN_Resources|title icons|Table [A-Za-z]+ RecID" | tail -n 50 | cut -c1-260 | sed 's/^/    /' || true
    say "gate2 [$label] crash or error reports (newest 3):"
    { ls -t "$game/Errors" 2>/dev/null || true; } | head -3 | while read -r f; do
        echo "  -- $f"; head -n 30 "$game/Errors/$f" 2>/dev/null | cut -c1-200 | sed 's/^/    /' || true
    done
    say "gate2 [$label] files in Data written since gate2 ran (newest 30):"
    { find "$root/Data" -type f -newer "$mark" 2>/dev/null || true; } | head -400 | while read -r f; do
        printf '    %s\t%s\t%s\n' "$(stat -f '%Sm' -t '%H:%M:%S' "$f")" "$(stat -f %z "$f")" "${f#"$root"/}"
    done | sort -k3 | tail -n 30 || true
}

gate2_report() {
    # What the client did with the patched build. Both folders are checked: the test copy, and the real install,
    # in case the game writes its logs or data there (it may find its install through Battle.net's settings).
    local game="$1" root mark real
    root="$(dirname "$game")"; mark="$root/.everlake-gate2"
    say "gate2: test folder made $(stat -f '%Sm' "$mark" 2>/dev/null); .build.info wowf row:"
    grep -a '|wowf' "$root/.build.info" | cut -c1-300 | sed 's/^/    /' || true
    gate2_folder_report "test copy" "$game" "$mark"
    real="$(find_game "" 2>/dev/null)" || real=""
    if [ -n "$real" ] && [ "$real" != "$game" ]; then
        say "gate2: the real install's .build.info wowf row (should still be Blizzard's):"
        grep -a '|wowf' "$(dirname "$real")/.build.info" | cut -c1-120 | sed 's/^/    /' || true
        gate2_folder_report "real install" "$real" "$mark"
    fi
    say "gate2: any other game log written since gate2 ran:"
    { find "$HOME/Library/Logs" "$HOME/Library/Application Support/Battle.net" -maxdepth 4 -type f -newer "$mark" \
        -iname "*.log" 2>/dev/null || true; } | head -20 | sed 's/^/    /' || true
}

do_check() {
    # Everything that has to be right before the game can reach the server.
    local GAME addr exe f port
    GAME="$(find_game "${1:-}" 2>/dev/null)" || GAME=""
    say "game folder: ${GAME:-NOT FOUND} (build $( [ -n "$GAME" ] && game_build "$GAME" || echo -))"
    say "game copy: $( [ -n "$GAME" ] && [ -d "$GAME/$COPY_NAME" ] && echo present || echo MISSING)"
    say "keypatch.dylib: $( [ -f "$DYLIB" ] && echo present || echo MISSING)"
    say "hosts entry: $(grep "$MARK" /etc/hosts || echo MISSING)"
    say "resolves to: $(dscacheutil -q host -a name "$PORTAL" | awk '/ip_address/{print $2}' | tr '\n' ' ')"
    addr="$(server_addr)"
    say "server address: ${addr:-NOT SAVED (run setup again)}"
    for port in 1119 8081 8085; do
        if [ -n "$addr" ] && nc -z -G 3 "$addr" "$port" 2>/dev/null; then say "server port $port: open"; else say "server port $port: NOT REACHABLE"; fi
    done
    if [ -f "$FORWARD_PID" ] && kill -0 "$(cat "$FORWARD_PID")" 2>/dev/null; then
        say "forwarder: running"
    else
        say "forwarder: not running (play starts it)"
    fi
    say "forward.log (last lines):"
    tail -n 15 "$FORWARD_LOG" 2>/dev/null | sed 's/^/    /' || true
    say "CA trusted: $(security find-certificate -c "$CA_NAME" "$HOME/Library/Keychains/login.keychain-db" >/dev/null 2>&1 && echo yes || echo NO)"
    if [ -n "$GAME" ]; then
        say "WTF/$WTF_NAME portal: $(grep -h '^SET portal' "$GAME/WTF/$WTF_NAME" 2>/dev/null || echo MISSING)"
        say "WTF/Config.wtf portal: $(grep -h '^SET portal' "$GAME/WTF/Config.wtf" 2>/dev/null || echo none)"
        exe="$(plutil -extract CFBundleExecutable raw -o - "$GAME/World of Warcraft.app/Contents/Info.plist" 2>/dev/null || true)"
        say "launch setting names in the game binary ($exe):"
        strings -a "$GAME/World of Warcraft.app/Contents/MacOS/$exe" 2>/dev/null \
            | grep -i -E "launch options|launcherlogin|WEB_TOKEN|CONNECTION_STRING|GAME_ACCOUNT|net\.battle" \
            | sort -u | head -25 | sed 's/^/    /'
        say "newest game logs (last lines):"
        for f in $(ls -t "$GAME/Logs" 2>/dev/null | head -3); do
            echo "  -- $f"
            tail -n 12 "$GAME/Logs/$f" 2>/dev/null | cut -c1-200 | sed 's/^/    /'
        done
        if [ -f "$(dirname "$GAME")/.everlake-gate2" ]; then
            gate2_report "$GAME"
        fi
    fi
    say "net.battle launch options (values hidden except the connection):"
    defaults read net.battle 2>/dev/null | grep -E "Launch Options|CONNECTION_STRING|GAME_ACCOUNT|WEB_TOKEN" \
        | sed -E 's/(WEB_TOKEN[^=]*=).*/\1 <hidden>;/' | sed 's/^/    /'
    say "keypatch.log:"
    cat "$SUPPORT/keypatch.log" 2>/dev/null || echo "  (none)"
}

cmd="${1:-}"; shift || true
case "$cmd" in
    setup)
        [ $# -ge 2 ] || die "usage: $0 setup <server address> <forever_root_ca.crt> [game folder]"
        GAME="$(find_game "${3:-}")" || die "game folder not found"
        say "game folder: $GAME (build $(game_build "$GAME"))"
        setup_hosts "$1"
        setup_ca "$2"
        build_dylib
        make_copy "$GAME"
        write_wtf "$GAME"
        say "done. Start with: $0 play <account email>"
        ;;
    play)
        [ $# -ge 1 ] || die "usage: $0 play <account email> [game folder]"
        GAME="$(find_game "${2:-}")" || die "game folder not found"
        [ -d "$GAME/$COPY_NAME" ] || die "no game copy: run setup first"
        [ -f "$DYLIB" ] || die "no keypatch.dylib: run setup first"
        [ -f "$SUPPORT/forever_root_ca.crt" ] || die "no copy of the CA certificate: run setup again"
        ADDR="$(server_addr)"; [ -n "$ADDR" ] || die "no server address saved: run setup again"
        grep "$MARK" /etc/hosts | grep -q '^127\.0\.0\.1' || die "hosts entry is not 127.0.0.1: run setup again"
        if [ -f "$(dirname "$GAME")/.everlake-gate2" ]; then
            say "gate2 test folder: the game's CDN is the server's port 80"
            start_forward "$ADDR" 80
        else
            start_forward "$ADDR"
        fi
        python3 "$HERE/login.py" "$1" || die "login failed"
        LOG="$SUPPORT/keypatch.log"; : > "$LOG"
        say "starting the game (key patch log: $LOG)"
        open -n -a "$GAME/$COPY_NAME" \
            --env "DYLD_INSERT_LIBRARIES=$DYLIB" \
            --env "FOREVER_SERVER_KEY=$SERVER_KEY" \
            --env "FOREVER_REGION_GROUP=$REGION_GROUP" \
            --env "FOREVER_PATCH_LOG=$LOG" \
            --args -launcherlogin -config "$WTF_NAME"
        say "first realm login can fail with 'server identity check failed': click Reconnect"
        ;;
    check)
        # Prints everything that has to be right, saves it and sends it to the server's report drop (port 8099).
        REPORT="$SUPPORT/check.txt"; mkdir -p "$SUPPORT"
        # a failing step must not stop the report from being sent
        { do_check "$@" 2>&1 || echo "[everlake] check stopped early (exit $?)"; } | tee "$REPORT"
        addr="$(server_addr)"
        if [ -n "$addr" ] && curl -s -m 5 -T "$REPORT" "http://$addr:8099/check-$(hostname -s)" >/dev/null; then
            say "report sent to the server"
        else
            say "report NOT sent (saved in $REPORT)"
        fi
        ;;
    gate2)
        GAME="$(find_game "${1:-}")" || die "game folder not found"
        [ -d "$GAME/$COPY_NAME" ] || die "no game copy: run setup first"
        ADDR="$(server_addr)"; [ -n "$ADDR" ] || die "no server address saved: run setup first"
        ROOT="$(dirname "$GAME")"; FLAVOR="$(basename "$GAME")"
        [ -d "$ROOT/Data" ] && [ -f "$ROOT/.build.info" ] || die "no Data folder or .build.info in $ROOT"
        nc -z -G 3 "$ADDR" 80 2>/dev/null || die "the server's CDN (port 80) is not reachable: start tools/tact/cdn.py there"
        KEYS="$(curl -sf -m 10 "http://$ADDR/everlake/build.json" \
            | python3 -c 'import json,sys; b=json.load(sys.stdin); print(b["build_key"], b["cdn_key"])')" \
            || die "could not read the build keys from the server's CDN"
        BUILD_KEY="${KEYS% *}"; CDN_KEY="${KEYS#* }"
        say "patched build from the server: build key $BUILD_KEY, CDN key $CDN_KEY"
        TEST="$SUPPORT/gate2/World of Warcraft"
        # keep the last test run's logs: re-making the folder would otherwise delete the evidence of a failure
        if [ -d "$TEST/$FLAVOR/Logs" ]; then
            KEEP="$SUPPORT/gate2-logs/$(date +%Y%m%d-%H%M%S)"; mkdir -p "$KEEP"
            cp -R "$TEST/$FLAVOR/Logs" "$KEEP/" 2>/dev/null || true
            [ -d "$TEST/$FLAVOR/Errors" ] && cp -R "$TEST/$FLAVOR/Errors" "$KEEP/" 2>/dev/null || true
            say "kept the previous test run's logs in $KEEP"
        fi
        rm -rf "$SUPPORT/gate2"; mkdir -p "$TEST"
        say "cloning $ROOT into $TEST (APFS clones: instant, no extra space)..."
        cp -cR "$ROOT/Data" "$TEST/Data" || die "cloning failed: is the disk APFS?"
        cp -cR "$GAME" "$TEST/$FLAVOR"
        for f in "$ROOT"/.[!.]*; do [ -f "$f" ] && cp -c "$f" "$TEST/"; done
        python3 "$HERE/buildinfo.py" "$TEST/.build.info" wowf "$BUILD_KEY" "$CDN_KEY" 127.0.0.1 || die ".build.info not changed"
        for key in "$BUILD_KEY" "$CDN_KEY"; do
            d="$TEST/Data/config/${key:0:2}/${key:2:2}"; mkdir -p "$d"
            curl -sf -m 30 -o "$d/$key" "http://$ADDR/tpr/wow/config/${key:0:2}/${key:2:2}/$key" \
                || die "could not fetch config $key from the server's CDN"
            [ "$(md5 -q "$d/$key")" = "$key" ] || die "config $key does not match its name"
        done
        touch "$TEST/.everlake-gate2"
        echo "$TEST/$FLAVOR" > "$GATE2_FILE"
        say "test folder ready ($TEST/$FLAVOR). Original install untouched. Start it with:"
        say "  $0 play <account email> gate2"
        say "then: does the Hearthstone show the Ragnaros icon? Afterwards run: $0 check gate2"
        ;;
    undo)
        stop_forward
        if grep -q "$MARK" /etc/hosts; then sudo sed -i '' "/$MARK/d" /etc/hosts; say "hosts entry removed"; fi
        security delete-certificate -c "$CA_NAME" "$HOME/Library/Keychains/login.keychain-db" 2>/dev/null \
            && say "CA removed" || true
        GAME="$(find_game "${1:-}" 2>/dev/null)" || GAME=""
        if [ -n "$GAME" ]; then
            rm -rf "${GAME:?}/$COPY_NAME" "${GAME:?}/WTF/$WTF_NAME"
            say "game copy removed"
        fi
        rm -rf "${SUPPORT:?}"
        ;;
    *)
        sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 1
        ;;
esac
