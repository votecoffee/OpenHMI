"""Offline, integrity-checked side-by-side Windows preview installation."""
import argparse
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import zipfile

MAX_ARCHIVE = 256 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024
MAX_FILES = 5000


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def relative_name(name):
    if not isinstance(name, str):
        raise ValueError('Package paths must be strings')
    parts = PurePosixPath(name).parts
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in '0123456789¹²³'), *(f'LPT{i}' for i in '0123456789¹²³')}
    if not name or len(name) > 240 or name.startswith('/') or '\\' in name or ':' in name:
        raise ValueError('Invalid package path')
    if '/'.join(parts) != name or any(part in ('.', '..') or part.endswith(('.', ' ')) or part.split('.')[0].rstrip(' .').upper() in reserved or any(ord(c) < 32 or c in '<>"|?*' for c in part) for part in parts):
        raise ValueError('Invalid Windows package path')
    return name


def read_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON package metadata key')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def manifest_value(data):
    manifest = read_json(data)
    if not isinstance(manifest, dict) or manifest.get('format') != 'OpenHMI-windows-preview' or manifest.get('source_dirty') is not False:
        raise ValueError('Only clean-source OpenHMI Windows preview packages are accepted')
    if not isinstance(manifest.get('source_commit'), str) or not isinstance(manifest.get('version'), str) or not re.fullmatch(r'[a-f0-9]{40}', manifest['source_commit']) or not re.fullmatch(r'[A-Za-z0-9._+\-]{1,60}', manifest['version']):
        raise ValueError('Invalid package source/version identity')
    files = manifest.get('files')
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES or 'OpenHMI.exe' not in files or 'manifest.json' in files:
        raise ValueError('Invalid package file inventory')
    names = [relative_name(name).casefold() for name in files]
    if len(set(names)) != len(names) or any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value) for value in files.values()):
        raise ValueError('Invalid or colliding package file hashes')
    return manifest


def linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


class Packages:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.releases = self.root / 'releases'

    @contextmanager
    def locked(self):
        # Reuse the proven OS-lock primitive in a separate manager-owned folder.
        from .launcher import library_lock
        with library_lock(self.root / 'manager-lock'):
            yield

    def release(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{64}', identifier):
            raise ValueError('Release ID must be the package SHA-256')
        path = self.releases / identifier[:24]
        if linked(self.releases) or linked(path) or path.resolve().parent != self.releases.resolve() or not path.resolve().is_relative_to(self.root):
            raise ValueError('Release must stay inside the installation root')
        return path

    def install(self, archive, expected):
        archive = Path(archive)
        with archive.open('rb') as stream:
            payload = stream.read(MAX_ARCHIVE + 1)
        if not re.fullmatch(r'[a-f0-9]{64}', expected) or len(payload) > MAX_ARCHIVE or hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError('Archive size or expected SHA-256 does not match')
        with self.locked():
            target = self.release(expected)
            if target.exists():
                return self.verify(expected)
            self.releases.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(BytesIO(payload)) as zipped:
                entries = zipped.infolist()
                if len(entries) > MAX_FILES + 1 or sum(entry.file_size for entry in entries) > MAX_EXPANDED:
                    raise ValueError('Package expanded size/file count exceeds limits')
                names = []
                for entry in entries:
                    name = relative_name(entry.filename)
                    if not name.startswith('OpenHMI/') or entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                        raise ValueError('Package must contain ordinary unencrypted OpenHMI files')
                    names.append(name)
                if len({name.casefold() for name in names}) != len(names) or 'OpenHMI/manifest.json' not in names:
                    raise ValueError('Missing manifest or duplicate package entries')
                if zipped.getinfo('OpenHMI/manifest.json').file_size > 2 * 1024 * 1024:
                    raise ValueError('Manifest exceeds size limit')
                encoded = zipped.read('OpenHMI/manifest.json')
                manifest = manifest_value(encoded)
                if set(names) != {'OpenHMI/manifest.json', *('OpenHMI/' + name for name in manifest['files'])}:
                    raise ValueError('ZIP entries differ from the manifest inventory')
                stage = Path(tempfile.mkdtemp(prefix='incoming-', dir=self.root))
                for entry in entries:
                    output = stage / entry.filename
                    if not output.resolve().is_relative_to(stage):
                        raise ValueError('Package path escaped staging')
                    output.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    with zipped.open(entry) as source, output.open('xb') as destination:
                        while chunk := source.read(1024 * 1024):
                            destination.write(chunk); digest.update(chunk)
                    name = entry.filename[len('OpenHMI/'):]
                    if name != 'manifest.json' and digest.hexdigest() != manifest['files'][name]:
                        raise ValueError('Package file hash mismatch: ' + name)
                record = {'format': 'OpenHMI-installed-package', 'archive_sha256': expected, 'manifest_sha256': hashlib.sha256(encoded).hexdigest()}
                (stage / 'installation.json').write_bytes((json.dumps(record, indent=2) + '\n').encode('utf-8'))
                # New owned staging and destination paths are checked before the directory rename.
                if linked(stage) or not stage.resolve().is_relative_to(self.root) or not target.resolve().is_relative_to(self.root) or target.exists():
                    raise ValueError('Installation paths changed during staging')
                stage.rename(target)
            return self.verify(expected)

    def verify(self, identifier):
        release = self.release(identifier)
        record_path = release / 'installation.json'
        bundle = release / 'OpenHMI'
        if linked(record_path) or linked(bundle) or record_path.stat().st_size > 1024 * 1024:
            raise ValueError('Installed metadata may not be a link')
        record = read_json(record_path.read_bytes())
        manifest_path = bundle / 'manifest.json'
        if not isinstance(record, dict) or record.get('format') != 'OpenHMI-installed-package' or record.get('archive_sha256') != identifier or linked(manifest_path) or manifest_path.stat().st_size > 2 * 1024 * 1024 or sha256(manifest_path) != record.get('manifest_sha256'):
            raise ValueError('Installed manifest identity mismatch')
        manifest = manifest_value(manifest_path.read_bytes())
        actual = set()
        expanded = 0
        for path in bundle.rglob('*'):
            if linked(path) or not path.resolve().is_relative_to(bundle.resolve()):
                raise ValueError('Installed package contains a link or escaped path')
            if path.is_file():
                actual.add(path.relative_to(bundle).as_posix())
                expanded += path.stat().st_size
                if len(actual) > MAX_FILES + 1 or expanded > MAX_EXPANDED:
                    raise ValueError('Installed package exceeds size/file limits')
        if actual != {'manifest.json', *manifest['files']}:
            raise ValueError('Installed file inventory changed')
        for name, digest in manifest['files'].items():
            if sha256(bundle / name) != digest:
                raise ValueError('Installed file hash mismatch: ' + name)
        return {'release': identifier, 'version': manifest['version'], 'source_commit': manifest['source_commit'], 'verified_files': len(manifest['files'])}

    def current(self):
        path = self.root / 'active.json'
        if linked(path):
            raise ValueError('Active selection may not be a link')
        if not path.exists():
            return None
        if linked(path) or path.stat().st_size > 65536:
            raise ValueError('Active selection may not be a link')
        value = read_json(path.read_bytes())
        if not isinstance(value, dict) or value.get('format') != 'OpenHMI-active-package' or value.get('version') != 1:
            raise ValueError('Unrecognized active selection; existing file preserved')
        self.release(value.get('release'))
        return value

    def activate(self, identifier):
        with self.locked():
            verified = self.verify(identifier)
            previous = self.current()
            value = {'format': 'OpenHMI-active-package', 'version': 1, 'release': identifier, 'previous': previous['release'] if previous else None}
            fd, name = tempfile.mkstemp(prefix='selection-', suffix='.json', dir=self.root)
            with os.fdopen(fd, 'wb') as stream:
                stream.write((json.dumps(value, indent=2) + '\n').encode('utf-8')); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, self.root / 'active.json')
            return {**verified, 'previous': value['previous']}

    def listing(self):
        selection = self.current()
        result = []
        if self.releases.is_dir():
            for path in sorted(self.releases.iterdir()):
                if re.fullmatch(r'[a-f0-9]{24}', path.name):
                    try:
                        record = path / 'installation.json'
                        if linked(path) or linked(record) or record.stat().st_size > 1024 * 1024:
                            raise ValueError('Invalid installation record')
                        metadata = read_json(record.read_bytes())
                        identifier = metadata.get('archive_sha256') if isinstance(metadata, dict) else None
                        if self.release(identifier) != path:
                            raise ValueError('Installation folder does not match archive identity')
                        result.append({**self.verify(identifier), 'active': bool(selection and identifier == selection['release'])})
                    except (OSError, ValueError) as error:
                        result.append({'directory': path.name, 'error': str(error), 'active': bool(selection and path.name == selection['release'][:24])})
        return {'active': selection, 'releases': result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'OpenHMI/application' if getattr(sys, 'frozen', False) else Path('.local/application')
    parser.add_argument('--root', type=Path, default=root, help='Application versions only; project data remains separate')
    sub = parser.add_subparsers(dest='operation', required=True)
    install = sub.add_parser('install'); install.add_argument('archive', type=Path); install.add_argument('--sha256', required=True)
    for operation in ('activate', 'verify'):
        sub.add_parser(operation).add_argument('release')
    sub.add_parser('list')
    launch = sub.add_parser('launch')
    launch.add_argument('--project', type=Path); launch.add_argument('--port', type=int, default=8000)
    launch.add_argument('--handlers', type=Path); launch.add_argument('--log-dir', type=Path)
    launch.add_argument('--open-browser', action='store_true')
    mode = launch.add_mutually_exclusive_group()
    mode.add_argument('--self-check', action='store_true')
    mode.add_argument('--preflight', action='store_true')
    mode.add_argument('--check-windows-mappings', action='store_true')
    args = parser.parse_args(argv)
    packages = Packages(args.root)
    try:
        if args.operation == 'install': result = packages.install(args.archive, args.sha256)
        elif args.operation == 'activate': result = packages.activate(args.release)
        elif args.operation == 'verify': result = packages.verify(args.release)
        elif args.operation == 'list': result = packages.listing()
        else:
            selection = packages.current()
            if not selection: raise ValueError('Install and activate an application package first')
            packages.verify(selection['release'])
            arguments = []
            for field in ('project', 'log_dir'):
                value = getattr(args, field)
                if value:
                    if value.resolve().is_relative_to(packages.root): raise ValueError('Project data and logs must stay outside the application installation')
                    arguments += ['--' + field.replace('_', '-'), str(value.resolve())]
            if args.handlers: arguments += ['--handlers', str(args.handlers.resolve())]
            arguments += ['--port', str(args.port)]
            if args.open_browser: arguments += ['--open-browser']
            if args.self_check: arguments += ['--self-check']
            if args.preflight: arguments += ['--preflight']
            if args.check_windows_mappings: arguments += ['--check-windows-mappings']
            executable = packages.release(selection['release']) / 'OpenHMI/OpenHMI.exe'
            with subprocess.Popen([str(executable), *arguments]) as runtime:
                while True:
                    try:
                        exit_code = runtime.wait()
                        break
                    except KeyboardInterrupt:
                        # The runtime shares this console and handles Ctrl+C itself.
                        # Keep waiting so it can finish shutdown and release its library.
                        continue
            raise SystemExit(exit_code)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        parser.exit(1, f'OpenHMI package: {error}\n')


if __name__ == '__main__':
    main()
