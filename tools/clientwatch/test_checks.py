"""Offline tests of the client watch parsers: python3 -m unittest discover -s tools/clientwatch"""
import os
import tempfile
import unittest

import checks

DBD = """COLUMNS
int ID
locstring Name_lang
int Flags

LAYOUT 984EC914
BUILD 1.15.8.63829-1.15.8.64057
BUILD 1.60.1.70790, 1.60.1.70840
$id$ID<32>
Name_lang
Flags<32>

LAYOUT 12345678
BUILD 1.60.1.70862
$id$ID<32>
Name_lang
Flags<32>[2] // now two
"""

SQL = """-- a comment with INSERT INTO `nope` (`ID`) VALUES (1);
DELETE FROM `map` WHERE `ID` = 530;
INSERT INTO `map` (`ID`, `Directory`, `MapName`) VALUES
(530, 'Expansion01', 'Out''land, (yes)'),
(531, 'a\\\\b', 'x;y');
INSERT INTO `hotfix_blob` (`TableHash`, `RecordId`, `locale`, `Blob`, `VerifiedBuild`) VALUES
(3776013982, 49576, 'enUS', X'00ff00', 70790);
INSERT INTO `hotfix_data` (`Id`, `UniqueId`, `TableHash`, `RecordId`, `Status`, `VerifiedBuild`) VALUES
(9530001, 953000101, 1, 530, 1, 70790);
"""


class FakeDBD:
    def name(self, sql_table):
        return {"map": "Map"}.get(sql_table)


class Tests(unittest.TestCase):
    def test_build_lines(self):
        self.assertTrue(checks._in_build_line("BUILD 1.60.1.70790, 1.60.1.70840", "1.60.1.70840"))
        self.assertFalse(checks._in_build_line("BUILD 1.60.1.70790, 1.60.1.70840", "1.60.1.70862"))
        self.assertTrue(checks._in_build_line("BUILD 1.15.8.63829-1.15.8.64057", "1.15.8.64000"))
        self.assertFalse(checks._in_build_line("BUILD 1.15.8.63829-1.15.8.64057", "1.15.9.64000"))

    def test_dbd_layouts(self):
        blocks = checks.parse_dbd(DBD)
        self.assertEqual(len(blocks), 2)
        i, b = checks.block_for(blocks, "1.60.1.70790")
        self.assertEqual((i, b["layouts"]), (0, ["984EC914"]))
        self.assertEqual(checks.block_for(blocks, "1.60.1.70840")[0], 0)
        self.assertEqual(checks.block_for(blocks, "1.60.1.70862")[1]["fields"][-1], "Flags<32>[2]")
        self.assertEqual(checks.block_for(blocks, "1.60.1.99999"), (None, None))

    def test_compare_layout(self):
        class D:
            def layout(self, t, v):
                return checks.block_for(checks.parse_dbd(DBD), v)
        self.assertIsNone(checks.compare_layout(D(), "ChrClasses", "1.60.1.70790", "1.60.1.70840"))
        ch = checks.compare_layout(D(), "ChrClasses", "1.60.1.70790", "1.60.1.70862")
        self.assertEqual(ch["change"], "layout")
        self.assertEqual(ch["fields_removed"], ["Flags<32>"])
        self.assertEqual(ch["fields_added"], ["Flags<32>[2]"])

    def test_sql_rows(self):
        rows = checks.sql_rows(SQL)
        self.assertEqual([t for t, _ in rows], ["map", "map", "hotfix_blob", "hotfix_data"])
        self.assertEqual(rows[0][1], {"ID": "530", "Directory": "Expansion01", "MapName": "Out'land, (yes)"})
        self.assertEqual(rows[1][1]["Directory"], "a\\b")
        self.assertEqual(rows[1][1]["MapName"], "x;y")
        self.assertEqual(rows[2][1]["Blob"], "00ff00")

    def test_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "2026_11_07_00_hotfixes_x.sql")
            with open(p, "w") as f:
                f.write(SQL)
            over, problems = checks.hotfix_overrides([p], FakeDBD())
        self.assertEqual(sorted(over), ["Map", "Spell"])
        self.assertEqual(sorted(over["Map"]), [530, 531])
        self.assertEqual(sorted(over["Spell"]), [49576])
        self.assertEqual(problems, [])

    def test_snake_and_diff(self):
        self.assertEqual(checks.snake("ChrClassesXPowerTypes"), "chr_classes_x_power_types")
        self.assertEqual(checks.snake("Achievement_Category"), "achievement_category")
        self.assertEqual(checks.row_diff({"a": "1", "b": "2"}, {"a": "1", "b": "3", "c": "4"}),
                         [("b", "2", "3"), ("c", None, "4")])


if __name__ == "__main__":
    unittest.main()
