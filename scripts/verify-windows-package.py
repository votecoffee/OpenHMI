"""Bounded offline smoke drill against an extracted package; no real PLC routes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request


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
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0)); port = reservation.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    def request(path, data=None, method=None):
        body = json.dumps(data).encode() if data is not None else None
        with urllib.request.urlopen(urllib.request.Request(base + path, body, {'Content-Type': 'application/json'}, method=method), timeout=5) as response:
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
            saved = json.loads(request('/api/project/draft', {'expected_revision': state['draft_revision'], 'project': state['draft']}, 'PUT'))
            request('/api/project/apply', {'expected_revision': saved['draft_revision']}, 'POST')
            backup = request('/api/workspace/backup')
            (work / 'fixture-backup.zip').write_bytes(backup)
            denied = subprocess.run([str(executable), '--project', str(project), '--port', str(port + 1 if port < 65535 else port - 1)],
                                    cwd=work, env=env, capture_output=True, text=True, timeout=15, creationflags=hidden)
            assert denied.returncode != 0 and 'Another OpenHMI runtime owns' in denied.stderr
            report['second_runtime_rejected'] = True
        finally:
            # Forced-stop drill of this exact owned process. No PID enumeration or shared process cleanup.
            child.kill(); child.wait(timeout=10)
        child = start(log)
        try:
            assert json.loads(request('/api/project'))['active']['title'] == 'Packaged restart fixture'
            report['forced_restart_preserved_project'] = True
            target = base + '/api/workspace/import?name=Restored'
            with urllib.request.urlopen(urllib.request.Request(target, backup, method='POST'), timeout=10) as response:
                assert response.status == 200
            request('/api/workspace/open', {'file': 'Restored.openhmi.sqlite3'}, 'POST')
            assert json.loads(request('/api/project'))['active']['title'] == 'Packaged restart fixture'
            assert json.loads(request('/api/tags'))['plc_hold'] is True
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
