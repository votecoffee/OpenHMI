"""Local runtime entry point for source installs and the portable Windows package."""
import argparse
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
import json
import logging.config
import os
from pathlib import Path
import sys
import threading
import webbrowser


def application_version():
    try:
        return version('openhmi')
    except PackageNotFoundError:
        return 'development'


def default_project():
    if getattr(sys, 'frozen', False):
        root = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
        return root / 'OpenHMI' / 'projects' / 'Default.openhmi.sqlite3'
    return Path('.local/project.sqlite3')


@contextmanager
def library_lock(directory):
    """Hold an OS lock, not a PID file. Never unlink a lock another waiter may open."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / '.openhmi-runtime.lock'
    with path.open('a+b') as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError(f'Another OpenHMI runtime owns this project library: {directory}') from error
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def log_configuration(directory):
    directory.mkdir(parents=True, exist_ok=True)
    return {
        'version': 1, 'disable_existing_loggers': False,
        'formatters': {'runtime': {'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'}},
        'handlers': {
            'console': {'class': 'logging.StreamHandler', 'formatter': 'runtime', 'stream': 'ext://sys.stderr'},
            'file': {'class': 'logging.handlers.RotatingFileHandler', 'formatter': 'runtime',
                     'filename': str(directory / 'runtime.log'), 'maxBytes': 5 * 1024 * 1024,
                     'backupCount': 3, 'encoding': 'utf-8'},
        },
        'root': {'level': 'INFO', 'handlers': ['console', 'file']},
        'loggers': {name: {'handlers': [], 'propagate': True, 'level': 'INFO'} for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access')},
    }


def self_check():
    # Import native/runtime dependencies without creating a project or opening a PLC.
    from PIL import Image
    from pycomm3 import LogixDriver
    from .windows_identity import WindowsIdentity
    assets = Path(__file__).parent / 'web'
    required = ['index.html', 'vendor/app.js', 'vendor/app.css', 'vendor/THIRD-PARTY-LICENSES.txt',
                'assets/fonts/NotoSansSC.ttf', 'assets/flags/us.svg']
    missing = [name for name in required if not (assets / name).is_file()]
    if missing:
        raise RuntimeError('Incomplete application package; missing assets: ' + ', '.join(missing))
    return {'version': application_version(), 'python': sys.version.split()[0], 'frozen': bool(getattr(sys, 'frozen', False)),
            'platform': sys.platform, 'windows_identity_available': WindowsIdentity().available,
            'dependencies': {name: version(name) for name in ('fastapi', 'pydantic', 'uvicorn', 'pillow', 'pycomm3')},
            'assets': 'present'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='OpenHMI local visual builder and runtime')
    parser.add_argument('--version', action='version', version=f'OpenHMI {application_version()}')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--self-check', action='store_true', help='Check bundled dependencies/assets without starting a project')
    mode.add_argument('--create-admin', metavar='USER', help='Create a local administrator while the runtime is stopped; password is prompted')
    parser.add_argument('--project', type=Path, default=default_project(), help='Database path; its folder is the project library')
    parser.add_argument('--handlers', type=Path, help='Trusted local Python action module loaded at startup')
    parser.add_argument('--recipe-users', type=Path, default=None if getattr(sys, 'frozen', False) else Path('.local/recipe-users.json'), help='Optional legacy recipe account file')
    parser.add_argument('--port', type=int, default=8000, help='Local HTTP port (default 8000)')
    parser.add_argument('--log-dir', type=Path, help='Rotating log folder (default: logs inside the project library)')
    parser.add_argument('--open-browser', action='store_true', help='Open the designer after this server starts')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535')
    try:
        if args.self_check:
            print(json.dumps(self_check(), indent=2))
            return
        project = args.project.resolve()
        with library_lock(project.parent):
            if args.create_admin:
                from .security import main as create_admin
                create_admin(['--project', str(project), '--user', args.create_admin])
                return
            self_check()
            logs = (args.log_dir or project.parent / 'logs').resolve()
            logging.config.dictConfig(log_configuration(logs))
            from .workspace import ProjectWorkspace
            import uvicorn
            url = f'http://127.0.0.1:{args.port}'
            logging.info('OpenHMI %s; project=%s; logs=%s; URL=%s; stop with Ctrl+C', application_version(), project, logs, url)
            workspace = ProjectWorkspace(project, args.handlers, args.recipe_users)
            config = uvicorn.Config(workspace, host='127.0.0.1', port=args.port, log_config=None,
                                    loop='asyncio', http='h11', ws='none')
            server = uvicorn.Server(config)
            finished = threading.Event()
            def open_when_started():
                while not finished.wait(.1):
                    if server.started:
                        webbrowser.open(url)
                        return
            if args.open_browser:
                threading.Thread(target=open_when_started, daemon=True).start()
            try:
                server.run()
            except KeyboardInterrupt:
                # Uvicorn completes lifespan shutdown, then asyncio re-raises Ctrl+C.
                # Treat that ordinary console stop as success in a frozen executable.
                logging.info('OpenHMI stopped by console operator')
            finally:
                finished.set()
    except (OSError, RuntimeError) as error:
        parser.exit(1, f'OpenHMI: {error}\n')


if __name__ == '__main__':
    main()
