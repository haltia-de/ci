import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('upload', Path(__file__).resolve().parents[1] / 'upload-apk.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.chdir, self.cwd)
        self.data = {'old.x86_64.apk': b'old', 'unrelated.txt': b'keep'}
        self.data['SHA256SUMS'] = f'{u.digest(b"old")}  old.x86_64.apk\n'.encode()
        self.writes = []
        self.delay = 0
        self.hidden = {}
        self.calls = 0
        self.bad = None
        self.patches = [patch.object(u, 'gh', self.gh), patch.object(u.time, 'sleep')]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        Path('new.aarch64.apk').write_bytes(b'new')

    def gh(self, *args):
        if args[0] == 'release':
            self.writes.append(args)
            name = args[3]
            if name.endswith('.apk'):
                self.assertNotIn('--clobber', args)
            self.data[name] = Path(name).read_bytes()
            if self.delay:
                self.hidden[name] = self.delay
            return b''
        path = args[-1]
        if '/commits/' in path:
            return b'{"sha": "' + b'a' * 40 + b'"}'
        if '/releases?' in path:
            return b'[{"tag_name": "v1.0.0", "id": 1}]'
        if '/releases/assets/' in path:
            return self.data['SHA256SUMS']
        self.calls += 1
        if self.bad == 'error' or (self.bad == 'poll-error' and self.calls > 1):
            raise subprocess.CalledProcessError(1, 'gh')
        if self.bad == 'incomplete':
            return b'[{"name": "old.x86_64.apk"}]'
        import json
        result = []
        for i, (name, data) in enumerate(self.data.items()):
            if self.hidden.get(name, 0):
                self.hidden[name] -= 1
                continue
            result.append(dict(name=name, digest='sha256:' + u.digest(data), state='uploaded', id=i))
        return json.dumps(result).encode()

    def run_upload(self):
        u.run('haltia-de/example', 'v1.0.0', 'a' * 40, True)

    def test_new_architecture_preserves_old(self):
        before = dict(self.data)
        self.run_upload()
        self.assertEqual(self.data['old.x86_64.apk'], before['old.x86_64.apk'])
        self.assertEqual(self.data['unrelated.txt'], before['unrelated.txt'])
        self.assertIn(before['SHA256SUMS'], self.data['SHA256SUMS'])
        self.assertEqual(len(self.writes), 2)

    def test_identical_rerun(self):
        self.run_upload()
        self.writes.clear()
        self.run_upload()
        self.assertEqual(self.writes, [])

    def test_conflicting_bytes(self):
        self.data['new.aarch64.apk'] = b'conflict'
        with self.assertRaises(ValueError):
            self.run_upload()
        self.assertEqual(self.writes, [])

    def test_metadata_failures(self):
        for bad in ('error', 'incomplete'):
            with self.subTest(bad=bad):
                self.bad = bad
                with self.assertRaises((subprocess.CalledProcessError, KeyError)):
                    self.run_upload()
                self.assertEqual(self.writes, [])

    def test_delayed_visibility(self):
        self.delay = 12
        self.run_upload()
        # Bounded retries at attempts 10 and 20; no package replacement.
        self.assertEqual(len(self.writes), 6)

    def test_poll_error_does_not_retry_upload(self):
        self.bad = 'poll-error'
        with self.assertRaises(ValueError):
            self.run_upload()
        self.assertEqual(len(self.writes), 2)

    def test_wrong_commit(self):
        with self.assertRaises(ValueError):
            u.run('haltia-de/example', 'v1.0.0', 'b' * 40, True)
        self.assertEqual(self.writes, [])

    def test_checksum_conflict(self):
        self.data['SHA256SUMS'] = f'{u.digest(b"wrong")}  old.x86_64.apk\n'.encode()
        with self.assertRaises(ValueError):
            self.run_upload()
        self.assertEqual(self.writes, [])


if __name__ == '__main__':
    unittest.main()
