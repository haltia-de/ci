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
            return list(self.data.values())[int(path.rsplit('/', 1)[1])]
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


class FormatTests(unittest.TestCase):
    setUp = UploadTests.setUp
    gh = UploadTests.gh

    def invoke_workflow(self, format):
        # Execute the uploader entry point named by the actual release step,
        # with its format environment; replace only the external gh process.
        import runpy
        root = Path(__file__).resolve().parents[1]
        workflow = (root / '.github/workflows' / f'{format}.yml').read_text()
        release = workflow.split('      - name: The release\n')[1].split('      - name: Publish')[0]
        self.assertIn('BUILD_COMMIT: ${{ github.sha }}', release)
        self.assertIn('TAG: ${{ github.ref_name }}', release)
        self.assertIn('repository: haltia-de/ci', workflow.split('  release:')[1])
        command = release.split('        run: |\n')[1].splitlines()
        self.assertEqual(command[0].strip(), 'cd out')
        script = command[1].strip().split()
        self.assertEqual(script[0], 'python3')
        self.assertEqual(len(script), 2)
        format_env = release.split('PACKAGE_FORMAT: ')[1].splitlines()[0]
        with patch.dict(os.environ, GH_REPO='haltia-de/example', TAG='v1.0.0',
                        BUILD_COMMIT='a' * 40, PACKAGE_FORMAT=format_env, APPEND='false'), \
                patch.object(subprocess, 'check_output', lambda args: self.gh(*args[1:])):
            runpy.run_path(str(root / Path(script[1]).name), run_name='__main__')
        for write in self.writes:
            self.assertNotIn('--clobber', write)

    def prepare(self, format):
        self.data = {'unrelated.txt': b'keep'}
        self.writes.clear()
        self.calls = 0
        self.bad = None
        self.hidden = {}
        self.delay = 0
        Path(f'package.{format}').write_bytes(b'package')

    def test_both_workflow_upload_paths(self):
        for format in ('deb', 'flatpak'):
            with self.subTest(format=format):
                self.prepare(format)
                self.invoke_workflow(format)
                self.assertEqual(len(self.writes), 2)
                self.assertEqual(self.data['unrelated.txt'], b'keep')
                self.writes.clear()
                self.invoke_workflow(format)
                self.assertEqual(self.writes, [])

    def test_conflicts_and_api_failures(self):
        for format in ('deb', 'flatpak'):
            for failure in ('package', 'checksum', 'error', 'incomplete', 'ref'):
                with self.subTest(format=format, failure=failure):
                    self.prepare(format)
                    if failure == 'package':
                        self.data[f'package.{format}'] = b'different'
                    elif failure == 'checksum':
                        # Valid checksum content with different bytes is still immutable.
                        self.data[f'SHA256SUMS.{format}'] = b''
                    elif failure == 'ref':
                        with patch.dict(os.environ, BUILD_COMMIT='b' * 40):
                            # The workflow supplies its exact build commit.
                            with self.assertRaises(ValueError):
                                u.run('haltia-de/example', 'v1.0.0', 'b' * 40, False, format)
                        continue
                    else:
                        self.bad = failure
                    with self.assertRaises((ValueError, KeyError, subprocess.CalledProcessError)):
                        self.invoke_workflow(format)
                    self.assertEqual(self.writes, [])

    def test_no_architecture_append(self):
        for format in ('deb', 'flatpak'):
            self.prepare(format)
            self.data[f'old.{format}'] = b'old'
            with self.assertRaises(ValueError):
                self.invoke_workflow(format)
            self.assertEqual(self.writes, [])

    def test_delayed_visibility_and_poll_errors(self):
        for format in ('deb', 'flatpak'):
            self.prepare(format)
            self.delay = 12
            self.invoke_workflow(format)
            self.assertEqual(len(self.writes), 6)
            self.prepare(format)
            self.bad = 'poll-error'
            with self.assertRaises(ValueError):
                self.invoke_workflow(format)
            self.assertEqual(len(self.writes), 2)

    def test_parallel_other_format_in_progress(self):
        import json
        for format, other in (('deb', 'flatpak'), ('flatpak', 'deb')):
            self.prepare(format)
            self.invoke_workflow(format)
            self.writes.clear()
            original = self.gh

            def listing(*args):
                data = original(*args)
                if '/assets?' in args[-1]:
                    rows = json.loads(data)
                    rows.append(dict(name=f'parallel.{other}', digest=None, state='open', id=99))
                    return json.dumps(rows).encode()
                return data

            with patch.object(self, 'gh', listing):
                self.invoke_workflow(format)
            self.assertEqual(self.writes, [])

    def test_relevant_in_progress_waits_without_replacement(self):
        import json
        for format in ('deb', 'flatpak'):
            self.prepare(format)
            self.data[f'package.{format}'] = b'package'
            original = self.gh

            def listing(*args):
                data = original(*args)
                if '/assets?' in args[-1] and self.calls <= 12:
                    rows = json.loads(data)
                    rows[-1].update(state='open', digest=None)
                    return json.dumps(rows).encode()
                return data

            with patch.object(self, 'gh', listing):
                self.invoke_workflow(format)
            self.assertEqual([w[3] for w in self.writes], [f'SHA256SUMS.{format}'])

    def test_interrupted_initial_batch(self):
        for format in ('deb', 'flatpak'):
            self.prepare(format)
            self.data[f'package.{format}'] = b'package'
            Path(f'second.{format}').write_bytes(b'second')
            self.invoke_workflow(format)
            self.assertEqual([w[3] for w in self.writes],
                             [f'second.{format}', f'SHA256SUMS.{format}'])
            self.writes.clear()
            Path(f'third.{format}').write_bytes(b'third')
            with self.assertRaises(ValueError):
                self.invoke_workflow(format)
            self.assertEqual(self.writes, [])

    def test_relevant_readiness_is_bounded(self):
        import json
        self.prepare('deb')
        original = self.gh

        def listing(*args):
            if '/assets?' in args[-1]:
                return json.dumps([dict(name='package.deb', digest=None, state='open', id=99)]).encode()
            return original(*args)

        with patch.object(self, 'gh', listing), patch.object(u.time, 'sleep') as sleep:
            with self.assertRaises(ValueError):
                self.invoke_workflow('deb')
        self.assertEqual(sleep.call_count, 40)
        self.assertEqual(self.writes, [])

    def test_sealed_batch_cannot_drop_package(self):
        for format in ('deb', 'flatpak'):
            self.prepare(format)
            path = Path(f'extra.{format}')
            path.write_bytes(b'extra')
            self.invoke_workflow(format)
            self.writes.clear()
            path.unlink()
            with self.assertRaises(ValueError):
                self.invoke_workflow(format)
            self.assertEqual(self.writes, [])

    def test_sealed_incomplete_missing_package_recovers(self):
        for format in ('deb', 'flatpak'):
            with self.subTest(format=format):
                self.prepare(format)
                pkg = f'package.{format}'
                missing = f'missing.{format}'
                checksum = f'SHA256SUMS.{format}'
                Path(missing).write_bytes(b'missing')
                self.data[pkg] = b'package'
                sums = (
                    f'{u.digest(b"missing")}  {missing}\n'
                    f'{u.digest(b"package")}  {pkg}\n'
                ).encode()
                self.data[checksum] = sums
                before = dict(self.data)
                self.invoke_workflow(format)
                self.assertEqual([w[3] for w in self.writes], [missing])
                self.assertEqual(self.data[missing], b'missing')
                self.assertEqual(self.data[pkg], before[pkg])
                self.assertEqual(self.data[checksum], before[checksum])
                self.assertEqual(self.data['unrelated.txt'], b'keep')
                self.writes.clear()
                self.invoke_workflow(format)
                self.assertEqual(self.writes, [])

    def test_sealed_incomplete_rejects_digest_and_new_name(self):
        for format in ('deb', 'flatpak'):
            for case in ('digest', 'new-name'):
                with self.subTest(format=format, case=case):
                    self.prepare(format)
                    pkg = f'package.{format}'
                    checksum = f'SHA256SUMS.{format}'
                    self.data[checksum] = f'{u.digest(b"package")}  {pkg}\n'.encode()
                    if case == 'digest':
                        Path(pkg).write_bytes(b'different')
                    else:
                        Path(f'extra.{format}').write_bytes(b'extra')
                    with self.assertRaises(ValueError):
                        self.invoke_workflow(format)
                    self.assertEqual(self.writes, [])
                    self.assertNotIn(pkg, self.data)
                    self.assertNotIn(f'extra.{format}', self.data)
                    self.assertEqual(self.data[checksum],
                                     f'{u.digest(b"package")}  {pkg}\n'.encode())

    def test_unclassifiable_in_progress_fails_closed(self):
        import json
        for name in ('unknown', None):
            self.prepare('deb')
            original = self.gh

            def listing(*args):
                data = original(*args)
                if '/assets?' in args[-1]:
                    return json.dumps([dict(name=name, digest=None, state='open', id=99)]).encode()
                return data

            with patch.object(self, 'gh', listing):
                with self.assertRaises(ValueError):
                    self.invoke_workflow('deb')
            self.assertEqual(self.writes, [])

    def test_pagination(self):
        for format in ('deb', 'flatpak'):
            self.prepare(format)
            original = self.gh

            def paginated(*args):
                import json
                if '/assets?' in args[-1]:
                    if 'page=1' == args[-1].split('&')[-1]:
                        return json.dumps([dict(name=f'unrelated-{i}', digest='sha256:' + '0' * 64,
                                                state='uploaded', id=i) for i in range(100)]).encode()
                return original(*args)

            with patch.object(self, 'gh', paginated):
                self.invoke_workflow(format)
            self.assertEqual(len(self.writes), 2)


if __name__ == '__main__':
    unittest.main()
