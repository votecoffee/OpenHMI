"""Integrity, Windows path boundaries and data-preserving preview updates."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import zipfile

from openhmi.package_manager import Packages, main, relative_name
from openhmi.launcher import main as launch


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.packages = Packages(self.root / 'applications')

    def archive(self, name='first.zip', value=b'MZ synthetic fixture', change=None, extra=None):
        files = {'OpenHMI.exe': value, '_internal/assets.txt': b'local asset'}
        manifest = {'format': 'OpenHMI-windows-preview', 'version': '0.1.0.dev0', 'source_commit': 'a' * 40,
                    'source_dirty': False, 'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        if change:
            change(manifest)
        path = self.root / name
        with zipfile.ZipFile(path, 'w') as zipped:
            zipped.writestr('OpenHMI/manifest.json', json.dumps(manifest))
            for file, data in files.items():
                zipped.writestr('OpenHMI/' + file, data)
            for file, data in extra or []:
                zipped.writestr(file, data)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_install_activate_update_and_rollback_leave_project_bytes_untouched(self):
        project = self.root / 'projects' / 'Machine.sqlite3'
        project.parent.mkdir(); project.write_bytes(b'synthetic project/security/recipe data')
        original = project.read_bytes()
        archive, first = self.archive()
        self.assertEqual(self.packages.install(archive, first)['verified_files'], 2)
        self.assertIsNone(self.packages.current())
        self.packages.activate(first)
        archive, second = self.archive('second.zip', b'MZ next version')
        self.packages.install(archive, second)
        self.assertEqual(self.packages.current()['release'], first)
        self.assertEqual(self.packages.activate(second)['previous'], first)
        self.packages.activate(first)
        self.assertEqual(self.packages.current()['release'], first)
        self.assertTrue(self.packages.release(second).exists())
        self.assertEqual(project.read_bytes(), original)
        self.assertEqual(len(self.packages.listing()['releases']), 2)

    def test_bad_archive_or_file_hash_never_changes_selection(self):
        archive, first = self.archive()
        self.packages.install(archive, first); self.packages.activate(first)
        with self.assertRaises(ValueError):
            self.packages.install(archive, '0' * 64)
        archive, second = self.archive('bad.zip', change=lambda m: m['files'].update({'OpenHMI.exe': '0' * 64}))
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.packages.install(archive, second)
        self.assertEqual(self.packages.current()['release'], first)
        self.assertFalse(self.packages.release(second).exists())

    def test_windows_paths_case_collisions_and_unlisted_payload_are_rejected(self):
        for name in ('../outside', '/absolute', 'C:/file', 'a\\b', 'a:b', 'a/../b', 'a//b', 'a/./b', 'a/CON.txt', 'a/COM¹.txt', 'a/LPT³', 'a/nul', 'a/trailing.', 'a/trailing ', 'a/file?', 'a/line\nbreak'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                relative_name(name)
        archive, digest = self.archive(extra=[('OpenHMI/Unexpected.exe', b'not listed')])
        with self.assertRaisesRegex(ValueError, 'inventory'):
            self.packages.install(archive, digest)
        archive, digest = self.archive('case.zip', extra=[('OpenHMI/OPENHMI.EXE', b'collision')])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.packages.install(archive, digest)

    def test_tampering_and_extra_files_prevent_activation_and_launch(self):
        archive, digest = self.archive()
        self.packages.install(archive, digest); self.packages.activate(digest)
        file = self.packages.release(digest) / 'OpenHMI/_internal/assets.txt'
        file.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.packages.activate(digest)
        with patch('subprocess.Popen') as run, self.assertRaises(SystemExit) as error:
            main(['--root', str(self.packages.root), 'launch', '--self-check'])
        self.assertEqual(error.exception.code, 1)
        run.assert_not_called()
        file.write_bytes(b'local asset')
        file.with_name('unknown.dll').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            self.packages.verify(digest)

    def test_metadata_tampering_dirty_source_and_unknown_selection_are_preserved(self):
        archive, digest = self.archive(change=lambda m: m.update(source_dirty=True))
        with self.assertRaises(ValueError):
            self.packages.install(archive, digest)
        archive, digest = self.archive('clean.zip')
        self.packages.install(archive, digest)
        pointer = self.packages.root / 'active.json'
        pointer.write_bytes(b'{"unrelated":"preserve me"}')
        with self.assertRaisesRegex(ValueError, 'Unrecognized'):
            self.packages.activate(digest)
        self.assertEqual(pointer.read_bytes(), b'{"unrelated":"preserve me"}')
        manifest = self.packages.release(digest) / 'OpenHMI/manifest.json'
        manifest.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'manifest identity'):
            self.packages.verify(digest)

    def test_reinstall_verifies_existing_copy_without_overwriting_it(self):
        archive, digest = self.archive()
        self.packages.install(archive, digest)
        file = self.packages.release(digest) / 'OpenHMI/OpenHMI.exe'
        file.write_bytes(b'preserve changed evidence')
        with self.assertRaises(ValueError):
            self.packages.install(archive, digest)
        self.assertEqual(file.read_bytes(), b'preserve changed evidence')

    def test_launch_forwards_arguments_and_refuses_data_inside_application_root(self):
        archive, digest = self.archive()
        self.packages.install(archive, digest); self.packages.activate(digest)
        with patch('subprocess.Popen') as run, self.assertRaises(SystemExit) as error:
            runtime = run.return_value
            runtime.wait.return_value = 0
            main(['--root', str(self.packages.root), 'launch', '--project', str(self.root / 'projects/Machine.sqlite3'), '--port', '8012', '--open-browser'])
        self.assertEqual(error.exception.code, 0)
        self.assertIn('--open-browser', run.call_args.args[0])
        with patch('subprocess.Popen') as run, self.assertRaises(SystemExit):
            main(['--root', str(self.packages.root), 'launch', '--project', str(self.packages.root / 'data.sqlite3')])
        run.assert_not_called()

    def test_managed_launch_waits_for_shutdown_after_console_interrupt(self):
        archive, digest = self.archive()
        self.packages.install(archive, digest); self.packages.activate(digest)
        with patch('subprocess.Popen') as run, self.assertRaises(SystemExit) as error:
            runtime = run.return_value
            runtime.wait.side_effect = [subprocess.TimeoutExpired('runtime', 0.25), KeyboardInterrupt, 7]
            main(['--root', str(self.packages.root), 'launch', '--project', str(self.root / 'station.sqlite3'),
                  '--watchdog-restarts', '2'])
        self.assertEqual(error.exception.code, 7)
        run.assert_called_once()
        self.assertEqual(runtime.wait.call_count, 3)
        self.assertGreater(runtime.wait.call_args.kwargs['timeout'], 0)
        runtime.kill.assert_not_called()

    def test_managed_launch_uses_one_deadline_and_terminates_only_its_child(self):
        archive, digest = self.archive()
        self.packages.install(archive, digest)
        self.packages.activate(digest)
        with patch('subprocess.Popen') as run, patch('openhmi.package_manager.time.monotonic', side_effect=[100, 101, 102, 103, 104]), \
                redirect_stderr(StringIO()) as errors, self.assertRaises(SystemExit) as error:
            runtime = run.return_value
            runtime.wait.side_effect = [KeyboardInterrupt, KeyboardInterrupt, subprocess.TimeoutExpired('runtime', 1), 1]
            runtime.poll.return_value = None
            main(['--root', str(self.packages.root), 'launch', '--shutdown-timeout', '3'])
        self.assertEqual(error.exception.code, 124)
        self.assertEqual([call.kwargs.get('timeout') for call in runtime.wait.call_args_list], [0.25, 2, 1, 4])
        runtime.kill.assert_called_once_with()
        run.assert_called_once()
        self.assertNotIn('--shutdown-timeout', run.call_args.args[0])
        self.assertIn('exceeded the 3s shutdown grace period', errors.getvalue())

    def test_managed_launch_rejects_invalid_shutdown_timeout_before_launch(self):
        with patch('subprocess.Popen') as run, redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
            main(['--root', str(self.packages.root), 'launch', '--shutdown-timeout', '0'])
        self.assertEqual(error.exception.code, 2)
        run.assert_not_called()

    def test_watchdog_retries_only_nonzero_exits_with_bounded_backoff_and_held_arguments(self):
        archive, digest = self.archive()
        self.packages.install(archive, digest)
        self.packages.activate(digest)
        runtimes = [Mock(**{'wait.return_value': code}) for code in (8, 9, 10)]
        with patch('subprocess.Popen', side_effect=runtimes) as run, patch('openhmi.package_manager.time.sleep') as sleep, \
                redirect_stderr(StringIO()) as errors, self.assertRaises(SystemExit) as result:
            main(['--root', str(self.packages.root), 'launch', '--project', str(self.root / 'station.sqlite3'),
                  '--handlers', str(self.root / 'startup.py'), '--open-browser', '--watchdog-restarts', '2'])
        self.assertEqual(result.exception.code, 10)
        initial, first, second = [call.args[0] for call in run.call_args_list]
        self.assertIn('--handlers', initial)
        self.assertIn('--open-browser', initial)
        self.assertNotIn('--hold-connections', initial)
        self.assertIn('--hold-connections', first)
        self.assertNotIn('--handlers', first)
        self.assertNotIn('--open-browser', first)
        self.assertEqual(first, second)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])
        self.assertIn('Recovery 2/2', errors.getvalue())

    def test_watchdog_stops_on_clean_exit_and_on_interrupt_between_launches(self):
        archive, digest = self.archive()
        self.packages.install(archive, digest)
        self.packages.activate(digest)
        arguments = ['--root', str(self.packages.root), 'launch', '--project', str(self.root / 'station.sqlite3'),
                     '--watchdog-restarts', '2']
        for code, expected in ((0, 0), (9, 130)):
            with self.subTest(code=code), patch('subprocess.Popen') as run, \
                    patch('openhmi.package_manager.time.sleep', side_effect=KeyboardInterrupt) as sleep, \
                    redirect_stderr(StringIO()), self.assertRaises(SystemExit) as result:
                run.return_value.wait.return_value = code
                main(arguments)
            self.assertEqual(result.exception.code, expected)
            run.assert_called_once()
            self.assertEqual(sleep.call_count, int(code != 0))

    def test_launcher_package_dispatch_and_manager_lock(self):
        with redirect_stdout(StringIO()) as output:
            launch(['package', '--root', str(self.packages.root), 'list'])
        self.assertEqual(json.loads(output.getvalue())['releases'], [])
        archive, digest = self.archive()
        with self.packages.locked(), self.assertRaises(RuntimeError):
            self.packages.install(archive, digest)

    def test_duplicate_metadata_keys_links_and_expansion_limits_are_rejected(self):
        from openhmi.package_manager import manifest_value
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            manifest_value(b'{"format":"x","format":"y"}')
        archive, digest = self.archive()
        with patch('openhmi.package_manager.MAX_EXPANDED', 1), self.assertRaises(ValueError):
            self.packages.install(archive, digest)
        link = self.root / 'linked.zip'
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(link, 'w') as target:
            for info in source.infolist():
                if info.filename.endswith('assets.txt'):
                    info.create_system = 3; info.external_attr = 0o120777 << 16
                target.writestr(info, source.read(info))
        with self.assertRaisesRegex(ValueError, 'ordinary'):
            self.packages.install(link, hashlib.sha256(link.read_bytes()).hexdigest())

    def test_interrupted_activation_keeps_previous_pointer(self):
        archive, first = self.archive()
        self.packages.install(archive, first); self.packages.activate(first)
        archive, second = self.archive('update.zip', b'MZ updated fixture')
        self.packages.install(archive, second)
        pointer = (self.packages.root / 'active.json').read_bytes()
        with patch('os.replace', side_effect=OSError('Synthetic interrupted selection')), self.assertRaises(OSError):
            self.packages.activate(second)
        self.assertEqual((self.packages.root / 'active.json').read_bytes(), pointer)
        self.assertEqual(self.packages.verify(second)['release'], second)
