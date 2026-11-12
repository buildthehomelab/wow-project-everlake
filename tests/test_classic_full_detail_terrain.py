"""Deployment-script guards and restart behavior, without Docker or live servers."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/classic-full-detail-terrain.sh'
MOCK = r'''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = ' '.join(sys.argv[1:])
with open(os.environ['CALL_LOG'], 'a') as f:
    f.write(args + '\n')
if sys.argv[1] in ('stop', 'start'):
    assert sys.argv[-1] == 'ix-everlake-realm2-worldserver2-1'
elif 'TC_REALM_ID' in args:
    print(os.getenv('SCHEMAS', '71\nworld_classic\nhotfixes_classic'))
elif 'mysqldump' in args:
    print('-- backed up map')
elif 'SELECT ParentMapID,Flags1' in args:
    print(os.getenv('STATE', '-1\t1536\t0'))
elif 'COUNT(*)' in args:
    print('1')
elif 'SELECT MAX(Id),MAX(UniqueId)' in args:
    print('9690001\t' + os.getenv('UNIQUE', '4294645896'))
elif '-t' not in sys.argv:
    Path(os.environ['SQL_LOG']).write_text(sys.stdin.read())
    sys.exit(int(os.getenv('SQL_FAIL', '0')))
'''


class FullDetailTerrain(unittest.TestCase):
    def run_script(self, mode, **overrides):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docker = root / 'docker'
            docker.write_text(MOCK)
            docker.chmod(0o755)
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                       TMPDIR=tmp, CALL_LOG=tmp + '/calls', SQL_LOG=tmp + '/sql', **overrides)
            result = subprocess.run(['bash', str(SCRIPT), mode], env=env,
                                    capture_output=True, text=True)
            calls = (root / 'calls').read_text()
            sql = (root / 'sql').read_text() if (root / 'sql').exists() else ''
            return result, calls, sql

    def test_apply_and_rollback(self):
        for mode, parent, target in [('apply', '-1\t1536\t0', '0, Flags1=2098688'), ('rollback', '0\t2098688\t1', '-1, Flags1=1536')]:
            with self.subTest(mode=mode):
                result, calls, sql = self.run_script(mode, STATE=parent)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('SET ParentMapID=' + target, sql)
                self.assertIn('MAX(UniqueId) + 1', sql)
                self.assertIn('COMMIT;', sql)
                self.assertIn('world_classic.terrain_swap_defaults', sql)
                self.assertIn('INSERT INTO' if mode == 'apply' else 'DELETE FROM', sql)
                self.assertIn('stop --time 120 ix-everlake-realm2-worldserver2-1', calls)
                self.assertTrue(calls.rstrip().endswith('start ix-everlake-realm2-worldserver2-1'))

    def test_sql_failure_restarts_classic(self):
        result, calls, sql = self.run_script('apply', SQL_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(calls.rstrip().endswith('start ix-everlake-realm2-worldserver2-1'))
        self.assertNotIn('apply complete', result.stdout)

    def test_guards_make_no_changes(self):
        for values in [dict(SCHEMAS='70\nworld\nhotfixes'), dict(STATE='-1\t1536\t1'),
                       dict(UNIQUE='4294967295'), dict(STATE='0\t1536\t0')]:
            with self.subTest(values=values):
                result, calls, sql = self.run_script('apply', **values)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('stop ', calls)
                self.assertEqual(sql, '')

    def test_check_is_read_only(self):
        result, calls, sql = self.run_script('check')
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('stop ', calls)
        self.assertEqual(sql, '')


if __name__ == '__main__':
    unittest.main()
