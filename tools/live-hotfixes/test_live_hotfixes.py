#!/usr/bin/env python3
"""python3 -m unittest discover -s tools/live-hotfixes"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbcache  # noqa: E402
import tact_keys  # noqa: E402


def entry(push, table, record, data, status=1, unique=7, region=1):
    return dbcache.ENTRY_HEAD.pack(b"XFTH", region, push, unique, table, record, len(data), status) + data


def cache(build, *entries):
    return b"XFTH" + struct.pack("<II", 9, build) + bytes(32) + b"".join(entries)


KEY_A = bytes(range(16))
KEY_B = bytes(range(16, 32))


class DBCacheTest(unittest.TestCase):
    def test_reads_entries(self):
        build, recs = dbcache.parse(cache(70862, entry(-1, dbcache.TABLE_TACT_KEY, 8283, KEY_A),
                                          entry(5, 0x1234, 9, b"\x01\x02", status=2)))
        self.assertEqual(build, 70862)
        self.assertEqual([(r.push, r.table, r.record, r.status, r.data) for r in recs],
                         [(-1, dbcache.TABLE_TACT_KEY, 8283, 1, KEY_A), (5, 0x1234, 9, 2, b"\x01\x02")])

    def test_rejects_bad_files(self):
        with self.assertRaises(dbcache.CacheError):
            dbcache.parse(b"NOPE" + bytes(40))
        with self.assertRaises(dbcache.CacheError):
            dbcache.parse(b"XFTH" + struct.pack("<II", 8, 1) + bytes(32))
        cut = cache(1, entry(1, 2, 3, KEY_A))[:-1]
        with self.assertRaises(dbcache.CacheError):
            dbcache.parse(cut)

    def test_newest_push_wins(self):
        _, recs = dbcache.parse(cache(1, entry(-1, dbcache.TABLE_TACT_KEY, 1, KEY_A),
                                      entry(100, dbcache.TABLE_TACT_KEY, 1, KEY_B)))
        self.assertEqual(dbcache.latest(recs, dbcache.TABLE_TACT_KEY)[1].data, KEY_B)


class TactKeysTest(unittest.TestCase):
    CORE_SQL = ("REPLACE INTO tact_key (ID, Key1, Key2, Key3, Key4, Key5, Key6, Key7, Key8, Key9, Key10, Key11, Key12, "
                "Key13, Key14, Key15, Key16, VerifiedBuild) VALUES\n"
                f"(10, {', '.join(map(str, KEY_A))}, 0),\n(11, {', '.join(map(str, KEY_A))}, 0);")

    def test_core_rows_parsed(self):
        core = tact_keys.core_keys_from_sql([self.CORE_SQL])
        self.assertEqual(core, {10: KEY_A, 11: KEY_A})

    def test_missing_and_different(self):
        live = {10: KEY_A, 11: KEY_B, 12: KEY_B}
        missing, differ = tact_keys.plan(live, tact_keys.core_keys_from_sql([self.CORE_SQL]))
        self.assertEqual((missing, differ), ([12], [11]))

    def test_removed_keys_not_sent(self):
        _, recs = dbcache.parse(cache(1, entry(-1, dbcache.TABLE_TACT_KEY, 5, KEY_A, status=2)))
        self.assertEqual(tact_keys.live_keys(recs), {})

    def test_sql(self):
        sql = tact_keys.render({12: KEY_B}, [12], [], 9590000, 70862, "DBCache.bin", "2ae1313e9f")
        self.assertIn("DELETE FROM `tact_key` WHERE `ID` IN (12);", sql)
        self.assertIn(f"(12,{','.join(map(str, KEY_B))},70862);", sql)
        self.assertIn(f"(9590000,959000001,{dbcache.TABLE_TACT_KEY},12,1,70862);", sql)
        self.assertIsNone(tact_keys.render({}, [], [], 9590000, 1, "x", "y"))


if __name__ == "__main__":
    unittest.main()
