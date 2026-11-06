# Connecting a Forever client

Notes from reading [jibay442/forever_docker](https://github.com/jibay442/forever_docker)'s launcher (`app/`) and the
Forever 1.60.1.70790 install manifest. Not tried against this server yet.

A player's computer needs three things before the stock client will log in here instead of at Blizzard.

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

## What changed since forever_docker

forever_docker was written for the beta. The live Forever build 70790 differs:

| | Beta (forever_docker) | Live 1.60.1.70790 |
|---|---|---|
| Windows exe | `WowB.exe` | `Wow.exe` (plus `Wow-ARM64.exe`) |
| macOS app | `World of Warcraft Beta.app` | `World of Warcraft.app` |
| Folder | `_classic_beta_` | `_forever_` |
| CDN product | `wow_classic_beta` | `wowf` |

So the launcher can't be used as it is. The key-store logic can be reused. In the end it belongs in our own launcher.
