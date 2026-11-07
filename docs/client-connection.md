# Connecting a Forever client

Notes from reading [jibay442/forever_docker](https://github.com/jibay442/forever_docker)'s launcher (`app/`) and the
Forever 1.60.1.70790 install manifest. Not tried against this server yet.

A player's computer needs three things before the stock client will log in here instead of at Blizzard.

## 0. macOS: Local Network permission

Since macOS 15, an app needs the *Local Network* permission to connect to other machines on the LAN. The
re-signed game copy is blocked without a prompt, even with "World of Warcraft" switched on under Privacy &
Security: its `Connection.log` shows `ERROR_NETWORK_MODULE_SOCKET_CLOSED (1016)` 15 ms after
`Battle.net logon requested`, and nothing reaches the server. Terminal has the permission, and 127.0.0.1 needs
none, so `client/macos/forward.py` (started by `everlake-client.sh play`) listens on 127.0.0.1:1119/8081/8085 and
passes the bytes to the server. TLS stays end to end. For that, the hosts entry points at 127.0.0.1 and the
server's realm address (`PUBLIC_ADDRESS` / `REALM_LOCAL_ADDRESS`) is 127.0.0.1 too. A server reached over the
internet (not the LAN) shouldn't need any of this.

## 1. Hosts entry

The client logs in at `*.actual.battle.net`. A hosts entry points the login name at this server:

```
<server address>  trinity.actual.battle.net
```

bnetserver also has to resolve that name itself, which is why `docker-compose.yml` gives it an `extra_hosts` line.

## 2. Our CA, trusted

bnetserver speaks TLS with a certificate for `trinity.actual.battle.net`, signed by our own root CA from
`scripts/gen-certs.sh`. The CA has a name constraint (`permitted;DNS:actual.battle.net`), so trusting it on a
player's computer can't be used to fake any other site.

- Windows: import `certs/ca/forever_root_ca.crt` into *Trusted Root Certification Authorities*.
- macOS: `security add-trusted-cert -d -r trustRoot -k ~/Library/Keychains/login.keychain-db forever_root_ca.crt`.

Never hand out `certs/ca/forever_root_ca.key`.

## 3. The server's key in the client

When a character enters the world, the server signs `EnterEncryptedMode` with an Ed25519 key and the client checks
the signature against one of 12 public keys it holds in memory, one per region group. The server uses region
group 8 (`Network.EnterEncryptedModeRegionGroup`, set by the entrypoint), so entry 8 has to hold the server's
public key.

The key store is a heap array of 12 entries of 40 bytes each: `u32 id (1..12)`, a 32-byte key, a `u8` flag and
3 bytes of padding. forever_docker's patcher finds it by searching memory for Blizzard's first key and checking the
whole 480-byte pattern, then writes our key into entry 8. Nothing depends on code addresses, so it should carry
over from build to build. The game files are never changed.

The core still signs with TrinityCore's stock key. Its public half is
`02596F0D0C061A8B30745988FD72C59E29EC367FB0F341F28E0F08D037BAFC69`. Our own key pair is a later step.

### Per system

- **Windows**: `ReadProcessMemory` / `WriteProcessMemory` on the game process.
- **macOS**: the game is signed with the hardened runtime, so another process can't write into it. forever_docker
  makes an ad-hoc re-signed copy of the app without the hardened runtime and loads a small dylib
  (`app/macos/keypatch.c`) with `DYLD_INSERT_LIBRARIES`, which patches the key from inside. Known issue: the very
  first realm login of a session can fail ("server identity check failed"); Reconnect works.

## Our own login name instead of battle.net (proposed, not tested on the client yet)

Steps 1 and 2 exist because the login name has to be a `*.actual.battle.net` one, and no public certificate authority
issues certificates for battle.net. With a name of our own, players install nothing: a real DNS record and a real
certificate (e.g. Let's Encrypt) replace the hosts entry and our CA. Only the in-memory patches remain, which the
launcher does anyway.

**Why the client refuses other names.** Read in the Windows `Wow.exe` of 1.60.1.70790 (from Blizzard's CDN, not run):

- `.data` holds a table of Blizzard's login domains, one entry each of {domain ending, its length, sign-in page}:
  `.actual.battle.net` (18), `.actual.battlenet.com.cn` (24), `.bgs.battle.net` (15), `.dev.bgs.cn.battle.net` (22),
  plus integration and staging ones.
- The length beside each ending says the login name must *end with* one of them.
- Arctium's launcher (MIT, [copy on GitHub](https://github.com/brian8544/Arctium-Launcher), `src/Patterns/Common.cs`
  `Portal`) lets custom servers in by overwriting `.actual.battle.net` in the running game with zeros.

**The patch.** `FOREVER_ANY_PORTAL=1` makes `client/macos/keypatch.c` do the same before the game starts:

1. It finds `.actual.battle.net` as a string of its own in the game's data.
2. It sets the length of the table entry pointing at it to 0.
3. It blanks the ending, so every login name ends with it.

`everlake-client.sh` turns it on whenever the login name isn't a `*.actual.battle.net` one. Checked only on a stand-in
program with the same table; the real client is next. Arctium also patches a certificate name check for some clients
(`CertCommonName`); whether Forever needs that too, only the test will tell. Windows needs the same write in its
key patcher.

**The names (proposed):**

| Name | Points at | Used for |
|---|---|---|
| `login.realm.example.com` | the login server (bnetserver, ports 1119 and 8081) | `LOGIN_HOSTNAME`, the name the game logs in at |
| `forever.realm.example.com` | that realm's worldserver | the realm's `PUBLIC_ADDRESS` (`realmlist.address`) |
| `classic.realm.example.com`, `retail.realm.example.com` | their worldservers, later | the same |

- The login server looks realm addresses up by DNS (`RealmList.cpp`) and hands the client an IP. So realm names need
  no client patch.
- The login server hands the client the login *name* (`LoginRESTService.cpp`, `HandleGetPortal`). That's why the
  login name is the one the client checks.
- One wildcard certificate, `*.realm.example.com`, covers them all. Let's Encrypt issues wildcards only through a DNS
  challenge.

**Server settings** (`.env`):

```sh
LOGIN_HOSTNAME=login.realm.example.com
PUBLIC_ADDRESS=forever.realm.example.com
CERTS_DIR=/path/to/certificate/files   # real files, not symlinks into another folder (the container can't follow those)
CERT_FILE=fullchain.pem
KEY_FILE=privkey.pem
```

The login server reads the certificate at start, so it needs a restart after each renewal (every 90 days for Let's
Encrypt).

**On the Mac mini** (the LAN still needs the forwarder, see 0):

```sh
EVERLAKE_LOGIN_HOST=login.realm.example.com ./client/macos/everlake-client.sh setup <server address> none
./client/macos/everlake-client.sh play <account email>
```

`keypatch.log` then says how many endings and table lengths were blanked.
- **Passes when** the game logs in and enters the world with no CA trusted.
- **If the client refuses the name** (a "can't connect" before any request reaches the server), the table check
  isn't the only one.
- **If TLS fails**, the certificate name check is the next suspect.

## What changed since forever_docker

forever_docker was written for the beta. The live Forever build 70790 differs:

| | Beta (forever_docker) | Live 1.60.1.70790 |
|---|---|---|
| Windows exe | `WowB.exe` | `Wow.exe` (plus `Wow-ARM64.exe`) |
| macOS app | `World of Warcraft Beta.app` | `World of Warcraft.app` |
| Folder | `_classic_beta_` | `_forever_` |
| CDN product | `wow_classic_beta` | `wowf` |

So the launcher can't be used as it is. The key-store logic can be reused. In the end it belongs in our own launcher.
