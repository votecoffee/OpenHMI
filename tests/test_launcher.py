"""Launcher ownership, user-data defaults and administrator setup contracts."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openhmi import launcher
from openhmi.projects import ProjectStore
from openhmi.security import Security
from tests.test_security import PASSWORD


class LauncherTests(unittest.TestCase):
    def test_frozen_data_default_is_independent_of_application_and_working_directory(self):
        with patch.object(sys, 'frozen', True, create=True), patch.dict(os.environ, {'LOCALAPPDATA': 'X:/SyntheticUserData'}):
            self.assertEqual(launcher.default_project(), Path('X:/SyntheticUserData/OpenHMI/projects/Default.openhmi.sqlite3'))
        self.assertEqual(launcher.default_project(), Path('.local/project.sqlite3'))

    def test_library_lock_survives_file_presence_and_releases_after_exception(self):
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'Synthetic'):
                with launcher.library_lock(directory):
                    with self.assertRaisesRegex(RuntimeError, 'Another OpenHMI'):
                        with launcher.library_lock(directory):
                            self.fail('A second owner was admitted')
                    raise ValueError('Synthetic')
            self.assertTrue((Path(directory) / '.openhmi-runtime.lock').exists())
            with launcher.library_lock(directory):
                pass

    def test_os_releases_lock_when_a_process_exits_without_cleanup(self):
        with TemporaryDirectory() as directory:
            code = 'from openhmi.launcher import library_lock; import sys; lock=library_lock(sys.argv[1]); lock.__enter__(); print("owned",flush=True); sys.stdin.read()'
            child = subprocess.Popen([sys.executable, '-c', code, directory], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                self.assertEqual(child.stdout.readline().strip(), 'owned')
                with self.assertRaises(RuntimeError):
                    with launcher.library_lock(directory):
                        self.fail('Cross-process ownership was lost')
            finally:
                child.kill()
                child.communicate(timeout=10)
            with launcher.library_lock(directory):
                pass

    def test_self_check_creates_no_project_or_library(self):
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()) as output:
            project = Path(directory) / 'absent' / 'Project.sqlite3'
            launcher.main(['--project', str(project), '--self-check'])
            self.assertIn('"assets": "present"', output.getvalue())
            self.assertFalse(project.parent.exists())

    def test_invalid_port_and_version_do_not_create_project_data(self):
        with TemporaryDirectory() as directory:
            project = Path(directory) / 'absent' / 'Project.sqlite3'
            for port in ('0', '65536', 'invalid'):
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                    launcher.main(['--project', str(project), '--port', port])
                self.assertEqual(error.exception.code, 2)
            with redirect_stdout(StringIO()), self.assertRaises(SystemExit) as error:
                launcher.main(['--version'])
            self.assertEqual(error.exception.code, 0)
            self.assertFalse(project.parent.exists())

    def test_preflight_preserves_existing_files_and_does_not_start_runtime(self):
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()) as output:
            library = Path(directory)
            project = library / 'Project.sqlite3'
            project.write_bytes(b'Existing database fixture')
            logs = library / 'logs'
            logs.mkdir()
            log = logs / 'runtime.log'
            log.write_bytes(b'Existing log fixture')
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            launcher.main(['--preflight', '--project', str(project), '--port', str(port)])
            self.assertTrue(json.loads(output.getvalue())['ok'])
            self.assertEqual(project.read_bytes(), b'Existing database fixture')
            self.assertEqual(log.read_bytes(), b'Existing log fixture')
            self.assertEqual(set(library.iterdir()), {project, logs})
            self.assertEqual(list(logs.iterdir()), [log])

    def test_preflight_reports_missing_log_directory_and_occupied_port(self):
        with TemporaryDirectory() as directory, socket.socket() as listener, redirect_stdout(StringIO()) as output:
            project = Path(directory) / 'Project.sqlite3'
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            with self.assertRaises(SystemExit) as error:
                launcher.main(['--preflight', '--project', str(project), '--port', str(listener.getsockname()[1])])
            self.assertEqual(error.exception.code, 1)
            report = json.loads(output.getvalue())
            self.assertFalse(report['ok'])
            self.assertTrue(report['checks']['project_storage']['ok'])
            self.assertFalse(report['checks']['log_storage']['ok'])
            self.assertFalse(report['checks']['loopback_port']['ok'])
            self.assertEqual(list(project.parent.iterdir()), [])

    def test_occupied_port_stops_startup_before_creating_project_or_logs(self):
        with TemporaryDirectory() as directory, socket.socket() as listener, redirect_stderr(StringIO()) as output:
            project = Path(directory) / 'absent' / 'Project.sqlite3'
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaises(SystemExit) as error:
                launcher.main(['--project', str(project), '--port', str(port)])
            self.assertEqual(error.exception.code, 1)
            self.assertIn(f'Cannot bind 127.0.0.1:{port}', output.getvalue())
            self.assertFalse(project.parent.exists())

    def test_bundled_admin_setup_preserves_existing_users_and_requires_library_ownership(self):
        with TemporaryDirectory() as directory:
            project = Path(directory) / 'Project.sqlite3'
            args = ['--project', str(project), '--create-admin', 'admin']
            with patch('getpass.getpass', return_value=PASSWORD), redirect_stdout(StringIO()):
                launcher.main(args)
            with launcher.library_lock(directory), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                launcher.main(['--project', str(project), '--create-admin', 'other'])
            self.assertEqual(error.exception.code, 1)
            with patch('getpass.getpass', return_value=PASSWORD), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                launcher.main(args)
            self.assertEqual(error.exception.code, 2)
            store = ProjectStore(project)
            try:
                users = Security(store).snapshot()['users']
                self.assertEqual([user['name'] for user in users], ['admin'])
                self.assertEqual(users[0]['groups'], ['Administrators'])
            finally:
                store.close()

    def test_incomplete_package_fails_before_opening_database(self):
        with TemporaryDirectory() as directory, patch.object(launcher, 'self_check', side_effect=RuntimeError('Incomplete application package')):
            project = Path(directory) / 'Project.sqlite3'
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                launcher.main(['--project', str(project)])
            self.assertEqual(error.exception.code, 1)
            self.assertFalse(project.exists())
