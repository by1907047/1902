"""Negative tests for tools/check_snapshot.py in a throwaway git repository.

Each case builds a small baseline tag plus manifests and checks that the
verifier accepts the consistent tree and rejects each way the baseline or
current-source identity could be misstated. No network or device access.
"""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import check_snapshot  # noqa: E402
import update_source_current  # noqa: E402

TAG = 'v-test-baseline'


def record(path, data):
    return {'Path': path, 'Bytes': len(data), 'SHA256': hashlib.sha256(data).hexdigest()}


class SourceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='sideline-identity-')
        self.root = Path(self.tmp.name)
        self.git('init', '-q')
        self.files = {'NCM-Driver-for-Windows/a.cpp': b'int a;\n',
                      'tests/b.py': b'print(1)\n'}
        for path, data in self.files.items():
            self.write(path, data)
        self.manifest = {'schema': 1, 'candidate': check_snapshot.BASELINE_CANDIDATE,
                         'files': [record(p, d) for p, d in sorted(self.files.items())]}
        self.write_manifest(self.manifest)
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'baseline')
        self.git('tag', TAG)
        self.patches = contextlib.ExitStack()
        for module in (check_snapshot, update_source_current):
            for name, value in (('ROOT', self.root),
                                ('MANIFEST', self.root/'docs/source-snapshot.json'),
                                ('CURRENT', self.root/'docs/source-current.json'),
                                ('BASELINE_TAG', TAG),
                                ('BASELINE_MANIFEST_SHA256', self.manifest_sha)):
                self.patch(module, name, value)
        self.patches.enter_context(unittest.mock.patch.dict(os.environ, {'GITHUB_ACTIONS': ''}))
        self.regenerate()

    def tearDown(self):
        self.patches.close()
        self.tmp.cleanup()

    def patch(self, module, name, value):
        self.patches.enter_context(unittest.mock.patch.object(module, name, value))

    def git(self, *args):
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                       cwd=self.root, check=True, capture_output=True)

    def write(self, path, data):
        file = self.root/path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)

    def write_manifest(self, manifest):
        data = (json.dumps(manifest, indent=2) + '\n').encode()
        self.write('docs/source-snapshot.json', data)
        self.manifest_sha = hashlib.sha256(data).hexdigest()

    def regenerate(self):
        with contextlib.redirect_stdout(io.StringIO()):
            update_source_current.main()

    def verify(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            check_snapshot.main()
        return output.getvalue()

    def assertRejected(self, fragment):
        with self.assertRaises(SystemExit) as raised:
            self.verify()
        self.assertIn(fragment, str(raised.exception))

    def test_consistent_tree_passes_and_reports_both_identities(self):
        output = self.verify()
        self.assertIn(f'all records match tag {TAG}', output)
        self.assertIn('2 files byte-preserved', output)
        self.assertIn('0 changed, 0 added', output)

    def test_intended_change_is_recorded_as_current_not_baseline(self):
        self.write('NCM-Driver-for-Windows/a.cpp', b'int a = 1;\n')
        self.write('tests/new_probe.py', b'pass\n')
        self.git('add', '-A')
        self.regenerate()
        output = self.verify()
        self.assertIn('1 files byte-preserved', output)
        self.assertIn('1 changed, 1 added', output)

    def test_unlisted_change_is_rejected(self):
        self.write('NCM-Driver-for-Windows/a.cpp', b'int a = 2;\n')
        self.assertRejected('differs from baseline but not listed as changed')

    def test_editing_baseline_manifest_is_rejected(self):
        manifest = json.loads((self.root/'docs/source-snapshot.json').read_text())
        manifest['files'][0]['Bytes'] += 1
        self.write('docs/source-snapshot.json', (json.dumps(manifest) + '\n').encode())
        self.assertRejected('Baseline manifest changed')

    def test_unrecorded_tracked_file_is_rejected(self):
        self.write('tests/unrecorded.py', b'pass\n')
        self.git('add', '-A')
        self.assertRejected('tracked but not recorded')

    def test_stale_changed_entry_is_rejected(self):
        self.write('tests/b.py', b'print(2)\n')
        self.regenerate()
        self.write('tests/b.py', self.files['tests/b.py'])
        self.assertRejected('listed as changed but identical to baseline')

    def test_manifest_that_disagrees_with_tag_is_rejected(self):
        # Manifest and working tree agree with each other but not with the tag.
        self.write('tests/b.py', b'print(3)\n')
        self.manifest['files'][1] = record('tests/b.py', b'print(3)\n')
        self.write_manifest(self.manifest)
        for module in (check_snapshot, update_source_current):
            self.patch(module, 'BASELINE_MANIFEST_SHA256', self.manifest_sha)
        self.regenerate()
        self.assertRejected(f'Baseline records differ from {TAG}')

    def test_ci_requires_the_baseline_tag(self):
        self.git('tag', '-d', TAG)
        self.assertIn('unavailable', self.verify())
        with unittest.mock.patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            self.assertRejected('required in CI')


if __name__ == '__main__':
    unittest.main()
