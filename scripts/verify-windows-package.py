"""Bounded offline smoke drill against an extracted package; no real PLC routes."""
import argparse
import csv
import hashlib
import http.cookiejar
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True, help='Extracted OpenHMI folder')
    parser.add_argument('--work', type=Path, required=True, help='New retained drill folder; never reuse a live project library')
    args = parser.parse_args()
    package, work = args.package.resolve(), args.work.resolve()
    executable = package / 'OpenHMI.exe'
    manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = package / name
        assert path.resolve().is_relative_to(package), 'Manifest path outside package'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, f'Package mismatch: {name}'
    work.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    env.pop('PYTHONHOME', None); env.pop('PYTHONPATH', None)
    hidden = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    check = subprocess.run([str(executable), '--self-check'], cwd=work, env=env, capture_output=True, text=True, check=True, creationflags=hidden)
    report = {'self_check': json.loads(check.stdout), 'manifest_files_verified': len(manifest['files']), 'path_has_python_or_node': False}
    assert report['self_check']['frozen'] is True
    project = work / 'project library' / 'Pilot.openhmi.sqlite3'
    handler = work / 'startup-probe.py'
    marker = work / 'handler-ran'
    handler.write_text(f'from pathlib import Path\ndef register(app):\n    Path({str(marker)!r}).touch()\n', encoding='utf-8')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        reservation.listen()
        port = reservation.getsockname()[1]
        conflict = subprocess.run([str(executable), '--project', str(project), '--port', str(port), '--handlers', str(handler)],
                                  cwd=work, env=env, capture_output=True, text=True, timeout=15, creationflags=hidden)
        assert conflict.returncode == 1 and f'Cannot bind 127.0.0.1:{port}' in conflict.stderr
        assert not project.parent.exists() and not marker.exists()
    report['port_conflict_rejected_before_opening_project_or_handlers'] = True
    # Simulate a failure before the ASGI workspace reports startup complete.
    handler.write_text(
        'from openhmi.workspace import ProjectWorkspace\n'
        'original = ProjectWorkspace.__call__\n'
        'async def fail_startup(self, scope, receive, send):\n'
        '    if scope["type"] == "lifespan":\n'
        '        raise RuntimeError("Synthetic workspace startup failure")\n'
        '    return await original(self, scope, receive, send)\n'
        'def register(app):\n'
        '    ProjectWorkspace.__call__ = fail_startup\n',
        encoding='utf-8',
    )
    failed_project = work / 'failed startup library' / 'Fault.openhmi.sqlite3'
    failed_start = subprocess.run(
        [str(executable), '--project', str(failed_project), '--port', str(port), '--handlers', str(handler)],
        cwd=work, env=env, capture_output=True, text=True, timeout=15, creationflags=hidden,
    )
    assert failed_start.returncode != 0 and 'Synthetic workspace startup failure' in failed_start.stderr
    assert 'Application startup failed' in failed_start.stderr
    assert 'Uvicorn running on' not in failed_start.stderr
    report['workspace_initialization_failure_prevents_serving_http'] = True
    invalid_project = work / 'invalid project library' / 'Invalid.openhmi.sqlite3'
    invalid_project.parent.mkdir()
    invalid_data = b'Synthetic invalid SQLite file'
    invalid_project.write_bytes(invalid_data)
    invalid_start = subprocess.run(
        [str(executable), '--project', str(invalid_project), '--port', str(port)],
        cwd=work, env=env, capture_output=True, text=True, timeout=15, creationflags=hidden,
    )
    invalid_log = (invalid_project.parent / 'logs/runtime.log').read_text(encoding='utf-8')
    assert invalid_start.returncode == 1 and 'Could not initialize project' in invalid_log
    assert 'file is not a database' in invalid_log and invalid_project.read_bytes() == invalid_data
    report['invalid_database_startup_error_logged_with_original_preserved'] = True
    project.parent.mkdir()
    logs = project.parent / 'logs'
    logs.mkdir()
    preflight = subprocess.run([str(executable), '--preflight', '--project', str(project), '--port', str(port)],
                               cwd=work, env=env, capture_output=True, text=True, check=True, creationflags=hidden)
    assert json.loads(preflight.stdout)['ok']
    assert list(project.parent.iterdir()) == [logs] and list(logs.iterdir()) == []
    report['preflight_passed_without_creating_runtime_files'] = True
    base = f'http://127.0.0.1:{port}'
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path, data=None, method=None):
        raw = isinstance(data, bytes)
        body = data if raw else json.dumps(data).encode() if data is not None else None
        content_type = 'image/png' if raw else 'application/json'
        with opener.open(urllib.request.Request(base + path, body, {'Content-Type': content_type}, method=method), timeout=5) as response:
            return response.read()
    def start(log):
        process = subprocess.Popen([str(executable), '--project', str(project), '--port', str(port)], cwd=work, env=env,
                                   stdout=log, stderr=log, creationflags=hidden)
        for _ in range(200):
            if process.poll() is not None:
                raise RuntimeError(f'Packaged runtime exited with {process.returncode}; inspect {work}')
            try:
                request('/api/project'); return process
            except (OSError, urllib.error.URLError):
                time.sleep(.1)
        process.kill(); process.wait(timeout=10)
        raise RuntimeError('Packaged runtime did not start in 20 seconds')
    with (work / 'process.log').open('wb') as log:
        child = start(log)
        try:
            for path in ('/', '/runtime', '/static/vendor/app.js', '/static/vendor/app.css', '/static/assets/fonts/NotoSansSC.ttf', '/static/assets/flags/us.svg'):
                assert request(path), f'Missing HTTP asset: {path}'
            state = json.loads(request('/api/project'))
            state['draft']['title'] = 'Packaged restart fixture'
            state['draft']['tags'] += [{'name': 'PackageMaximum', 'type': 'number', 'initial': 50.0}, {'name': 'PackageUser', 'type': 'string', 'initial': '', 'writable': True}, {'name': 'PackagePrivileges', 'type': 'integer', 'initial': 0, 'writable': True}]
            state['draft']['controls'] += [{'id': 'package_number', 'kind': 'input', 'label': 'Packaged number', 'tag': 'TankLevel', 'minimum': 10.0, 'maximum_tag': 'PackageMaximum'}, {'id': 'package_text', 'kind': 'text_input', 'label': 'Packaged text', 'tag': 'OperatorText', 'max_length': 4}]
            state['draft']['controls'].append({
                'id': 'package_trend', 'kind': 'trend', 'label': 'Packaged trend',
                'tags': ['TankLevel', 'MotorRunning'], 'seconds': 10,
                'recording': {'sample_ms': 100, 'max_samples': 30},
            })
            image = BytesIO()
            Image.new('RGB', (40, 30), '#789abc').save(image, format='PNG')
            image_id = json.loads(request('/api/canvas-images', image.getvalue(), 'POST'))['id']
            state['draft']['layout'] = {
                'boxes': {
                    control['id']: {'x': (index % 4) * 160, 'y': (index // 4) * 100, 'width': 152, 'height': 90}
                    for index, control in enumerate(state['draft']['controls'])
                },
                'decorations': {
                    'machine': {'kind': 'image', 'label': 'Machine', 'image': image_id,
                                'locked': True, 'x': 0, 'y': 0, 'width': 640, 'height': 400},
                },
            }
            state['draft']['identity_publication'] = {'enabled': True, 'username_tag': 'PackageUser', 'privileges_tag': 'PackagePrivileges', 'bits': [{'bit': 31, 'source': 'permission', 'name': 'security.manage'}]}
            alarm_button = next(control for control in state['draft']['controls'] if control['kind'] == 'button')
            alarm_button['action'] = 'toggle_alarm'
            saved = json.loads(request('/api/project/draft', {'expected_revision': state['draft_revision'], 'project': state['draft']}, 'PUT'))
            request('/api/project/apply', {'expected_revision': saved['draft_revision']}, 'POST')
            request('/api/controls/package_number/value', {'value': 25.0}, 'PUT')
            request('/api/controls/package_text/value', {'value': 'ab'}, 'PUT')
            try:
                request('/api/controls/package_text/value', {'value': 'too long'}, 'PUT')
                raise AssertionError('Packaged text limit was not enforced')
            except urllib.error.HTTPError as error:
                assert error.code == 422
            report['bounded_numeric_and_text_edits'] = True
            capture = json.loads(request('/api/trends/package_trend', {'action': 'start'}, 'POST'))
            capture_path = f'/api/trend-captures/{capture["id"]}'
            for _ in range(50):
                if json.loads(request(capture_path))['samples']:
                    break
                time.sleep(.1)
            else:
                raise AssertionError('Packaged trend recorded no samples')
            request('/api/trends/package_trend', {'action': 'stop', 'capture_id': capture['id']}, 'POST')
            trend_csv = request(capture_path + '/csv')
            values = {(row['tag'], row['value']) for row in csv.DictReader(StringIO(trend_csv.decode()))}
            assert ('TankLevel', '25.0') in values
            assert values & {('MotorRunning', 'true'), ('MotorRunning', 'false')}
            asset_path = '/api/canvas-images/' + image_id
            canvas_image = request(asset_path)
            assert canvas_image[:4] == b'RIFF' and canvas_image[8:12] == b'WEBP'
            request(f'/api/controls/{alarm_button["id"]}/activate', {}, 'POST')
            alarm = json.loads(request('/api/alarms/occurrences'))['items'][0]
            shelved = json.loads(request(f'/api/alarms/occurrences/{alarm["occurrence_id"]}/shelve', {'duration_seconds': 3600, 'reason': 'Packaged shelf fixture'}, 'POST'))
            assert json.loads(request('/api/alarms'))['annunciated_outstanding'] == []
            report['timed_shelving_does_not_clear_alarm'] = json.loads(request('/api/alarms'))['active_count'] == 1
            assert report['timed_shelving_does_not_clear_alarm']
            backup = request('/api/workspace/backup')
            (work / 'fixture-backup.zip').write_bytes(backup)
            denied = subprocess.run([str(executable), '--project', str(project), '--port', str(port + 1 if port < 65535 else port - 1)],
                                    cwd=work, env=env, capture_output=True, text=True, timeout=15, creationflags=hidden)
            assert denied.returncode != 0 and 'Another OpenHMI runtime owns' in denied.stderr
            report['second_runtime_rejected'] = True
        finally:
            # Forced-stop drill of this exact owned process. No PID enumeration or shared process cleanup.
            child.kill(); child.wait(timeout=10)
        # Synthetic project-local administrator, never a Windows account or production credential.
        # Windows getpass reads the console, not redirected stdin. Seed only this
        # owned offline fixture through the source security API, then authenticate
        # through the executable. Interactive CLI prompting is a separate drill.
        from openhmi.projects import ProjectStore
        from openhmi.security import Security
        from openhmi.security_routes import SecurityChange
        fixture = ProjectStore(project)
        try:
            security = Security(fixture)
            security.change(SecurityChange(operation='user', name='package_operator', groups=['Administrators'],
                            password='PackageSmokeOnly-2026!', expected_version=security.snapshot()['version'],
                            reason='Synthetic offline package fixture'), 'package-smoke-fixture')
        finally:
            fixture.close()
        report['synthetic_account_fixture'] = 'Source API seed while packaged process is stopped; executable login verified below'
        child = start(log)
        try:
            request('/api/security/login', {'name': 'package_operator', 'password': 'PackageSmokeOnly-2026!'}, 'POST')
            request('/api/security/publication/claim', {'client': 'package-fixture'}, 'POST')
            for _ in range(50):
                if json.loads(request('/api/tags'))['values']['PackagePrivileges'] == -2147483648:
                    break
                time.sleep(.1)
            else:
                raise AssertionError('Packaged identity word was not published')
            assert json.loads(request('/api/tags'))['values']['PackageUser'] == 'package_operator'
            report['authenticated_identity_publication_bit31'] = True
            assert json.loads(request('/api/project'))['active']['title'] == 'Packaged restart fixture'
            assert json.loads(request('/api/alarms/shelves'))['items'][0]['expires_at'] == shelved['expires_at']
            report['forced_restart_preserved_project'] = True
            target = base + '/api/workspace/import?name=Restored'
            with opener.open(urllib.request.Request(target, backup, method='POST'), timeout=10) as response:
                assert response.status == 200
            request('/api/workspace/open', {'file': 'Restored.openhmi.sqlite3'}, 'POST')
            restored = json.loads(request('/api/project'))['active']
            assert restored['title'] == 'Packaged restart fixture'
            machine = restored['layout']['decorations']['machine']
            assert machine['locked'] is True and machine['image'] == image_id
            assert request(asset_path) == canvas_image
            assert request(capture_path + '/csv') == trend_csv
            report['canvas_image_and_trend_csv_preserved_by_backup'] = True
            assert json.loads(request('/api/tags'))['plc_hold'] is True
            shelf = json.loads(request('/api/alarms/shelves'))['items'][0]
            assert shelf['expires_at'] == shelved['expires_at']
            request(f'/api/alarms/shelves/{shelf["alarm_id"]}/restore', {'expected_operation_id': shelf['operation_id'], 'reason': 'Packaged restore fixture'}, 'POST')
            assert json.loads(request('/api/alarms/shelves'))['items'] == []
            assert json.loads(request('/api/alarms'))['unacknowledged_count'] == 1
            report['shelf_restart_backup_expiry_and_early_restore'] = True
            report['backup_restore_preserved_project_and_hold'] = True
        finally:
            child.kill(); child.wait(timeout=10)
    assert (project.parent / 'logs/runtime.log').stat().st_size > 0
    report['rotating_log_created'] = True
    report['graceful_console_shutdown'] = 'not exercised by this forced-stop drill'
    report['clean_machine_acceptance'] = 'not performed'
    (work / 'report.json').write_bytes((json.dumps(report, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
