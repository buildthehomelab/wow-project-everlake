"""Row-by-row compare after dropping columns that differ only because of the engine (see docs/classic-on-forever.md).
Reads the CSVs tables_compare.py cached in <work dir>/wago."""
import csv, sys, collections
csv.field_size_limit(1<<30)
S = sys.argv[1]
def rd(t, b):
    return {x["ID"]: x for x in csv.DictReader(open("%s/wago/%s-%s.csv" % (S, t, b), encoding="utf-8", errors="replace"))}
IGNORE = {
 "SpellMisc": {"Attributes_15"}, "SpellLevels": {"BaseLevel"}, "SpellTargetRestrictions": {"ConeDegrees"},
 "SkillLineAbility": {"TradeSkillCategoryID", "TrivialSkillLineRankHigh", "TrivialSkillLineRankLow"},
 "ItemSparse": {"ExpansionID"}, "AreaTable": {"MountFlags"}, "TaxiNodes": {"Flags"}, "UiMap": {"Flags"},
 "ItemModifiedAppearance": {"TransmogSourceTypeEnum"}, "CreatureModelData": {"GeoBox_%d" % i for i in range(6)},
 "GameObjectDisplayInfo": {"GeoBox_%d" % i for i in range(6)}, "Talent": {"ClassID"}, "SpellEffect": {"EffectBasePointsF"},
}
def num(x):
    try: return float(x)
    except: return None
for t in ["Spell", "SpellMisc", "SpellEffect", "SpellLevels", "SpellPower", "SpellCooldowns", "SpellAuraOptions", "SpellTargetRestrictions",
          "SkillLineAbility", "Talent", "ItemSparse", "ItemEffect", "Item", "CreatureDisplayInfo", "AreaTable", "TaxiNodes", "Map"]:
    a, b = rd(t, "1.60.1.70862"), rd(t, "1.15.9.70576")
    ca = list(next(iter(a.values())).keys()); cb = set(next(iter(b.values())).keys())
    common = [c for c in ca if c in cb and c not in IGNORE.get(t, ())]
    cols, differ = collections.Counter(), 0
    for k in a.keys() & b.keys():
        d = [c for c in common if a[k][c] != b[k][c] and not (num(a[k][c]) is not None and num(a[k][c]) == num(b[k][c]))]
        if t == "SpellEffect":
            fv, eb, es = num(a[k]["EffectBasePointsF"]), num(b[k]["EffectBasePoints"]), num(b[k]["EffectDieSides"])
            if fv is not None and eb is not None and fv not in (eb, eb + (es or 0), eb + 1):
                d.append("BasePoints")
        if d:
            differ += 1; cols.update(d)
    print("%-24s shared %6d  real differ %6d | %s" % (t, len(a.keys() & b.keys()), differ, ", ".join("%s %d" % c for c in cols.most_common(5))))
