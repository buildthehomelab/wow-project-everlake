"""Unit tests for classic_kit.py and hotfix_kit.py's chunking: python -m unittest discover -s tools/era -v"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_kit  # noqa: E402
import hotfix_kit  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


class EffectValue(unittest.TestCase):
    def test_die_sides_0_or_1_adds_up(self):
        self.assertEqual(classic_kit.effect_value({"EffectBasePoints": "5", "EffectDieSides": "1"}), (6, 0.0))
        self.assertEqual(classic_kit.effect_value({"EffectBasePoints": "10", "EffectDieSides": "0"}), (10, 0.0))

    def test_a_range_becomes_its_middle_and_spread(self):
        # Classic 1155 + 1d189 = 1156..1344; Forever spell effect 1207110 holds 1250 and 0.1504
        value, variance = classic_kit.effect_value({"EffectBasePoints": "1155", "EffectDieSides": "189"})
        self.assertEqual(value, 1250)
        self.assertAlmostEqual(variance, 0.1504, places=4)


class Helpers(unittest.TestCase):
    def test_same_compares_numbers_by_value(self):
        self.assertTrue(classic_kit.same("1", "1.0"))
        self.assertFalse(classic_kit.same("1", "2"))
        self.assertFalse(classic_kit.same("a", "b"))

    def test_is_set(self):
        self.assertFalse(classic_kit.is_set("0"))
        self.assertFalse(classic_kit.is_set(""))
        self.assertTrue(classic_kit.is_set("0.5"))
        self.assertTrue(classic_kit.is_set("text"))

    def test_chunks_keep_statements_small(self):
        parts = list(hotfix_kit.chunks(list(range(2500))))
        self.assertEqual([len(p) for p in parts], [1000, 1000, 500])


def write(cache, build, table, header, rows):
    os.makedirs(os.path.join(cache, build), exist_ok=True)
    with open(os.path.join(cache, build, table + ".csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


class Kit(unittest.TestCase):
    def test_changed_added_and_empty_rows(self):
        with tempfile.TemporaryDirectory() as d:
            # Forever: Attributes_15 8192 everywhere (engine), a column Classic lacks (PvPDurationIndex)
            write(d, "F", "SpellMisc", ["ID", "Attributes_0", "Attributes_15", "DurationIndex", "PvPDurationIndex", "SpellID"],
                  [[1, 0, 8192, 5, 0, 100], [2, 16, 8192, 7, 0, 200], [3, 0, 8192, 1, 0, 300]])
            write(d, "C", "SpellMisc", ["ID", "Attributes_0", "Attributes_15", "DurationIndex", "SpellID"],
                  [[1, 0, 0, 9, 100],      # changed: DurationIndex only (Attributes_15 is engine noise)
                   [2, 16, 0, 7, 200],     # same apart from engine noise: not sent
                   [4, 64, 0, 3, 400],     # only Classic: sent with Forever's usual engine values
                   [5, 0, 0, 0, 500]])     # only Classic and empty: left out
            out = os.path.join(d, "kit.json")
            subprocess.run([sys.executable, "-I", os.path.join(HERE, "classic_kit.py"), "--cache", d, "--out", out,
                            "--forever", "F", "--classic", "C", "--tables", "SpellMisc"],
                           check=True, capture_output=True)
            with open(out) as f:
                kit = json.load(f)
        self.assertEqual(kit["target_build"], "F")
        changed, added = kit["rows"]
        self.assertEqual((changed["build"], changed["ids"], changed["set"]), ("F", [1], {"1": {"DurationIndex": "9"}}))
        self.assertEqual((added["build"], added["ids"]), ("C", [4]))
        self.assertEqual(added["set"]["4"], {"Attributes_15": "8192", "PvPDurationIndex": "0"})


if __name__ == "__main__":
    unittest.main()
