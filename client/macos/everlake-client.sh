#!/bin/bash
# Sets up a Mac to play the Forever client on an Everlake server, and starts it.
#
#   ./everlake-client.sh setup <server address> <path to forever_root_ca.crt | none> [game folder]
#   ./everlake-client.sh play  <account email> [game folder]
#   ./everlake-client.sh check [game folder]
#   ./everlake-client.sh undo  [game folder]
#   ./everlake-client.sh gate2 [game folder]       (then: play <account email> gate2, check gate2)
#   ./everlake-client.sh gate2-addon               (re-installs the gate2 prefetch addon in the test folder)
#   ./everlake-client.sh gate2-inspect             (read-only check of the local storage, sent to the server)
#   ./everlake-client.sh gate2-install             (puts the added files into the test folder's local storage; gate2-uninstall undoes)
#   ./everlake-client.sh test1-addon [game folder]  (Test 1: installs the EverlakeTest1 addon; then play, then test1)
#   ./everlake-client.sh test1 [game folder]        (Test 1 report: hotfixes, the addon's record, errors, screenshots)
#   ./everlake-client.sh test1-ui                   (Test 1 UI: gate2 copy from the server's build, its files, the addon)
#   ./everlake-client.sh fix-owner                  (gives the Everlake folder back to you after a run with sudo)
#   ./everlake-client.sh switch <account email> [game folder]  (gate 5 realm switch test: guided, sends a report)
#   ./everlake-client.sh cdn <address[:port] | server>  (where gate2 gets the patched build; default: the server, 8087)
#   ./everlake-client.sh china-undead [CDN address[:port]]  (China Undead test: gate2 copy + files; docs/china-undead.md)
#   ./everlake-client.sh china-mode on|off [game folder]  (the client's own China setting, overrideArchive)
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
#   Our own login name: EVERLAKE_LOGIN_HOST=login.realm.example.com ./everlake-client.sh setup <server address> none
#   The name is remembered for play. With a real certificate for it there is no CA to trust ("none"), and play has the
#   key patch also lift the client's rule that login names end in .actual.battle.net (FOREVER_ANY_PORTAL in
#   keypatch.c). See docs/client-connection.md.
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
MARK="# everlake"
SUPPORT="$HOME/Library/Application Support/Everlake"
# The login server's name: EVERLAKE_LOGIN_HOST, else the one setup saved, else the battle.net name with our own CA.
LOGIN_FILE="$SUPPORT/login-host.txt"
PORTAL="${EVERLAKE_LOGIN_HOST:-$(cat "$LOGIN_FILE" 2>/dev/null || true)}"
PORTAL="${PORTAL:-trinity.actual.battle.net}"
export EVERLAKE_LOGIN_HOST="$PORTAL"   # login.py logs in there
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

# Where the patched build (tools/tact/cdn.py) is served, as address[:port]: EVERLAKE_CDN, else what the cdn command
# saved, else the game server's cdn service (docker-compose.yml, port 8087). A missing port means 80.
CDN_FILE="$SUPPORT/cdn.txt"
cdn_addr() {
    local a="${EVERLAKE_CDN:-$(cat "$CDN_FILE" 2>/dev/null || true)}"
    if [ -n "$a" ]; then echo "$a"; elif [ -n "$(server_addr)" ]; then echo "$(server_addr):8087"; fi
}
# host and port of an address[:port]
addr_host() { echo "${1%%:*}"; }
addr_port() { case "$1" in *:*) echo "${1##*:}" ;; *) echo 80 ;; esac; }

# true when the login name is our own, not a *.actual.battle.net one: the client then needs the login-name patch
custom_portal() { case "$PORTAL" in *.actual.battle.net) return 1 ;; *) return 0 ;; esac; }

FORWARD_PORTS="1119 8081 8085 8086 8095 80"

# the pid listening on 127.0.0.1:<port>, if any
port_listener() { lsof -nP -t -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | head -n 1 || true; }

stop_forward() {
    local port pid cmd
    if [ -f "$FORWARD_PID" ] && kill -0 "$(cat "$FORWARD_PID")" 2>/dev/null; then
        kill "$(cat "$FORWARD_PID")" 2>/dev/null || true
        sleep 0.5
    fi
    rm -f "$FORWARD_PID"
    # A forwarder from an earlier run whose pid file was lost still holds the ports; a new one then can't listen and
    # quits, while the old one keeps serving without the newer ports (2026-11-07: no port 8095, realm 2 unreachable).
    # Stop whatever holds our ports, but only if it is a forward.py.
    for port in $FORWARD_PORTS; do
        pid="$(port_listener "$port")"
        if [ -n "$pid" ]; then
            if ps -o command= -p "$pid" 2>/dev/null | grep -q 'forward\.py'; then
                say "stopping an old forwarder still running (pid $pid, port $port)"
                kill "$pid" 2>/dev/null || true
                sleep 0.5
            fi
        elif nc -z -G 1 127.0.0.1 "$port" 2>/dev/null; then
            # busy, but not by a process of ours: another user's, e.g. a forwarder started with sudo. Only root can see
            # (and stop) it, so this step asks for your password.
            say "port $port is held by a program you can't see (started with sudo?): looking it up as root (asks for your password)"
            pid="$(sudo lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
            cmd="$( [ -n "$pid" ] && sudo ps -o command= -p "$pid" 2>/dev/null || true)"
            if printf '%s' "$cmd" | grep -q 'forward\.py'; then
                say "stopping a forwarder that was started with sudo (pid $pid, port $port)"
                sudo kill "$pid" 2>/dev/null || true
                sleep 0.5
            else
                say "port $port is held by: ${cmd:-unknown (pid ${pid:-?})}"
            fi
        fi
    done
}

start_forward() {
    local addr="$1" pid="" port missing
    shift
    stop_forward
    # extra ports (gate2 adds 80, the CDN, as 80@<cdn address> when it runs elsewhere) on top of forward.py's default
    # 1119 8081 8085 8086 8095
    # (8086 = realm 1 on a host that already runs Evermore on 8085, 8095 = realm 2)
    set -- 1119 8081 8085 8086 8095 "$@"
    FORWARD_PID_FILE="$FORWARD_PID" nohup python3 "$HERE/forward.py" "$addr" "$@" > "$FORWARD_LOG" 2>&1 &
    missing=" $*"
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        sleep 0.5
        [ -s "$FORWARD_PID" ] || continue   # forward.py writes its pid once every port listens
        pid="$(tr -dc '0-9' < "$FORWARD_PID")"
        missing=""
        # a port may name its own machine (80@<cdn address>): the listener is still the local port
        for port in "$@"; do [ "$(port_listener "${port%%@*}")" = "$pid" ] || missing="$missing ${port%%@*}"; done
        [ -z "$missing" ] && { say "forwarder running on ports $* (log: $FORWARD_LOG)"; return 0; }
    done
    cat "$FORWARD_LOG" >&2
    for port in $missing; do
        pid="$(port_listener "$port")"
        [ -n "$pid" ] && say "port $port is taken by: $(ps -o command= -p "$pid" 2>/dev/null | cut -c1-120)"
    done
    die "the forwarder did not start on port(s)$missing"
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

gate2_addon() {
    # Installs client/addons/EverlakePrefetch into a gate2 test folder, with the list of added files taken from the
    # server's build.json. On login it asks the client for each file, so they are stored locally before a map
    # that needs them loads.
    local game="$1" addr="$2" dest="$1/Interface/AddOns/EverlakePrefetch"
    mkdir -p "$dest"
    cp "$HERE/../addons/EverlakePrefetch/EverlakePrefetch.toc" "$HERE/../addons/EverlakePrefetch/EverlakePrefetch.lua" "$dest/"
    curl -sf -m 10 "http://$addr/everlake/build.json" | python3 -c '
import json, sys
ids = sorted(int(f) for f in json.load(sys.stdin)["files"])
print("EverlakePrefetchList = {%s}" % ", ".join(map(str, ids)))' > "$dest/EverlakePrefetchList.lua" \
        || die "could not read the file list from the server's CDN"
    say "addon EverlakePrefetch installed in the test folder ($(grep -o '[0-9]\+' "$dest/EverlakePrefetchList.lua" | wc -l | tr -d ' ') files)"
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
    say "gate2 [$label] every log written since gate2 ran, last 80 lines each (raw):"
    { find "$game/Logs" -maxdepth 1 -type f -newer "$mark" -size +0 2>/dev/null || true; } | while read -r f; do
        echo "  -- $(basename "$f")"
        tail -n 80 "$f" 2>/dev/null | grep -v -E "Fully Compacted|Table [A-Za-z]+ RecID" | cut -c1-260 | sed 's/^/    /' || true
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
    say "gate2: who may write the test copy's storage (you are $(id -un), groups $(id -Gn | tr ' ' ','))"
    for d in "$root/Data" "$root/Data/data" "$root/Data/config"; do
        ls -ldeO@ "$d" 2>&1 | sed 's/^/    /'
    done
    ls -leO "$root/Data/data" 2>/dev/null | grep -E '\.idx$' | head -4 | sed 's/^/    /'
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

test1_report() {
    # Test 1 (docs/era-data.md): what the client did with the Death Knight and Monk rows, read from the game folder.
    local game="$1" mark="$SUPPORT/test1.mark" f n
    say "test1: game folder $game, build $(game_build "$game") (the server takes 1.60.1.70790 only)"
    say "test1: addon EverlakeTest1 $( [ -f "$game/Interface/AddOns/EverlakeTest1/EverlakeTest1.lua" ] && echo installed || echo MISSING: run test1-addon)"
    say "test1: started $(stat -f '%Sm' "$mark" 2>/dev/null || echo '(no mark: run test1-addon first)')"
    say "test1: hotfixes from our pushes (9540020-9540029 classes and spells, 9540010-9540015 talent tree, 9540030+ visuals) per table and result:"
    grep -a -h -E "[^0-9]95400[0-3][0-9] Table " "$game/Logs/Hotfix.log" 2>/dev/null \
        | awk '{for (i = 1; i <= NF; i++) if ($i == "Table") print $(i + 1), $NF}' | sort | uniq -c | sed 's/^/    /' || true
    say "test1: our hotfix rows the client did NOT accept (first 40):"
    grep -a -h -E "[^0-9]95400[0-3][0-9] Table " "$game/Logs/Hotfix.log" 2>/dev/null \
        | grep -v "VALIDATION_RESULT_VALID" | head -n 40 | cut -c1-200 | sed 's/^/    /' || true
    say "test1: the addon's record (SavedVariables EverlakeTest1.lua; written at /reload or logout):"
    n=0
    for f in "$game"/WTF/Account/*/SavedVariables/EverlakeTest1.lua; do
        [ -f "$f" ] || continue
        n=$((n + 1))
        echo "  -- $f ($(stat -f '%Sm' "$f"))"
        head -n 1500 "$f" | cut -c1-400 | sed 's/^/    /'
    done
    [ "$n" -gt 0 ] || echo "    (none yet)"
    say "test1: logs written since test1-addon, error and character lines (last 80):"
    { find "$game/Logs" -maxdepth 1 -type f -newer "$mark" 2>/dev/null || true; } | while read -r f; do
        grep -a -H -i -E "error|invalid|fail|lua|script|charcreate|character create|class|exception|assert" "$f" 2>/dev/null \
            | grep -v -E "Table [A-Za-z]+ RecID .* VALIDATION_RESULT_VALID|IBN_Resources" | tail -n 30 || true
    done | tail -n 80 | cut -c1-260 | sed 's/^/    /'
    say "test1: crash or error reports since test1-addon:"
    { find "$game/Errors" -type f -newer "$mark" 2>/dev/null || true; } | head -3 | while read -r f; do
        echo "  -- $(basename "$f")"; head -n 40 "$f" 2>/dev/null | cut -c1-200 | sed 's/^/    /' || true
    done
    say "test1: screenshots since test1-addon, the game's and the Desktop's (each sent to the server as its own file):"
    test1_shots "$game" | while read -r f; do
        printf '    %s\t%s\n' "$(basename "$f")" "$(stat -f %z "$f")"
    done
}

test1_shots() {
    # Screenshots taken since test1-addon: the game's own (Screenshots folder) and macOS ones (Cmd+Shift+3 or 4, on
    # the Desktop), newest 12.
    { find "$1/Screenshots" "$HOME/Desktop" -maxdepth 1 -type f -newer "$SUPPORT/test1.mark" \
        \( -iname "*.jpg" -o -iname "*.png" -o -iname "*.tga" \) 2>/dev/null || true; } | sort | tail -n 12
}

# --- gate 5 realm switch test (docs/era-data.md, tests 4-6) ---
# Realm 1 "Everlake" (Forever) and realm 2 "Everlake Two" (a second Forever realm) send different data: realm 2 alone has the Death
# Knight and Monk kit (hotfix pushes 9540010-9540030), and both rename Attack (push 9550000 on both: same push, other
# text) and the Hearthstone (realm 1 push 9550001, realm 2 push 9560001). The EverlakeSwitch addon checks at every
# login that the client shows only the current realm's data; these functions keep what the client stored after each run.
SWITCH="$SUPPORT/switch"

game_running() { pgrep -f "$COPY_NAME/Contents/MacOS" >/dev/null 2>&1; }

switch_snapshot() {
    # <game> <label>: the client's caches, its hotfix log and the addon's record, as they are now
    local game="$1" label="$2" out="$SWITCH/$2" f
    mkdir -p "$out"
    {
        echo "== snapshot $label at $(date '+%H:%M:%S')"
        echo "-- Cache folder (size, modified, path; md5 of the hotfix cache):"
        { find "$game/Cache" -type f 2>/dev/null || true; } | sort | while read -r f; do
            printf '    %10s  %s  %s\n' "$(stat -f %z "$f")" "$(stat -f '%Sm' -t '%H:%M:%S' "$f")" "${f#"$game"/}"
        done | head -n 80 || true
        find "$game/Cache" -name DBCache.bin 2>/dev/null | while read -r f; do
            echo "-- ${f#"$game"/} md5 $(md5 -q "$f")"
            python3 "$HERE/dbcache.py" "$f" 2>&1 | sed 's/^/    /'
            cp "$f" "$out/DBCache.bin" 2>/dev/null || true
        done
        echo "-- per-realm folders under WTF/Account (the client keeps settings per realm there):"
        { find "$game/WTF/Account" -mindepth 2 -maxdepth 2 -type d 2>/dev/null || true; } | sed "s#^$game/##; s/^/    /"
        echo "-- Hotfix.log: $(wc -l < "$game/Logs/Hotfix.log" 2>/dev/null | tr -d ' ' || echo 0) lines, modified $(stat -f '%Sm' "$game/Logs/Hotfix.log" 2>/dev/null || echo -)"
    } > "$out/snapshot.txt" 2>&1
    cp "$game/Logs/Hotfix.log" "$out/Hotfix.log" 2>/dev/null || true
    for f in "$game"/WTF/Account/*/SavedVariables/EverlakeSwitch.lua; do [ -f "$f" ] && cp "$f" "$out/"; done
    cat "$out/snapshot.txt"
}

switch_hotfix_lines() {
    # <Hotfix.log>: our pushes per push id, the marker rows as logged, and the other kinds of lines in the log
    local log="$1"
    [ -f "$log" ] || { echo "    (no Hotfix.log)"; return 0; }
    echo "    our pushes, rows logged per push id:"
    grep -a -o -E '[^0-9](95[3-6][0-9]{4})[^0-9]' "$log" | tr -dc '0-9\n' | sort | uniq -c | sed 's/^/      /' || true
    echo "    every line naming a marker push (9550000, 9550001, 9560001) or record 6603 / 8690:"
    grep -a -E '955000[01]|9560001|RecID:? ?(6603|8690)[^0-9]' "$log" | head -n 40 | cut -c1-240 | sed 's/^/      /' || true
    echo "    lines that are not single rows (requests, connections, summaries), first 40:"
    grep -a -v -E 'Table [A-Za-z0-9_]+ RecID' "$log" | head -n 40 | cut -c1-240 | sed 's/^/      /' || true
}

switch_ask() {
    # <question>: the answer typed in Terminal goes into the report
    local answer
    printf '\033[1;33m[everlake] %s\033[0m ' "$1"
    read -r answer < /dev/tty || answer="(no answer)"
    echo "Q: $1" >> "$SWITCH/answers.txt"
    echo "A: ${answer:-(empty)}" >> "$SWITCH/answers.txt"
}

switch_run() {
    # <email> <folder> <run number> <instructions...>: starts the game, waits until it has been quit
    local email="$1" folder="$2" run="$3" n=0
    shift 3
    say "---- run $run ----"
    for line in "$@"; do say "  $line"; done
    if game_running; then die "the game is already running: quit it first"; fi
    "$0" play "$email" ${folder:+"$folder"} || die "play failed"
    while ! game_running && [ $n -lt 60 ]; do sleep 1; n=$((n + 1)); done
    game_running || die "the game did not start"
    say "waiting for you to quit the game (Exit button or Cmd+Q)..."
    while game_running; do sleep 3; done
    say "game quit at $(date '+%H:%M:%S')"
}

switch_report() {
    # everything the test kept, in run order
    local d
    say "switch: game folder $1, build $(game_build "$1"); started $(stat -f '%Sm' "$SWITCH/mark" 2>/dev/null)"
    for d in "$SWITCH"/[0-9]*; do
        [ -d "$d" ] || continue
        cat "$d/snapshot.txt" 2>/dev/null
        echo "-- Hotfix.log at this point:"
        switch_hotfix_lines "$d/Hotfix.log"
    done
    say "switch: the answers you typed"
    sed 's/^/    /' "$SWITCH/answers.txt" 2>/dev/null || echo "    (none)"
    say "switch: the addon's record, every login (EverlakeSwitch saved variables):"
    d="$(ls -d "$SWITCH"/[0-9]* 2>/dev/null | tail -n 1)"
    if [ -n "$d" ] && [ -f "$d/EverlakeSwitch.lua" ]; then sed 's/^/    /' "$d/EverlakeSwitch.lua" | head -n 600; else echo "    (none: was the addon enabled?)"; fi
    say "switch: crash or error reports since the test started:"
    { find "$1/Errors" -type f -newer "$SWITCH/mark" 2>/dev/null || true; } | head -3 | while read -r f; do
        echo "  -- $(basename "$f")"; head -n 30 "$f" 2>/dev/null | cut -c1-200 | sed 's/^/    /' || true
    done
}

switch_test() {
    local email="$1" folder="${2:-}" game addr report f n=0 small
    game="$(find_game "$folder")" || die "game folder not found"
    addr="$(server_addr)"; [ -n "$addr" ] || die "no server address saved: run setup first"
    nc -z -G 3 "$addr" 8095 2>/dev/null || die "realm 2 (port 8095 on the server) is not reachable: is worldserver2 running?"
    if game_running; then die "the game is running: quit it first"; fi
    rm -rf "$SWITCH"; mkdir -p "$SWITCH"; touch "$SWITCH/mark"
    mkdir -p "$game/Interface/AddOns/EverlakeSwitch"
    cp "$HERE/../addons/EverlakeSwitch/EverlakeSwitch.toc" "$HERE/../addons/EverlakeSwitch/EverlakeSwitch.lua" \
        "$game/Interface/AddOns/EverlakeSwitch/"
    say "addon EverlakeSwitch installed in $game (build $(game_build "$game"))"
    say "Two game runs, about 15 minutes. After each login the addon prints a line in chat: OK (green) or MIXED (red)."
    say "Take a screenshot (Cmd+Shift+3) whenever something looks wrong, and at the two character creation screens."
    switch_snapshot "$game" 0-before >/dev/null || say "snapshot 0-before incomplete"
    switch_run "$email" "$folder" 1 \
        "1. RULESET (top of the character screen): Normal card = Everlake. Select. Enter the world with Pat. Wait for the chat line. Press P: in General," \
        "   is Attack called 'Attack (realm 1)'? Log out (to the character list)." \
        "2. Create New Character, Human: Death Knight and Monk should NOT be offered here. Screenshot. Back." \
        "3. RULESET: Roleplay card = Everlake Two. Select. Enter the world with Aevise. Chat line. Press P: 'Attack (realm 2)'" \
        "   and a Death Knight tab; hover Death Coil: does the tooltip have text? Screenshot. Log out." \
        "4. Create New Character, Human: Death Knight and Monk SHOULD be offered here. Screenshot. Back." \
        "5. RULESET Normal: Pat, chat line, log out. RULESET Roleplay: Aevise, chat line, log out." \
        "6. Quit the game (Exit)."
    switch_snapshot "$game" 1-after-run1 >/dev/null || say "snapshot 1-after-run1 incomplete"
    switch_ask "Run 1: did the Roleplay card take you to Everlake Two (Aevise and Asdasd listed)? (y/n)"
    switch_ask "Run 1: did Everlake's character creation offer Death Knight or Monk? (y/n, which)"
    switch_ask "Run 1: did Everlake Two's character creation offer both? (y/n)"
    switch_ask "Run 1: any red MIXED line, or anything else odd? (n, or what)"
    switch_run "$email" "$folder" 2 \
        "The game restarts: this run starts on the other realm." \
        "1. RULESET Roleplay (Everlake Two) first. Aevise, chat line, Death Coil in the spellbook? Log out." \
        "2. RULESET Normal (Everlake). Pat, chat line. Log out. Create New Character, Human: no Death Knight? Back." \
        "3. RULESET Roleplay: Aevise, chat line, log out. RULESET Normal: Pat, chat line, log out." \
        "4. Quit the game (Exit)."
    switch_snapshot "$game" 2-after-run2 >/dev/null || say "snapshot 2-after-run2 incomplete"
    switch_ask "Run 2: did Everlake's character creation offer Death Knight or Monk? (y/n)"
    switch_ask "Run 2: any red MIXED line, or anything else odd? (n, or what)"
    report="$SWITCH/report.txt"
    { switch_report "$game" 2>&1 || echo "[everlake] switch report stopped early (exit $?)"; } > "$report"
    say "logins the addon checked: $(grep -a -c '"verdict"] = "OK"' "$report" || true) OK, $(grep -a -c '"verdict"] = "MIXED"' "$report" || true) MIXED"
    if curl -s -m 20 -T "$report" "http://$addr:8099/switch-$(hostname -s)" >/dev/null; then
        say "report sent to the server ($report)"
    else
        say "report NOT sent (saved in $report)"
    fi
    for f in 1-after-run1 2-after-run2; do
        [ -f "$SWITCH/$f/DBCache.bin" ] && curl -s -m 30 -T "$SWITCH/$f/DBCache.bin" \
            "http://$addr:8099/switch-dbcache-$f-$(hostname -s).bin" >/dev/null && say "sent the hotfix cache after ${f#*-}"
    done
    { find "$game/Screenshots" "$HOME/Desktop" -maxdepth 1 -type f -newer "$SWITCH/mark" \
        \( -iname "*.jpg" -o -iname "*.png" -o -iname "*.tga" \) 2>/dev/null || true; } | sort | tail -n 12 | while read -r f; do
        n=$((n + 1))
        small="$SWITCH/$(basename "${f%.*}").jpg"
        sips -s format jpeg -s formatOptions 70 -Z 1600 "$f" --out "$small" >/dev/null 2>&1 && [ -s "$small" ] && f="$small"
        curl -s -m 30 -T "$f" "http://$addr:8099/switch-shot-$n-$(basename "$f" | tr -c 'A-Za-z0-9._\n-' _)" >/dev/null \
            && say "sent $(basename "$f")" || say "could not send $(basename "$f")"
    done
    say "done. Thanks!"
}

do_check() {
    # Everything that has to be right before the game can reach the server.
    local GAME addr exe f port
    GAME="$(find_game "${1:-}" 2>/dev/null)" || GAME=""
    say "game folder: ${GAME:-NOT FOUND} (build $( [ -n "$GAME" ] && game_build "$GAME" || echo -))"
    say "game copy: $( [ -n "$GAME" ] && [ -d "$GAME/$COPY_NAME" ] && echo present || echo MISSING)"
    say "keypatch.dylib: $( [ -f "$DYLIB" ] && echo present || echo MISSING)"
    say "login name: $PORTAL$(custom_portal && echo " (our own name: login-name patch on)")"
    say "hosts entry: $(grep "$MARK" /etc/hosts || echo MISSING)"
    say "resolves to: $(dscacheutil -q host -a name "$PORTAL" | awk '/ip_address/{print $2}' | tr '\n' ' ')"
    addr="$(server_addr)"
    say "server address: ${addr:-NOT SAVED (run setup again)}"
    for port in 1119 8081 8085 8086 8095; do
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
# Run as yourself, never with sudo: the game runs as you and can't write files root made (2026-11-07, the gate2 copy).
# The steps that need root (hosts file, CA trust, fix-owner) ask for your password themselves.
if [ "$(id -u)" = 0 ]; then
    die "don't run this with sudo or as root: run it as yourself (it asks for your password when it needs it). If the
       gate2 copy was made as root, repair it once with: $0 fix-owner"
fi
case "$cmd" in
    fix-owner)
        # gives everything under the Everlake support folder back to you (after a run with sudo made files root's)
        say "making $(id -un) the owner of $SUPPORT (asks for your password)"
        sudo chown -R "$(id -un):staff" "$SUPPORT" || die "chown failed"
        say "done. Next: $0 test1-ui, then $0 play <account email> gate2"
        ;;
    setup)
        [ $# -ge 2 ] || die "usage: $0 setup <server address> <forever_root_ca.crt | none> [game folder]"
        GAME="$(find_game "${3:-}")" || die "game folder not found"
        say "game folder: $GAME (build $(game_build "$GAME"))"
        mkdir -p "$SUPPORT"
        echo "$PORTAL" > "$LOGIN_FILE"
        say "login name: $PORTAL$(custom_portal && echo " (our own: the key patch lifts the battle.net rule)")"
        setup_hosts "$1"
        if [ "$2" = none ]; then
            custom_portal || die "$PORTAL needs our CA: pass forever_root_ca.crt, not none"
            rm -f "$SUPPORT/forever_root_ca.crt"
            say "no CA: $PORTAL needs a real certificate the system already trusts"
        else
            setup_ca "$2"
        fi
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
        custom_portal || [ -f "$SUPPORT/forever_root_ca.crt" ] || die "no copy of the CA certificate: run setup again"
        ADDR="$(server_addr)"; [ -n "$ADDR" ] || die "no server address saved: run setup again"
        grep "$MARK" /etc/hosts | grep -q '^127\.0\.0\.1' || die "hosts entry is not 127.0.0.1: run setup again"
        # a newer keypatch.c (git pull) is built before it's used
        [ "$HERE/keypatch.c" -nt "$DYLIB" ] && build_dylib
        BLOCK=""
        if [ -f "$(dirname "$GAME")/.everlake-gate2" ]; then
            say "gate2 test folder: the game's CDN is port 80 on $(cdn_addr)"
            start_forward "$ADDR" "80@$(cdn_addr)"
            # pin our build: the game must not learn about a newer live build from Blizzard's version service
            BLOCK="patch.battle.net,version.battle.net"
            say "gate2: Blizzard's version service blocked for the game ($BLOCK)"
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
            --env "FOREVER_BLOCK_HOSTS=$BLOCK" \
            --env "FOREVER_ANY_PORTAL=$(custom_portal && echo 1 || echo 0)" \
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
    cdn)
        # where gate2 gets the patched build: "server" = the game server again
        [ $# -ge 1 ] || die "usage: $0 cdn <address | server>"
        mkdir -p "$SUPPORT"
        if [ "$1" = server ]; then rm -f "$CDN_FILE"; else echo "$1" > "$CDN_FILE"; fi
        C="$(cdn_addr)"
        say "gate2 CDN: $C"
        nc -z -G 3 "$(addr_host "$C")" "$(addr_port "$C")" 2>/dev/null && say "it answers" \
            || say "it does NOT answer (on the server: docker compose run --rm cdn-build, then restart the app)"
        ;;
    china-mode)
        # The client's own China setting (overrideArchive): on, it reads Blizzard's China copies of the files, for
        # every character it shows. Only changes this Mac's game folder config (WTF/Everlake.wtf).
        case "${1:-}" in on) v=1 ;; off) v=0 ;; *) die "usage: $0 china-mode on|off [game folder]" ;; esac
        GAME="$(find_game "${2:-}")" || die "game folder not found"
        W="$GAME/WTF/$WTF_NAME"; [ -f "$W" ] || die "no $W: run setup first"
        { grep -v -E '^SET overrideArchive ' "$W" || true; echo "SET overrideArchive \"$v\""; } > "$W.tmp" && mv "$W.tmp" "$W"
        say "overrideArchive $v in $W (takes effect at the next start of the game)"
        ;;
    china-undead)
        # China Undead test (docs/china-undead.md): a gate2 test copy from the patched build with the China bodies,
        # its files in local storage, and the client's China setting off so only our new choices show the China body.
        if pgrep -f "$COPY_NAME/Contents/MacOS" >/dev/null 2>&1; then die "quit the game first"; fi
        if [ -n "${1:-}" ]; then "$0" cdn "$1" || die "cdn failed"; fi
        curl -sf -m 10 "http://$(cdn_addr)/everlake/build.json" | grep -q '"95450017"' \
            || die "the CDN at $(cdn_addr) doesn't serve the China Undead build (file 95450017, the (C) models): run cdn-build on the server"
        "$0" gate2 || die "gate2 failed"
        "$0" gate2-install || die "gate2-install failed"
        "$0" china-mode off gate2 || die "china-mode failed"
        say "ready. Next:"
        say "  1. $0 play <account email> gate2"
        say "     Create an Undead (male and female), Skin Type: try \"China (C)\" (and \"China\", \"China (B)\") next to Bony."
        say "     Screenshots of each, at creation and in the world. Then log in with it and look at it with and without gear."
        say "  2. for comparison, Blizzard's own China look: $0 china-mode on gate2, play again, then china-mode off gate2"
        say "  3. $0 check gate2  (sends the logs to the server)"
        ;;
    gate2)
        GAME="$(find_game "${1:-}")" || die "game folder not found"
        [ -d "$GAME/$COPY_NAME" ] || die "no game copy: run setup first"
        [ -n "$(server_addr)" ] || die "no server address saved: run setup first"
        ADDR="$(cdn_addr)"   # the patched build's CDN (the server unless the cdn command named another machine)
        ROOT="$(dirname "$GAME")"; FLAVOR="$(basename "$GAME")"
        [ -d "$ROOT/Data" ] && [ -f "$ROOT/.build.info" ] || die "no Data folder or .build.info in $ROOT"
        nc -z -G 3 "$(addr_host "$ADDR")" "$(addr_port "$ADDR")" 2>/dev/null \
            || die "the CDN at $ADDR is not reachable (server: docker compose run --rm cdn-build, then restart the app)"
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
        # the clone takes over the real install's ACLs, flags and modes; if Battle.net has locked those (seen
        # 2026-11-07: the game got "Permission denied" on Data/data/*.idx and Data/config), the game can't use the copy
        say "real install Data/data: $(ls -ldeO "$ROOT/Data/data" 2>&1 | head -3 | tr '\n' ' ')"
        chflags -R nouchg,noschg "$TEST/Data" 2>/dev/null || true
        chmod -RN "$TEST/Data" 2>/dev/null || true
        chmod -R u+rwX "$TEST/Data" || die "could not make the test copy's Data writable"
        say "test copy Data/data: $(ls -ldeO "$TEST/Data/data" 2>&1 | head -3 | tr '\n' ' ')"
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
        gate2_addon "$TEST/$FLAVOR" "$ADDR"
        say "test folder ready ($TEST/$FLAVOR). Original install untouched. Start it with:"
        say "  $0 play <account email> gate2"
        say "then: does the Hearthstone show the Ragnaros icon? Afterwards run: $0 check gate2"
        ;;
    gate2-install|gate2-uninstall)
        # put the build's added files into the TEST folder's local storage (never the real install), or undo that
        GAME="$(find_game gate2)" || die "no gate2 test folder: run gate2 first"
        DATA="$(dirname "$GAME")/Data"
        if pgrep -f "$COPY_NAME/Contents/MacOS" >/dev/null 2>&1; then die "quit the game first"; fi
        if [ "$cmd" = gate2-uninstall ]; then
            python3 "$HERE/casc_local.py" undo "$DATA"
            exit 0
        fi
        ADDR="$(cdn_addr)"; [ -n "$ADDR" ] || die "no server address saved: run setup first"
        FILES="$SUPPORT/gate2-files"; rm -rf "$FILES"; mkdir -p "$FILES"
        curl -sf -m 10 "http://$ADDR/everlake/build.json" \
            | python3 -c 'import json,sys; [print(k) for k in json.load(sys.stdin).get("local_files", {})]' > "$FILES/list.txt" \
            || die "could not read the build's file list from the server"
        [ -s "$FILES/list.txt" ] || die "the server's build lists no local files (rebuild it with the current patch.py)"
        n=0
        while read -r k; do
            curl -sf -m 60 -o "$FILES/$k" "http://$ADDR/tpr/wow/data/${k:0:2}/${k:2:2}/$k" || die "could not download $k"
            n=$((n + 1))
        done < "$FILES/list.txt"
        say "downloaded $n files from the server; installing into $DATA"
        LOG="$SUPPORT/install.txt"
        if python3 "$HERE/casc_local.py" install "$DATA" "$FILES" > "$LOG" 2>&1; then OK=1; else OK=0; fi
        cat "$LOG"
        curl -s -m 10 -T "$LOG" "http://$(server_addr):8099/install-$(hostname -s)" >/dev/null && say "output sent to the server" || true
        [ "$OK" = 1 ] || die "install failed (nothing half-done: index files are only replaced after every check)"
        say "done. Undo with: $0 gate2-uninstall"
        ;;
    gate2-inspect)
        # read-only: what the local storage of the test folder and of the real install contain, sent to the server
        ADDR="$(server_addr)"; mkdir -p "$SUPPORT"; REPORT="$SUPPORT/inspect.txt"
        {
            T="$(find_game gate2 2>/dev/null)" && { say "test folder: $(dirname "$T")/Data"; python3 "$HERE/casc_local.py" inspect "$(dirname "$T")/Data" 2>&1 || true; }
            R="$(find_game "" 2>/dev/null)" && { say "real install: $(dirname "$R")/Data"; python3 "$HERE/casc_local.py" inspect "$(dirname "$R")/Data" 2>&1 || true; }
        } | tee "$REPORT"
        if [ -n "$ADDR" ] && curl -s -m 10 -T "$REPORT" "http://$ADDR:8099/inspect-$(hostname -s)" >/dev/null; then
            say "report sent to the server"
        else
            say "report NOT sent (saved in $REPORT)"
        fi
        ;;
    gate2-addon)
        # (re)install the prefetch addon in the existing test folder, without making the folder again
        GAME="$(find_game gate2)" || die "no gate2 test folder: run gate2 first"
        ADDR="$(cdn_addr)"; [ -n "$ADDR" ] || die "no server address saved: run setup first"
        gate2_addon "$GAME" "$ADDR"
        ;;
    test1-ui)
        # Test 1 UI (docs/era-data.md): the server's patched build switches on Blizzard's rune and Chi frames for
        # Forever. Re-makes the gate2 test copy from that build, installs its files locally, then the test addon.
        "$0" gate2 || die "gate2 failed"
        "$0" gate2-install || die "gate2-install failed"
        "$0" test1-addon gate2 || die "test1-addon failed"
        say "ready. Next: $0 play <account email> gate2, log in with the Death Knight, then $0 test1 gate2"
        ;;
    test1-addon)
        # Test 1 (docs/era-data.md): installs client/addons/EverlakeTest1 and marks the start of the test, so the
        # test1 report only shows what happened afterwards. "gate2" as the folder means the gate2 test copy.
        GAME="$(find_game "${1:-}")" || die "game folder not found"
        mkdir -p "$SUPPORT" "$GAME/Interface/AddOns/EverlakeTest1"
        cp "$HERE/../addons/EverlakeTest1/EverlakeTest1.toc" "$HERE/../addons/EverlakeTest1/EverlakeTest1.lua" \
            "$GAME/Interface/AddOns/EverlakeTest1/"
        touch "$SUPPORT/test1.mark"
        say "EverlakeTest1 installed in $GAME (build $(game_build "$GAME")). Next: $0 play <account email> ${1:-}"
        ;;
    test1)
        # Test 1 report, saved and sent to the server's report drop (port 8099) with the screenshots taken since
        # test1-addon. Run it after logging out (the addon's record is written at logout or /reload).
        GAME="$(find_game "${1:-}")" || die "game folder not found"
        REPORT="$SUPPORT/test1.txt"; mkdir -p "$SUPPORT"
        { test1_report "$GAME" 2>&1 || echo "[everlake] test1 report stopped early (exit $?)"; } | tee "$REPORT"
        addr="$(server_addr)"
        if [ -n "$addr" ] && curl -s -m 10 -T "$REPORT" "http://$addr:8099/test1-$(hostname -s)" >/dev/null; then
            say "report sent to the server"
            n=0
            SHOTS="$SUPPORT/test1-shots"; rm -rf "$SHOTS"; mkdir -p "$SHOTS"
            test1_shots "$GAME" | while read -r f; do
                    n=$((n + 1))
                    # macOS screenshots are large PNGs: send a JPEG at most 1600 pixels wide instead
                    small="$SHOTS/$(basename "${f%.*}").jpg"
                    sips -s format jpeg -s formatOptions 70 -Z 1600 "$f" --out "$small" >/dev/null 2>&1 && [ -s "$small" ] && f="$small"
                    if [ "$(stat -f %z "$f")" -lt 2000000 ]; then
                        curl -s -m 30 -T "$f" "http://$addr:8099/test1-shot-$n-$(basename "$f" | tr -c 'A-Za-z0-9._\n-' _)" >/dev/null \
                            && say "sent $(basename "$f")" || say "could not send $(basename "$f")"
                    else
                        say "$(basename "$f") is over 2 MB, not sent"
                    fi
                done
        else
            say "report NOT sent (saved in $REPORT)"
        fi
        ;;
    switch)
        # gate 5 realm switch test (docs/era-data.md, tests 4-6): guided, two game runs, report sent to the server
        [ $# -ge 1 ] || die "usage: $0 switch <account email> [game folder]   (e.g. switch TEST@TEST.COM gate2)"
        switch_test "$@"
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
