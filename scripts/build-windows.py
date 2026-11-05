"""Build a portable Windows preview from a dedicated, pinned build environment."""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments):
    subprocess.run([str(value) for value in arguments], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New output directory; existing paths are never replaced')
    args = parser.parse_args()
    if sys.platform != 'win32' or platform.machine().upper() not in ('AMD64', 'X86_64'):
        parser.error('This preview build requires Windows x64')
    if sys.version_info[:2] != (3, 14):
        parser.error('Use standard CPython 3.14 x64 for this pinned preview')
    # Fail before building if the dedicated environment drifts from the reviewed lock.
    locked = set()
    for line in (ROOT / 'requirements/windows-build.lock').read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        name, expected = line.split('==')
        locked.add(name.lower().replace('_', '-'))
        if metadata.version(name) != expected:
            parser.error(f'Build dependency differs from lock: {name}')
    installed = {item.metadata['Name'].lower().replace('_', '-') for item in metadata.distributions()}
    if installed - locked - {'pip', 'openhmi'}:
        parser.error('Use a dedicated build environment; unexpected extra dependencies are installed')
    if not (ROOT / 'openhmi/web/vendor/app.js').is_file():
        parser.error('Contributors must build browser assets before packaging (npm ci; npm run build)')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    local = ROOT / '.local'
    local.mkdir(exist_ok=True)
    # Each invocation owns a new work directory. Preserve build evidence, never clear shared paths.
    work = Path(tempfile.mkdtemp(prefix='windows-build-', dir=local))
    run(sys.executable, '-m', 'pip', 'install', '--no-deps', '--no-build-isolation', ROOT)
    run(sys.executable, '-m', 'PyInstaller', '--onedir', '--console', '--name', 'OpenHMI',
        '--distpath', output, '--workpath', work / 'work', '--specpath', work,
        '--paths', ROOT, '--collect-data', 'openhmi', '--recursive-copy-metadata', 'openhmi',
        '--collect-submodules', 'pycomm3', '--hidden-import', 'uvicorn.loops.asyncio',
        '--hidden-import', 'uvicorn.protocols.http.h11_impl', '--hidden-import', 'uvicorn.lifespan.on',
        ROOT / 'scripts/windows-entry.py')
    bundle = output / 'OpenHMI'
    shutil.copyfile(ROOT / 'LICENSE', bundle / 'LICENSE.txt')
    shutil.copyfile(ROOT / 'docs/windows-package.md', bundle / 'READ-ME.md')
    shutil.copyfile(ROOT / 'requirements/windows-build.lock', bundle / 'BUILD-DEPENDENCIES.lock')
    inventory = []
    notices = ['OpenHMI build environment dependency notices (includes build tools)\n']
    for distribution in sorted(metadata.distributions(), key=lambda item: item.metadata['Name'].lower()):
        name, release = distribution.metadata['Name'], distribution.version
        inventory.append({'name': name, 'version': release})
        notices.append(f'\n===== {name} {release} =====\n')
        for file in distribution.files or []:
            if '.dist-info' in str(file) and any(part.lower().startswith(('license', 'licence', 'copying', 'notice')) for part in file.parts):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    notices.append(source.read_text(encoding='utf-8', errors='replace'))
    (bundle / 'PYTHON-DEPENDENCY-NOTICES.txt').write_bytes('\n'.join(notices).encode('utf-8'))
    (bundle / 'PYTHON-LICENSE.txt').write_bytes((Path(sys.base_prefix) / 'LICENSE.txt').read_bytes())
    assets = ROOT / 'openhmi/web'
    for source, name in [('assets/fonts/OFL.txt', 'FONT-LICENSE.txt'), ('assets/flags/LICENSE.txt', 'FLAG-LICENSE.txt'), ('vendor/THIRD-PARTY-LICENSES.txt', 'BROWSER-DEPENDENCY-NOTICES.txt')]:
        shutil.copyfile(assets / source, bundle / name)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    manifest = {'format': 'OpenHMI-windows-preview', 'version': metadata.version('openhmi'),
                'source_commit': commit, 'source_dirty': dirty, 'python': platform.python_version(),
                'platform': platform.platform(), 'dependencies': inventory,
                'files': {path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted(bundle.rglob('*')) if path.is_file()}}
    (bundle / 'manifest.json').write_bytes((json.dumps(manifest, indent=2) + '\n').encode('utf-8'))
    archive = output / f'OpenHMI-{metadata.version("openhmi")}-windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                zipped.write(path, path.relative_to(output))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_bytes(f'{digest}  {archive.name}\n'.encode('ascii'))
    print(f'Built {archive}\nSHA256 {digest}\nBuild work retained in {work}')


if __name__ == '__main__':
    main()
