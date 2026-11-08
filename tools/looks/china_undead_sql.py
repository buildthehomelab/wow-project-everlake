#!/usr/bin/env python3
"""Hotfix SQL for the China Undead test (docs/china-undead.md).

    python3 tools/looks/china_undead_sql.py --cache <dir for wago CSVs> --out sql/everlake/<file>.sql [--part c]

Copies the Forever build's "Fresh" Skin Type choice (male 6529, female 6526) into new choices "China" and
"China (B)" and gives each the China body (tools/looks/china_undead.py) as a skinned model. Reads
ChrCustomizationElement of the Forever build from wago.tools (cached in --cache).

--part d writes the third test (push 9570002): "Normal body", Blizzard's own Undead model (959310 / 997378, bones
inline) as the skinned model, with no new files. China (C) drew black too, so this tells whether any skinned
body draws black (textured = the China model's borrowed skeleton is the problem).

--part c writes the second test (push 9570001): "China (C)", the China body with its skin texture named in the
model (95450017 male, 95450019 female), since the first test drew the body black.
"""
import argparse
import csv
import os
import struct
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--cache", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--part", choices=["ab", "c", "d"], default="ab")
args = ap.parse_args()


def L(table, build="1.60.1.70790"):
    path = os.path.join(args.cache, build, table + ".csv")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        req = urllib.request.Request("https://wago.tools/db2/%s/csv?build=%s" % (table, build),
                                     headers={"User-Agent": "wow-project-everlake"})
        open(path, "wb").write(urllib.request.urlopen(req, timeout=120).read())
    return list(csv.DictReader(open(path, encoding="utf-8")))


BUILD = 70790
PART_C, PART_D = args.part == "c", args.part == "d"
PUSH = 9570002 if PART_D else 9570001 if PART_C else 9570000
H_CHOICE, H_ELEMENT, H_SKINNED = 0x681D0F3D, 0xD6D051EC, 0x559CECEC
elements = L("ChrCustomizationElement")
ECOLS = ["ID", "ChrCustomizationChoiceID", "RelatedChrCustomizationChoiceID", "ChrCustomizationGeosetID",
         "ChrCustomizationSkinnedModelID", "ChrCustomizationMaterialID", "ChrCustomizationBoneSetID",
         "ChrCustomizationCondModelID", "ChrCustomizationDisplayInfoID", "ChrCustItemGeoModifyID",
         "ChrCustomizationVoiceID", "AnimKitID", "ParticleColorID", "ChrCustGeoComponentLinkID"]
# (sex, option, Fresh choice to copy, China model FileDataID)
MODELS = {"ab": (95450001, 95450009), "c": (95450017, 95450019), "d": (959310, 997378)}[args.part]
SEXES = [("male", 567, "6529", MODELS[0]), ("female", 568, "6526", MODELS[1])]
# name, skinned-model Flags
VARIANTS = {"ab": [("China", 0), ("China (B)", 1)], "c": [("China (C)", 0)], "d": [("Normal body", 0)]}[args.part]
FIRST_ELEMENT = {"ab": 9546001, "c": 9546101, "d": 9546201}[args.part]
FIRST_ID = {"ab": 954601, "c": 954605, "d": 954607}[args.part]
choices, els, skinned = [], [], []
cid, eid, sid = FIRST_ID, FIRST_ELEMENT, FIRST_ID
for sex, option, fresh, model in SEXES:
    fresh_els = [e for e in elements if e["ChrCustomizationChoiceID"] == fresh]
    for n, (name, flags) in enumerate(VARIANTS):
        order = 6 if PART_D else 5 if PART_C else 3 + n
        choices.append((name, cid, option, 55, 0, order, order, 0, 90001, 0, 0, 0, sex))
        for e in fresh_els:
            row = [int(e[c]) for c in ECOLS]
            row[0], row[1] = eid, cid
            els.append(row); eid += 1
        skinned.append((sid, model, 0, 0, -1, flags, sex, name))
        els.append([eid, cid, 0, 0, sid] + [0] * 9); eid += 1
        cid += 1; sid += 1
out = []
w = out.append
if PART_D:
    w("-- China Undead test, part 3 (docs/china-undead.md): \"Normal body\" per sex. China and China (C) drew the China")
    w("-- body black, with the character skin and with a named texture alike. This attaches Blizzard's own Undead model")
    w("-- (959310 male, 997378 female; bones inline, unchanged) the same way, with Fresh's parts. Textured = skinned")
    w("-- bodies work and the China model's borrowed skeleton (SKID, no bones) is the problem; black = any skinned body")
    w("-- draws black on this model. No new files. Hotfix push %d. Re-runnable; the DELETEs undo it." % PUSH)
    w("-- Restart the worldserver afterwards.")
elif PART_C:
    w("-- China Undead test, part 2 (docs/china-undead.md): \"China (C)\" per sex. The first test (push 9570000) drew the")
    w("-- China body black: a skinned model gets no character skin. These models name the China skin texture (skin colour")
    w("-- 0) in place of the character skin: 95450017 (male, texture 95450018) and 95450019 (female, texture 95450020).")
    w("-- Otherwise the same as \"China\": Fresh's parts plus the body as a skinned model. Hotfix push %d." % PUSH)
    w("-- Re-runnable; the DELETEs undo it. Restart the worldserver afterwards.")
else:
    w("-- China Undead test (docs/china-undead.md): two new Undead \"Skin Type\" choices per sex, \"China\" and \"China (B)\".")
    w("-- Each copies the Fresh choice's parts (hides the exposed-bone pieces 19xx/29xx/30xx, Fresh's cape geosets) and adds")
    w("-- the China body as a skinned model (a collection, the way retail adds Mechagnome arms or Dracthyr horns), drawn on")
    w("-- the character's own skeleton. The model files are new FileDataIDs 95450001 (male) and 95450009 (female) from")
    w("-- tools/looks/china_undead.py; they reach the client through the patched build (tools/tact/patch.py).")
    w("-- \"China\" and \"China (B)\" differ only in the skinned model's Flags (0 and 1; retail uses 1 on 20 of its rows, meaning")
    w("-- unknown). Requirement 55 = Bony's (shown in a normal client); Fresh's own (4975) needs the China client setting.")
    w("-- ChrCustomizationSkinnedModel has no hotfix table in the core, so its rows go in hotfix_blob as the client's record")
    w("-- bytes (layout 4C32AA8A: CollectionsFileDataID int32, GeosetType uint8, GeosetID, Modifier, Flags int32; no ID).")
    w("-- Hotfix push %d. Re-runnable; the DELETEs undo it. Restart the worldserver afterwards." % PUSH)
w("")
w("DELETE FROM `hotfix_data` WHERE `Id` = %d;" % PUSH)
w("DELETE FROM `chr_customization_choice` WHERE `ID` IN (%s);" % ", ".join(str(c[1]) for c in choices))
w("DELETE FROM `chr_customization_element` WHERE `ID` BETWEEN %d AND %d;" % (FIRST_ELEMENT, eid - 1))
w("DELETE FROM `hotfix_blob` WHERE `TableHash` = %d AND `RecordId` IN (%s);" % (H_SKINNED, ", ".join(str(s[0]) for s in skinned)))
w("")
w("INSERT INTO `chr_customization_choice` (`Name`, `ID`, `ChrCustomizationOptionID`, `ChrCustomizationReqID`,")
w("  `ChrCustomizationVisReqID`, `SortOrder`, `UiOrderIndex`, `Flags`, `AddedInPatch`, `SoundKitID`, `SwatchColor1`, `SwatchColor2`,")
w("  `VerifiedBuild`) VALUES")
w("\n".join("('%s', %d, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d)%s -- %s" % (c[:12] + (BUILD, "," if i < len(choices) - 1 else ";", c[12])) for i, c in enumerate(choices)))
w("")
w("INSERT INTO `chr_customization_element` (%s, `VerifiedBuild`) VALUES" % ", ".join("`%s`" % c for c in ECOLS))
w(",\n".join("(%s, %d)" % (", ".join(map(str, r)), BUILD) for r in els) + ";")
w("")
w("INSERT INTO `hotfix_blob` (`TableHash`, `RecordId`, `locale`, `Blob`, `VerifiedBuild`) VALUES")
w("\n".join("(%d, %d, 'enUS', X'%s', %d)%s -- %s %s: model %d, geoset type 0 id 0, modifier -1, flags %d" %
             (H_SKINNED, s[0], struct.pack("<iBiii", s[1], s[2], s[3], s[4], s[5]).hex(), BUILD,
              "," if i < len(skinned) - 1 else ";", s[6], s[7], s[1], s[5])
             for i, s in enumerate(skinned)))
w("")
w("-- Send them to the client: ChrCustomizationChoice 0x%08X, ChrCustomizationElement 0x%08X, ChrCustomizationSkinnedModel 0x%08X" % (H_CHOICE, H_ELEMENT, H_SKINNED))
w("INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES")
rows, n = [], 1
for s in skinned:
    rows.append((PUSH, PUSH * 100 + n, H_SKINNED, s[0])); n += 1
for c in choices:
    rows.append((PUSH, PUSH * 100 + n, H_CHOICE, c[1])); n += 1
for r in els:
    rows.append((PUSH, PUSH * 100 + n, H_ELEMENT, r[0])); n += 1
assert n - 1 <= 99, n
w(",\n".join("(%d, %d, %d, %d, 1, %d)" % (r + (BUILD,)) for r in rows) + ";")
open(args.out, "w").write("\n".join(out) + "\n")
print(len(choices), "choices", len(els), "elements", len(skinned), "skinned", n - 1, "hotfix rows")
