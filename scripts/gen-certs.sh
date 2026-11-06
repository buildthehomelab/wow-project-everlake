#!/bin/sh
# Creates your own root CA (restricted to *.actual.battle.net) and a server certificate
# for trinity.actual.battle.net, signed by it.
#
#   certs/forever.cert.pem  certificate chain  -> used by bnetserver
#   certs/forever.key.pem   server private key -> used by bnetserver
#   certs/ca/forever_root_ca.crt   CA certificate -> give it to players (import into "Trusted Root CAs")
#   certs/ca/forever_root_ca.key   CA private key -> NEVER share it
#
# Usage: ./scripts/gen-certs.sh [days]   (default 825 days)
set -eu

DAYS="${1:-825}"
HOST=trinity.actual.battle.net
DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
CA="$DIR/ca"
mkdir -p "$CA"
umask 077

if [ ! -f "$CA/forever_root_ca.key" ]; then
    echo "== new root CA"
    openssl req -x509 -newkey rsa:4096 -sha256 -nodes -days 3650 \
        -keyout "$CA/forever_root_ca.key" -out "$CA/forever_root_ca.crt" \
        -subj "/CN=Forever Private Root CA" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -addext "nameConstraints=critical,permitted;DNS:actual.battle.net"
else
    echo "== reusing existing root CA $CA/forever_root_ca.crt"
fi

echo "== server certificate for $HOST"
openssl req -newkey rsa:2048 -sha256 -nodes \
    -keyout "$DIR/forever.key.pem" -out "$CA/server.csr" -subj "/CN=$HOST"

cat > "$CA/server.ext" <<EXT
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:$HOST,DNS:*.actual.battle.net
EXT

openssl x509 -req -in "$CA/server.csr" -CA "$CA/forever_root_ca.crt" -CAkey "$CA/forever_root_ca.key" \
    -CAcreateserial -days "$DAYS" -sha256 -extfile "$CA/server.ext" -out "$CA/server.crt"

cat "$CA/server.crt" "$CA/forever_root_ca.crt" > "$DIR/forever.cert.pem"
rm -f "$CA/server.csr" "$CA/server.ext"
# readable by the container user (root) through the read-only mount
chmod 644 "$DIR/forever.cert.pem" "$CA/forever_root_ca.crt"
chmod 600 "$DIR/forever.key.pem" "$CA/forever_root_ca.key"

openssl verify -CAfile "$CA/forever_root_ca.crt" "$CA/server.crt"
echo
echo "Done. Give players: $CA/forever_root_ca.crt (never the .key)"
