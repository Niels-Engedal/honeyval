"""Standard-library smoke tests for the Potato dataset adapter."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('prepare_dataset.py')


class PrepareDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'strategies.jsonl'
        rows = [
            {'role': 'attacker', 'strategy': 'Looks genuine and interesting',
             'strategy_source': 'contemporaneous', 'strategy_prompt_version': 'v2', 'trajectory_id': 'a'},
            {'role': 'defender', 'strategy': 'Make it appear convincing',
             'strategy_source': 'contemporaneous', 'strategy_prompt_version': 'v2', 'trajectory_id': 'a'},
            {'role': 'attacker', 'strategy': 'Other old strategy',
             'strategy_source': 'retrospective', 'strategy_prompt_version': 'v2', 'trajectory_id': 'a'},
        ]
        self.source.write_text('\n'.join(json.dumps(x) for x in rows) + '\n')

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), '--input', str(self.source),
                               '--output-root', str(self.root / 'datasets'), *args],
                              text=True, capture_output=True)

    def test_separate_roles_and_default_source(self):
        done = self.run_script('--name', 'pilot')
        self.assertEqual(done.returncode, 0, done.stderr)
        path = self.root / 'datasets' / 'pilot'
        items = [json.loads(x) for x in (path / 'data.jsonl').read_text().splitlines()]
        self.assertEqual({x['role'] for x in items}, {'attacker','defender'})
        self.assertEqual(len(items), 2)
        self.assertEqual(len({x['id'] for x in items}), 2)
        self.assertIn('source_sha256', (path / 'manifest.json').read_text())
        self.assertTrue((path / 'config.yaml').exists())

    def test_no_overwrite(self):
        self.assertEqual(self.run_script('--name', 'pilot').returncode, 0)
        result = self.run_script('--name', 'pilot')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already exists', result.stderr)

    def test_role_and_legacy_filters(self):
        done = self.run_script('--name', 'legacy', '--role', 'attacker', '--source', 'all')
        self.assertEqual(done.returncode, 0, done.stderr)
        data = (self.root / 'datasets' / 'legacy' / 'data.jsonl').read_text().splitlines()
        self.assertEqual(len(data), 2)

    def test_mixed_protocol_rejected(self):
        with self.source.open('a') as fp:
            fp.write(json.dumps({'role': 'attacker', 'strategy':'new',
                                 'strategy_prompt_version':'v1',
                                 'strategy_source':'contemporaneous'}) + '\n')
        failed = self.run_script('--name', 'mixed')
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn('Multiple strategy prompt versions', failed.stderr)
        self.assertFalse((self.root / 'datasets' / 'mixed').exists())


if __name__ == '__main__':
    unittest.main()