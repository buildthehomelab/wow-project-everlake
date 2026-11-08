#!/usr/bin/env python3
"""A hotfix kit that turns the Forever client's game tables into Classic Era's, for the Classic realm.

    python3 tools/era/classic_kit.py --cache <wago cache> --out <kit.json> [--max-rows N]
    python3 tools/era/hotfix_kit.py <kit.json> --schema ... --dbc ... --cache <wago cache> --out <file.sql>

The Classic test (docs/classic-on-forever.md): one realm sends Classic Era's spells, items and skills as hotfixes while
the Forever realm keeps Blizzard's rows. This writes the kit that hotfix_kit.py turns into SQL, for every row where
Classic Era differs from Forever, table by table:

  rows both builds have   the Forever row, with only the columns Classic changed set to Classic's values. Columns
                          that differ on almost every row only because of the engine (ENGINE_COLUMNS) keep Forever's.
  rows only Classic has   Classic's row; engine columns and columns Classic's layout lacks get the value most of
                          Forever's rows hold. Rows that hold nothing but their keys and engine columns are left out
                          (Classic keeps an empty SpellTargetRestrictions row for most spells; Forever doesn't).
                          Spell (the text) is always sent: the client drops a spell that has no Spell row
                          (Test 1, docs/era-data.md).
  rows only Forever has   left alone: the Classic realm's world never uses them.

Spell effect values: Classic stores BasePoints + DieSides (old style), Forever one float and a variance. DieSides 0 or
1 gives BasePoints + DieSides, variance 0; more gives the middle of the range and its spread (checked on 13,159 and
2,682 rows the builds share, 2026-11-08).

Model looks stay Forever's (user, 2026-11-08), so CreatureDisplayInfo is not in the kit. Map rows wait for Classic's
terrain.
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hotfix_kit import Wago  # noqa: E402

FOREVER = "1.60.1.70862"
CLASSIC = "1.15.9.70576"
FIRST_PUSH = 9600000

# Spells first, then skills, items and the world, so --max-rows keeps whole areas.
TABLES = ["SpellName", "Spell", "SpellMisc", "SpellEffect", "SpellLevels", "SpellPower", "SpellCooldowns",
          "SpellAuraOptions", "SpellCategories", "SpellClassOptions", "SpellReagents", "SpellEquippedItems",
          "SpellShapeshift", "SpellTargetRestrictions", "SpellInterrupts", "SpellXSpellVisual", "SkillLineAbility",
          "Item", "ItemSparse", "ItemEffect", "ItemSet", "AreaTable", "Faction", "FactionTemplate", "TaxiNodes"]

# Columns that differ on almost every shared row only because Forever runs a newer engine (measured 2026-11-08).
ENGINE_COLUMNS = {
    "SpellMisc": {"Attributes_15"},
    "SpellEffect": {"EffectBasePointsF", "Variance"},
    "SpellLevels": {"BaseLevel"},
    "SpellTargetRestrictions": {"ConeDegrees"},
    "SkillLineAbility": {"TradeSkillCategoryID", "TrivialSkillLineRankHigh", "TrivialSkillLineRankLow"},
    "ItemSparse": {"ExpansionID"},
    "AreaTable": {"MountFlags"},
    "TaxiNodes": {"Flags"},
}
# Columns that only link a row to its owner: a row with nothing else set is empty.
KEY_COLUMNS = {"ID", "SpellID", "DifficultyID", "ParentItemID", "ItemID"}


def number(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def same(a, b):
    if a == b:
        return True
    x, y = number(a), number(b)
    return x is not None and x == y


def is_set(v):
    """A non-zero number or a non-empty text."""
    n = number(v)
    return n != 0 if n is not None else v != ""


def text(v):
    """A number as the CSVs write it: 12.0 -> '12'."""
    return str(int(v)) if float(v).is_integer() else repr(v)


def effect_value(row):
    """Forever's (EffectBasePointsF, Variance) for a Classic SpellEffect row."""
    base, sides = int(row["EffectBasePoints"] or 0), int(row["EffectDieSides"] or 0)
    if sides <= 1:
        return base + sides, 0.0
    middle = base + (sides + 1) / 2
    return middle, ((sides - 1) / middle if middle else 0.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", required=True, help="wago.tools CSV cache (the same one hotfix_kit.py uses)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--forever", default=FOREVER)
    ap.add_argument("--classic", default=CLASSIC)
    ap.add_argument("--first-push", type=int, default=FIRST_PUSH)
    ap.add_argument("--max-rows", type=int, default=0, help="stop after this many rows (a smaller first step)")
    ap.add_argument("--tables", help="comma-separated subset of the tables, in the usual order")
    args = ap.parse_args()

    wago = Wago(args.cache)
    rows, total, summary = [], 0, []
    tables = [t for t in TABLES if not args.tables or t in args.tables.split(",")]
    for table in tables:
        f, c = wago.load(table, args.forever), wago.load(table, args.classic)
        if not f or not c:
            sys.exit("%s: no table on wago.tools for %s" % (table, args.forever if not f else args.classic))
        fh, ch = f[0], set(c[0])
        engine = ENGINE_COLUMNS.get(table, set())
        compare = [h for h in fh if h in ch and h not in engine and h != "ID"]
        fby, cby = wago.by(table, args.forever, "ID"), wago.by(table, args.classic, "ID")
        mode = {h: collections.Counter(r[h] for r in f[1]).most_common(1)[0][0] for h in fh}
        visuals = wago.by("SpellVisual", args.forever, "ID") if table == "SpellXSpellVisual" else None

        changed, changed_set, added, added_set, empty, no_visual = [], {}, [], {}, 0, 0
        for rid in sorted(cby):
            cr = cby[rid][0]
            if rid in fby:
                fr = fby[rid][0]
                over = {h: cr[h] for h in compare if not same(fr[h], cr[h])}
                if table == "SpellEffect":
                    value, variance = effect_value(cr)
                    if not same(fr["EffectBasePointsF"], value) or abs(float(fr["Variance"] or 0) - variance) > 1e-4:
                        over["EffectBasePointsF"], over["Variance"] = text(value), repr(round(variance, 8))
                if over:
                    changed.append(rid)
                    changed_set[str(rid)] = over
                continue
            if table != "Spell" and not any(is_set(cr[h]) for h in c[0]
                                             if h in fh and h not in KEY_COLUMNS and h not in engine):
                empty += 1
                continue
            if visuals is not None and int(cr["SpellVisualID"] or 0) not in visuals:
                no_visual += 1
                continue
            over = {h: mode[h] for h in fh if h != "ID" and (h in engine or h not in ch)}
            if table == "SpellEffect":
                value, variance = effect_value(cr)
                over["EffectBasePointsF"], over["Variance"] = text(value), repr(round(variance, 8))
            added.append(rid)
            added_set[str(rid)] = over

        for build, ids, sets in ((args.forever, changed, changed_set), (args.classic, added, added_set)):
            if args.max_rows and total + len(ids) > args.max_rows:
                ids = ids[:max(0, args.max_rows - total)]
                sets = {k: sets[k] for k in map(str, ids)}
            if ids:
                rows.append({"table": table, "build": build, "ids": ids, "set": sets})
                total += len(ids)
        summary.append("%-24s changed %6d  added %6d  (empty rows left out %d%s)" % (
            table, len(changed), len(added), empty, ", visual missing %d" % no_visual if visuals is not None else ""))
        if args.max_rows and total >= args.max_rows:
            summary.append("stopped at --max-rows %d" % args.max_rows)
            break

    kit = {"comment": "Classic test (docs/classic-on-forever.md): Classic Era %s rows on the Forever client %s, "
                      "%d rows. Written by tools/era/classic_kit.py." % (args.classic, args.forever, total),
           "target_build": args.forever, "first_push": args.first_push, "rows": rows}
    with open(args.out, "w") as fh_out:
        json.dump(kit, fh_out)
    print("\n".join(summary))
    print("%d rows -> %s (pushes from %d, 99 rows each: up to %d)" % (
        total, args.out, args.first_push, args.first_push + (total - 1) // 99))


if __name__ == "__main__":
    main()
