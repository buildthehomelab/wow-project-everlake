#!/usr/bin/env python3
"""Mines QuestieTrace recordings that players shared (SavedVariables or /qlt export text) for what the public QuestieDB output leaves out.

    questietrace.py FILE [FILE ...] [--out out/questietrace.json]

FILE is either a character's SavedVariables file (WTF/Account/<account>/<realm>/<character>/SavedVariables/
QuestieTrace.lua: saved sessions are encoded, the live one is plain) or a text file holding `/qlt export` strings
(`!QuestieTrace:N!...!End:QuestieTrace:N!`). QuestieTrace is GPL-3.0 (github.com/Questie/QuestieTrace); its recording
already strips player names and player GUIDs.

What comes out, per session, with the client build and the time it was seen:
- merchants: every vendor window: npc id, slot, item id, name, price (copper), stack, numAvailable (limited stock),
  extended-cost flag, currency id. Not recorded by the addon: the extended-cost amounts and restock events.
- gossip: npc id, the greeting text and every option.
- trainers: which npcs opened a trainer window (the addon records no service list).
- quest_dialogs: quest id, the giver (npc or object), title, quest text, objectives, progress and reward text.
- loot: every loot window: source creature/object ids, item id, name, quantity, quality.
The decoding follows QuestieTrace's own (tools/corrections-extractor/src/core/trace-data/decode.ts and cbor.ts).
"""
import argparse
import json
import math
import os
import re
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lua_data  # noqa: E402

PRINT_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789()"
SIX_BIT = {c: i for i, c in enumerate(PRINT_ALPHABET)}
EXPORT = re.compile(r"!QuestieTrace:(\d+)!([^!]*)!End:QuestieTrace:\1!")
MAX_CBOR = 512 << 20


# ---------------------------------------------------------------- decoding

def decode_for_print(text):
    """LibDeflate:DecodeForPrint: 4 characters -> 3 bytes, little-endian 6-bit groups; whitespace ignored."""
    clean = re.sub(r"\s+", "", text)
    if len(clean) == 1:
        raise ValueError("payload is not valid print-encoded data")
    out, cache, bits = bytearray(), 0, 0
    for ch in clean:
        if ch not in SIX_BIT:
            raise ValueError(f"payload is not valid print-encoded data (character {ch!r})")
        cache |= SIX_BIT[ch] << bits
        bits += 6
        while bits >= 8:
            out.append(cache & 0xFF)
            cache >>= 8
            bits -= 8
    return bytes(out)


class _Cbor:
    """The subset BlizzardCBOR writes: definite lengths, no tags, false/true/null/undefined, half/single/double floats."""

    def __init__(self, data):
        self.d, self.i = data, 0

    def read(self):
        if self.i >= len(self.d):
            raise ValueError("truncated CBOR")
        b = self.d[self.i]
        self.i += 1
        major, info = b >> 5, b & 31
        if major == 7:
            if info == 20:
                return False
            if info == 21:
                return True
            if info in (22, 23):
                return None
            if info == 25:
                v = struct.unpack_from(">e", self.d, self.i)[0]
                self.i += 2
                return v
            if info == 26:
                v = struct.unpack_from(">f", self.d, self.i)[0]
                self.i += 4
                return v
            if info == 27:
                v = struct.unpack_from(">d", self.d, self.i)[0]
                self.i += 8
                return v
            raise ValueError(f"unsupported CBOR simple value {info}")
        n = self.length(info)
        if major == 0:
            return n
        if major == 1:
            return -1 - n
        if major in (2, 3):
            raw = self.d[self.i:self.i + n]
            self.i += n
            try:                                        # Lua strings are bytes; the addon's text is UTF-8
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1")
        if major == 4:
            return [self.read() for _ in range(n)]
        if major == 5:
            out = {}
            for _ in range(n):
                k = self.read()
                out[str(int(k)) if isinstance(k, float) and k.is_integer() else str(k)] = self.read()
            return out
        raise ValueError(f"unsupported CBOR major type {major}")

    def length(self, info):
        if info < 24:
            return info
        size = {24: 1, 25: 2, 26: 4, 27: 8}.get(info)
        if not size:
            raise ValueError("indefinite CBOR lengths are not used by QuestieTrace")
        v = int.from_bytes(self.d[self.i:self.i + size], "big")
        self.i += size
        return v


def decode_payload(encoded):
    raw = zlib.decompressobj(-15)
    cbor = raw.decompress(decode_for_print(encoded), MAX_CBOR)
    value = _Cbor(cbor).read()
    if not isinstance(value, (dict, list)):
        raise ValueError("decoded payload is not a table")
    return value


def sessions_in(path):
    """Every SessionRecord in a SavedVariables file or an export text, as plain Python tables."""
    text = open(path, encoding="utf-8", errors="replace").read()
    found = []
    for m in EXPORT.finditer(text):
        try:
            payload = decode_payload(m.group(2))
        except Exception as error:          # a cut-off or corrupt export is skipped, the rest still decode
            print(f"{path}: an export did not decode ({type(error).__name__}: {error})", file=sys.stderr)
            continue
        found += as_list(payload.get("sessions")) if isinstance(payload, dict) and "sessions" in payload else [payload]
    if "QuestieTraceCharacter" in text:
        sv = lua_data.tables(text).get("QuestieTraceCharacter") or {}
        for entry in (sv.get("sessions") or []) if isinstance(sv.get("sessions"), list) else (sv.get("sessions") or {}).values():
            if isinstance(entry, dict) and "encoded" in entry:
                try:
                    decoded = decode_payload(entry["encoded"])     # a SessionRecord, or an export holding sessions
                except Exception as error:
                    print(f"{path}: a saved session did not decode ({type(error).__name__}: {error})", file=sys.stderr)
                    continue
                found += as_list(decoded.get("sessions")) if isinstance(decoded, dict) and "sessions" in decoded else [decoded]
            elif isinstance(entry, dict) and "events" in entry:
                found.append(entry)
        if isinstance(sv.get("currentSession"), dict):
            found.append(sv["currentSession"])
    return [s for s in found if isinstance(s, dict) and "events" in s]


# ---------------------------------------------------------------- reading a session

def as_list(v):
    """Lua arrays arrive as lists, or as dicts keyed "1".."n" (with an "n" field for packed returns)."""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        n = v.get("n")
        keys = [k for k in v if k != "n" and re.fullmatch(r"\d+", k)]
        size = int(n) if isinstance(n, (int, float)) else (max(map(int, keys)) if keys else 0)
        return [v.get(str(i)) for i in range(1, size + 1)]
    return []


def stream(session, name, *params):
    node = (session.get("functions") or {}).get(name)
    for p in params:
        if isinstance(node, list) and isinstance(p, int) and node and not (isinstance(node[0], dict) and "t" in node[0]):
            node = node[p - 1] if 0 < p <= len(node) else None     # index-keyed streams written as a CBOR array
        elif isinstance(node, dict):
            node = node.get(str(p))
        else:
            return []
    if isinstance(node, dict) and "1" in node and isinstance(node["1"], dict) and "t" in node["1"]:
        node = as_list(node)
    return node if isinstance(node, list) else []


def value_at(entries, t, tp_limit):
    """The stream's value at an event: the last sample at or before the event's frame, before the next event."""
    best = None
    for e in entries:
        et, etp = e.get("t", 0), e.get("tp", 0)
        if et < t or (et == t and etp <= tp_limit):
            best = e
        else:
            break
    return None if best is None else best.get("v")


def guid_id(guid):
    """Creature-0-<server>-<instance>-<zone>-<npcId>-<spawn> -> ("creature", npcId); GameObject likewise."""
    if not isinstance(guid, str):
        return None, None
    parts = guid.split("-")
    kind = {"Creature": "creature", "Vehicle": "creature", "GameObject": "gameobject", "Item": "item"}.get(parts[0])
    if kind and len(parts) >= 6 and parts[5].isdigit():
        return kind, int(parts[5])
    return None, None


def item_id(link):
    m = re.search(r"\|Hitem:(\d+)", link or "") or re.search(r"item:(\d+)", link or "")
    return int(m.group(1)) if m else None


def mine(session):
    events = as_list(session.get("events"))
    build = as_list(session.get("buildInfo"))
    name = session.get("name")
    out = {k: [] for k in ("merchants", "gossip", "trainers", "quest_dialogs", "loot")}
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        e, t, tp = ev.get("e"), ev.get("t", 0), ev.get("tp", 0)
        nxt = events[i + 1] if i + 1 < len(events) else None
        limit = nxt.get("tp", math.inf) if isinstance(nxt, dict) and nxt.get("t") == t else math.inf
        at = lambda fn, *p: value_at(stream(session, fn, *p), t, limit)  # noqa: E731
        seen = {"session": name, "build": build[1] if len(build) > 1 else None, "t": t}
        if e == "MERCHANT_SHOW":
            kind, npc = guid_id(at("UnitGUID", "npc"))
            count = at("GetMerchantNumItems") or 0
            for slot in range(1, int(count) + 1):
                info = as_list(at("GetMerchantItemInfo", slot))
                modern = at("C_MerchantFrame.GetItemInfo", slot) or {}
                out["merchants"].append(dict(seen, npc=npc, npc_kind=kind, slot=slot, item=item_id(at("GetMerchantItemLink", slot)),
                    name=(info[0] if info else None) or modern.get("name"), price=info[2] if len(info) > 2 else modern.get("price"),
                    stack=info[3] if len(info) > 3 else modern.get("stackCount"), available=info[4] if len(info) > 4 else modern.get("numAvailable"),
                    purchasable=info[5] if len(info) > 5 else modern.get("isPurchasable"),
                    extended_cost=info[7] if len(info) > 7 else modern.get("hasExtendedCost"),
                    currency=info[8] if len(info) > 8 else modern.get("currencyID"), spell=info[9] if len(info) > 9 else modern.get("spellID")))
        elif e == "GOSSIP_SHOW":
            kind, npc = guid_id(at("UnitGUID", "npc"))
            out["gossip"].append(dict(seen, npc=npc, npc_kind=kind, text=at("C_GossipInfo.GetText"),
                                      options=as_list(at("C_GossipInfo.GetOptions")) or at("C_GossipInfo.GetOptions")))
        elif e == "TRAINER_SHOW":
            kind, npc = guid_id(at("UnitGUID", "npc"))
            out["trainers"].append(dict(seen, npc=npc, npc_kind=kind))
        elif e in ("QUEST_DETAIL", "QUEST_PROGRESS", "QUEST_COMPLETE"):
            kind, giver = guid_id(at("UnitGUID", "questnpc") or at("UnitGUID", "npc"))
            out["quest_dialogs"].append(dict(seen, event=e, quest=at("GetQuestID"), giver=giver, giver_kind=kind,
                                             title=at("GetTitleText"), text=at("GetQuestText"), objectives=at("GetObjectiveText"),
                                             progress=at("GetProgressText"), reward=at("GetRewardText")))
        elif e in ("LOOT_READY", "LOOT_OPENED"):
            count = at("GetNumLootItems") or 0
            for slot in range(1, int(count) + 1):
                info = as_list(at("GetLootSlotInfo", slot))
                sources = as_list(at("GetLootSourceInfo", slot))
                ids = [guid_id(sources[j]) for j in range(0, len(sources), 2)]
                out["loot"].append(dict(seen, slot=slot, item=item_id(at("GetLootSlotLink", slot)), name=info[1] if len(info) > 1 else None,
                                        quantity=info[2] if len(info) > 2 else None, quality=info[4] if len(info) > 4 else None,
                                        sources=[{"kind": k, "id": x, "count": sources[j * 2 + 1] if j * 2 + 1 < len(sources) else None}
                                                 for j, (k, x) in enumerate(ids) if x]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default=os.path.join(HERE, "out", "questietrace.json"))
    args = ap.parse_args()
    total = {k: [] for k in ("merchants", "gossip", "trainers", "quest_dialogs", "loot")}
    sessions = 0
    for path in args.files:
        for s in sessions_in(path):
            sessions += 1
            for k, rows in mine(s).items():
                total[k] += rows
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as handle:
        json.dump(total, handle, indent=0, ensure_ascii=False)
    print(f"{sessions} sessions: " + ", ".join(f"{k} {len(v)}" for k, v in total.items()) + f" -> {os.path.relpath(args.out, HERE)}")


if __name__ == "__main__":
    main()
