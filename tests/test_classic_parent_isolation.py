"""Deployment-script guards and restart behavior, without Docker or live servers."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/classic-parent-isolation.sh'
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
elif 'COUNT(*)' in args:
    print(os.getenv('ACTIVE', '0') if 'terrain_swap_defaults' in args else '1')
elif 'SELECT ParentMapID' in args:
    print(os.getenv('PARENT', '0'))
elif 'SELECT MAX(Id),MAX(UniqueId)' in args:
    print('9690001\t' + os.getenv('UNIQUE', '4294645896'))
elif '-t' not in sys.argv:
    Path(os.environ['SQL_LOG']).write_text(sys.stdin.read())
    sys.exit(int(os.getenv('SQL_FAIL', '0')))
'''


class ParentIsolation(unittest.TestCase):
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

    def test_detach_and_restore(self):
        for mode, parent, target in [('detach', '0', '-1'), ('restore', '-1', '0')]:
            with self.subTest(mode=mode):
                result, calls, sql = self.run_script(mode, PARENT=parent)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('SET ParentMapID=' + target, sql)
                self.assertIn('MAX(UniqueId) + 1', sql)
                self.assertIn('COMMIT;', sql)
                self.assertIn('stop --time 120 ix-everlake-realm2-worldserver2-1', calls)
                self.assertTrue(calls.rstrip().endswith('start ix-everlake-realm2-worldserver2-1'))

    def test_sql_failure_restarts_classic(self):
        result, calls, sql = self.run_script('detach', SQL_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(calls.rstrip().endswith('start ix-everlake-realm2-worldserver2-1'))
        self.assertNotIn('detach complete', result.stdout)

    def test_guards_make_no_changes(self):
        for values in [dict(SCHEMAS='70\nworld\nhotfixes'), dict(ACTIVE='1'),
                       dict(UNIQUE='4294967295'), dict(PARENT='-1')]:
            with self.subTest(values=values):
                result, calls, sql = self.run_script('detach', **values)
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
