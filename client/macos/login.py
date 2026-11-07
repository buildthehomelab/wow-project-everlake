#!/usr/bin/env python3
"""Logs in to an Everlake login server and hands the game a login ticket, the way Battle.net does.

    login.py <email> [--test]

Asks for the password, then:
  1. POST /bnetserver/login/          email + password -> ticket
  2. POST /bnetserver/launcher/remember/  ticket -> launcher token
  3. POST /bnetserver/launcher/login/     token -> fresh login ticket + game account name
  4. writes the ticket to the net.battle preferences (Launch Options/WoW), where the game reads it when started
     with -launcherlogin: WEB_TOKEN (encrypted, see below), GAME_ACCOUNT, CONNECTION_STRING.

WEB_TOKEN encryption (same scheme as jibay442/forever_docker app/src-tauri/src/macos.rs and
Shauren/tc-client-launcher): AES-128-CBC, zero IV, PKCS#7; key = PBKDF2-HMAC-SHA1(entropy XOR user name,
"someSalt", 1000 rounds, 16 bytes). Only the first 16 bytes of the user name count.

--test checks the encryption against forever_docker's reference values and exits.
"""
import getpass
import hashlib
import json
import os
import ssl
import subprocess
import sys
import urllib.request

PORTAL = "trinity.actual.battle.net"
BNET_PORT = 1119
REST_PORT = 8081
CA_FILE = os.path.expanduser("~/Library/Application Support/Everlake/forever_root_ca.crt")
ENTROPY = bytes([0xC8, 0x76, 0xF4, 0xAE, 0x4C, 0x95, 0x2E, 0xFE, 0xF2, 0xFA, 0x0F, 0x54, 0x19, 0xC0, 0x9C, 0x43])


def encrypt_ticket(ticket, user):
    password = bytearray(ENTROPY)
    for i, b in enumerate(user.encode()[:16]):
        password[i] ^= b
    key = hashlib.pbkdf2_hmac("sha1", bytes(password), b"someSalt", 1000, 16)
    out = subprocess.run(["openssl", "enc", "-aes-128-cbc", "-K", key.hex(), "-iv", "00" * 16, "-nosalt"],
                         input=ticket.encode(), capture_output=True, check=True).stdout
    return out


def self_test():
    cases = [("alice", "c648fac45e970e5481a51d09a47d3edf8d3fc929ff471e6fa7d8e6d900163ea6"),
             ("a-very-long-user-name-xyz", "83d39aad9ede31437dc7fe9083fdf5f88d1da8a4c1f527c9d7d8ef665964c200")]
    for user, want in cases:
        got = encrypt_ticket("TC-0123456789abcdef", user).hex()
        print(("ok  " if got == want else "BAD ") + user)
        if got != want:
            sys.exit(1)


def post(path, body=None, ticket=None):
    ctx = ssl.create_default_context(cafile=CA_FILE)
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(f"https://{PORTAL}:{REST_PORT}/bnetserver{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if ticket:
        import base64
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{ticket}:".encode()).decode())
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def main():
    if "--test" in sys.argv:
        self_test()
        return
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    email = sys.argv[1]
    password = os.environ.get("EVERLAKE_PASSWORD") or getpass.getpass(f"Everlake password for {email}: ")

    _, r = post("/login/", {"version": "1.0", "inputs": [
        {"input_id": "account_name", "value": email},
        {"input_id": "password", "value": password}]})
    ticket = r.get("login_ticket")
    if not ticket:
        sys.exit(f"login refused: {r.get('authentication_state') or r or 'wrong email or password'}")
    status, r = post("/launcher/remember/", ticket=ticket)
    token = r.get("token")
    if not token:
        sys.exit(f"launcher/remember refused ({status})")
    status, r = post("/launcher/login/", ticket=token)
    if status != 200 or not r.get("login_ticket"):
        sys.exit(f"launcher/login refused ({status})")
    accounts = [a.get("name") for a in r.get("game_accounts", []) if a.get("name")]
    account = accounts[0] if accounts else "WoW1"

    web_token = encrypt_ticket(r["login_ticket"], os.environ["USER"]).hex()
    for key, kind, value in [("Launch Options/WoW/WEB_TOKEN", "-data", web_token),
                             ("Launch Options/WoW/GAME_ACCOUNT", "-string", account),
                             ("Launch Options/WoW/CONNECTION_STRING", "-string", f"{PORTAL}:{BNET_PORT}")]:
        subprocess.run(["defaults", "write", "net.battle", key, kind, value], check=True)
    print(f"logged in as {email}, game account {account}")


if __name__ == "__main__":
    main()
