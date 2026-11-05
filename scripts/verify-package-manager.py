"""Exercise the frozen package manager against new owned application/data roots."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manager', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--update', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    executable = args.manager.resolve()
    work = args.work.resolve(); work.mkdir(parents=True, exist_ok=False)
    applications = work / 'applications'
    projects = work / 'projects'; projects.mkdir()
    # Only fixture data: no runtime, handler execution or controller connection.
    from openhmi.projects import ProjectStore
    from openhmi.security import Security
    store = ProjectStore(projects / 'Fixture.openhmi.sqlite3')
    Security(store)
    store.close()
    (projects / 'external-handler.py').write_bytes(b'# Synthetic external handler preservation marker\n')
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in projects.iterdir() if path.is_file()}
    env = dict(os.environ); env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    env.pop('PYTHONHOME', None); env.pop('PYTHONPATH', None)
    def command(*arguments):
        result = subprocess.run([str(executable), 'package', '--root', str(applications), *map(str, arguments)],
                                cwd=work, env=env, capture_output=True, text=True, timeout=60,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError(f'Packaged manager command failed: {arguments[0]}: {result.stderr}')
        return json.loads(result.stdout)
    old = args.package.resolve(); new = args.update.resolve()
    first = hashlib.sha256(old.read_bytes()).hexdigest()
    second = hashlib.sha256(new.read_bytes()).hexdigest()
    if first == second:
        raise ValueError('Use two distinct preview archives for the update/rollback drill')
    installed = command('install', old, '--sha256', first)
    command('activate', first)
    old_check = command('launch', '--self-check')
    updated = command('install', new, '--sha256', second)
    assert command('list')['active']['release'] == first, 'Install activated an update unexpectedly'
    command('activate', second)
    new_check = command('launch', '--self-check')
    assert new_check['frozen'] and old_check['frozen']
    command('activate', first)
    assert command('list')['active']['release'] == first
    command('launch', '--self-check')
    assert len(command('list')['releases']) == 2
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in projects.iterdir() if path.is_file()}
    assert before == after, 'Package management changed fixture project/external-handler bytes'
    report = {'initial': installed, 'updated': updated, 'rollback_release': first,
              'retained_versions': 2, 'project_and_external_handler_hashes_unchanged': before == after,
              'selected_versions_self_check': {'initial': old_check, 'updated': new_check},
              'child_path_without_python_or_node': True,
              'scope': 'Build-machine frozen manager/install/update/selection/rollback checks; self-check only, not database downgrade or clean-machine acceptance.'}
    (work / 'report.json').write_bytes((json.dumps(report, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
