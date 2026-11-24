"""Local project library and complete, checksummed SQLite backup archives."""

import asyncio
from contextlib import closing
import hashlib
from io import BytesIO
import json
import logging
from pathlib import Path
import re
import sqlite3
import tempfile
import zipfile

from pydantic import ValidationError
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from .http_context import require_project_instance, set_response_context
from .async_cleanup import finish_cleanup
from .project_models import Project, default_project
from .projects import ProjectStore
from .workspace_publication import PublicationError, ensure_available, publish_project
from .workspace_inventory import ArtifactQuery, InventoryUnavailable, inventory
from .workspace_contracts import LibrarySnapshot, CreatedProject, ImportedProject, OpenedProject
from .workspace_import import import_response
from .workspace_mutations import mutation_response
from .http_snapshot import prepare_snapshot

MAX_BACKUP = 256 * 1024 * 1024
TABLES = {'security_group_style', 'alarm_shelf', 'project', 'recipe_entry', 'recipe_revision', 'recipe_image', 'recipe_audit', 'recipe_policy', 'recipe_selection',
          'security_settings', 'security_group', 'security_user', 'security_windows', 'security_audit', 'tag_history',
          'alarm_config', 'alarm_state', 'alarm_occurrence', 'alarm_event', 'alarm_meta', 'alarm_acknowledgement', 'alarm_event_context', 'alarm_note', 'operator_activity', 'command_transaction', 'command_event', 'recipe_transfer', 'project_storage', 'project_revision', 'project_recovery', 'trend_capture', 'trend_frame', 'canvas_image', 'sqlite_sequence'}


class ProjectWorkspace:
    def __init__(self, path, handlers=None, recipe_users=None, *, hold_connections=False):
        self.path = Path(path).resolve()
        self.root = self.path.parent
        self.root.mkdir(parents=True, exist_ok=True)
        self.handlers, self.recipe_users = handlers, recipe_users
        self.hold_connections = hold_connections
        self.lock = asyncio.Lock()
        self.upload_lock = asyncio.Lock()
        self.mutation_slots = asyncio.BoundedSemaphore(4)
        self.stopping = False
        self.context = None
        self.current = self._app(self.path, handlers)

    def _app(self, path, handlers=None):
        from .server import create_app
        hold = self.hold_connections or path.with_suffix('.hold').exists()
        legacy = path.with_suffix('.recipe-users.json')
        app = create_app(path, handlers, legacy if legacy.exists() else self.recipe_users, hold_connections=hold)
        app.state.release_connections = lambda: path.with_suffix('.hold').unlink(missing_ok=True)
        return app

    def target(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,59}', name):
            raise HTTPException(422, 'Use a project ID of letters, numbers, underscores or hyphens, starting with a letter')
        path = self.root / f'{name}.openhmi.sqlite3'
        if path.is_symlink() or path.resolve().parent != self.root:
            raise HTTPException(422, 'Project must stay in the local library')
        return path

    def listing(self):
        files = [path for path in self.root.glob('*.openhmi.sqlite3') if not path.is_symlink()]
        if self.path not in files:
            files.insert(0, self.path)
        return LibrarySnapshot(current=self.path.name, projects=[{'file': path.name, 'current': path == self.path} for path in files],
                               handlers=bool(self.handlers), plc_hold=self.current.state.driver.plc_hold).model_dump()

    def export(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / 'project.sqlite3'
            with self.current.state.store._lock, closing(sqlite3.connect(backup)) as destination:
                self.current.state.store._db.backup(destination)
            if backup.stat().st_size > MAX_BACKUP:
                raise HTTPException(413, 'Project exceeds the 256 MiB browser backup limit')
            files = {'project.sqlite3': backup.read_bytes()}
            if self.handlers:
                files['handlers.py'] = Path(self.handlers).read_bytes()
            legacy = self.path.with_suffix('.recipe-users.json')
            if legacy.exists():
                files['recipe-users.json'] = legacy.read_bytes()
            elif isinstance(self.recipe_users, Path) and self.recipe_users.exists():
                files['recipe-users.json'] = self.recipe_users.read_bytes()
            elif isinstance(self.recipe_users, dict):
                files['recipe-users.json'] = json.dumps(self.recipe_users).encode('utf-8')
            if sum(len(data) for data in files.values()) > MAX_BACKUP - 8192:
                raise HTTPException(413, 'Project exceeds the 256 MiB browser backup limit')
            manifest = {'format': 'OpenHMI-backup', 'version': 1, 'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
            output = BytesIO()
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                archive.writestr('manifest.json', json.dumps(manifest, indent=2))
                for name, data in files.items():
                    archive.writestr(name, data)
            data = output.getvalue()
            if len(data) > MAX_BACKUP:
                raise HTTPException(413, 'Project exceeds the 256 MiB browser backup limit')
            return data

    def import_backup(self, name, data):
        target = self.target(name)
        if target.exists():
            raise HTTPException(409, 'Project already exists; import uses a new project ID')
        try:
            ensure_available(target)
            with zipfile.ZipFile(BytesIO(data)) as archive:
                entries = archive.infolist()
                names = [item.filename for item in entries]
                if len(names) != len(set(names)) or not {'manifest.json', 'project.sqlite3'} <= set(names) or not set(names) <= {'manifest.json', 'project.sqlite3', 'handlers.py', 'recipe-users.json'}:
                    raise ValueError('Unexpected or duplicate backup entries')
                if sum(item.file_size for item in entries) > MAX_BACKUP or archive.getinfo('manifest.json').file_size > 8192:
                    raise ValueError('Backup expands beyond the import limit')
                manifest = json.loads(archive.read('manifest.json'))
                if manifest.get('format') != 'OpenHMI-backup' or manifest.get('version') != 1:
                    raise ValueError('Unsupported backup format')
                files = {entry: archive.read(entry) for entry in names if entry != 'manifest.json'}
                if manifest['files'] != {key: hashlib.sha256(value).hexdigest() for key, value in files.items()}:
                    raise ValueError('Backup checksum verification failed')
                if 'recipe-users.json' in files:
                    from .recipe_auth import RecipeAuth
                    if len(files['recipe-users.json']) > 1024 * 1024:
                        raise ValueError('Legacy recipe account file exceeds 1 MiB')
                    RecipeAuth(json.loads(files['recipe-users.json']))
            with tempfile.TemporaryDirectory(dir=self.root) as directory:
                temporary = Path(directory) / 'project.sqlite3'
                temporary.write_bytes(files['project.sqlite3'])
                with closing(sqlite3.connect(temporary)) as db:
                    db.execute('PRAGMA trusted_schema=OFF')
                    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('Project database integrity check failed')
                    schema = db.execute("SELECT type,name FROM sqlite_master WHERE type IN ('table','view','trigger')").fetchall()
                    if any(kind != 'table' or table not in TABLES for kind, table in schema):
                        raise ValueError('Unsupported project schema or executable SQL objects')
                    state = json.loads(db.execute('SELECT state FROM project WHERE id=1').fetchone()[0])
                    Project.model_validate(state['draft'])
                    Project.model_validate(state['active'])
                # Construct without starting lifespan: validation cannot contact a PLC or execute handlers.
                candidate = self._app(temporary)
                try:
                    candidate.state.store.verify_history()
                    candidate.state.store.fork_identity()
                finally:
                    candidate.state.store.close()
                extras = {target.with_suffix('.hold'): b'Imported PLC connections require Apply live.\n'}
                if 'handlers.py' in files:
                    extras[target.with_suffix('.handlers.py')] = files['handlers.py']
                if 'recipe-users.json' in files:
                    extras[target.with_suffix('.recipe-users.json')] = files['recipe-users.json']
                publish_project(temporary, target, extras)
        except PublicationError as error:
            raise HTTPException(error.status, str(error)) from error
        except OSError as error:
            logging.exception('Project import could not finish')
            raise HTTPException(503, 'Project import could not finish. Review the project library before retrying.') from error
        except HTTPException:
            raise
        except (ValueError, KeyError, TypeError, sqlite3.Error, zipfile.BadZipFile, RuntimeError) as error:
            raise HTTPException(422, f'Invalid OpenHMI backup: {error}') from error
        return ImportedProject(file=target.name, handlers_saved_for_review='handlers.py' in files, plc_hold=True).model_dump()

    def create(self, name, title):
        target = self.target(name)
        if target.exists():
            raise HTTPException(409, 'Project already exists')
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            raise HTTPException(422, 'Provide a project title of 1–120 characters')
        try:
            ensure_available(target)
            with tempfile.TemporaryDirectory(dir=self.root) as directory:
                temporary = Path(directory) / 'project.sqlite3'
                initial = default_project()
                initial.title = title
                store = ProjectStore(temporary, initial_project=initial)
                try:
                    from .security import Security
                    Security(store)
                    with self.current.state.store._lock:
                        source = self.current.state.store._db
                        security = {table: source.execute(f'SELECT * FROM {table}').fetchall() for table in ('security_settings', 'security_group', 'security_user', 'security_windows', 'security_group_style')}
                    with store.transaction() as db:
                        for table, rows in security.items():
                            db.execute(f'DELETE FROM {table}')
                            if rows:
                                placeholders = ','.join('?' for _ in rows[0])
                                db.executemany(f'INSERT INTO {table} VALUES({placeholders})', rows)
                finally:
                    store.close()
                publish_project(temporary, target, {})
        except PublicationError as error:
            raise HTTPException(error.status, str(error)) from error
        except HTTPException:
            raise
        except Exception as error:
            logging.exception('Project creation could not finish')
            raise HTTPException(503, 'Project creation could not finish. Review the project library before retrying.') from error
        return CreatedProject(file=target.name).model_dump()

    async def open(self, filename):
        allowed = {item['file'] for item in self.listing()['projects']}
        if not isinstance(filename, str) or filename not in allowed:
            raise HTTPException(404, 'Project is not in the local library')
        target = self.root / filename
        if target.is_symlink() or target.resolve().parent != self.root:
            raise HTTPException(422, 'Invalid project location')
        if target == self.path:
            return
        try:
            candidate = self._app(target)  # custom Python is never automatically loaded on project open/import
            context = candidate.router.lifespan_context(candidate)
            await context.__aenter__()
        except Exception as error:
            logging.exception('Project candidate startup failed')
            raise HTTPException(503, 'The requested project could not start. The current project remains open; review server logs before trying again.') from error
        previous = self.context
        self.context, self.current, self.path, self.handlers = context, candidate, target, None
        if previous:
            try:
                await finish_cleanup(previous.__aexit__(None, None, None))
            except Exception as error:
                logging.exception('Previous project shutdown failed after switching')
                raise HTTPException(503, 'The requested project is now open, but the previous runtime shutdown failed. Reload and review server logs before further changes.') from error

    async def _shutdown(self):
        # Serialize with switching, then retire whichever runtime the workspace owns.
        async with self.lock:
            self.stopping = True
            context, self.context = self.context, None
            if context:
                await finish_cleanup(context.__aexit__(None, None, None))

    def require_management(self, request):
        security = self.current.state.security
        security.require(request, 'security.manage')
        if not security.configured() and self.current.state.recipe_auth.users:
            legacy_user = self.current.state.recipe_auth.user(request.cookies.get('openhmi_recipe_session'))
            if not legacy_user or not legacy_user.permits('administrator'):
                raise HTTPException(403, 'A legacy recipe administrator or HMI security administrator is required for project management')

    async def handle(self, request):
        self.require_management(request)
        path = request.url.path
        if request.method == 'GET' and path == '/api/workspace/artifacts':
            try:
                query = ArtifactQuery.model_validate(dict(request.query_params))
            except ValidationError as error:
                raise HTTPException(422, error.errors(include_url=False)) from error
            try:
                return JSONResponse(await finish_cleanup(asyncio.to_thread(inventory, self.root, query)))
            except InventoryUnavailable as error:
                logging.exception('Project file inventory failed')
                raise HTTPException(503, str(error)) from error
        if request.method == 'GET' and path == '/api/workspace':
            return JSONResponse(self.listing())
        if request.method == 'GET' and path == '/api/workspace/backup':
            expected = request.headers.get('x-openhmi-project')
            if expected and expected != self.current.state.project_instance:
                raise HTTPException(409, 'A different project was opened. Reload before exporting a backup.')
            try:
                data = await finish_cleanup(asyncio.to_thread(self.export))
            except HTTPException:
                raise
            except Exception as error:
                logging.exception('Complete backup export failed')
                raise HTTPException(503, 'Complete backup could not be exported. Review server logs and retry explicitly.') from error
            return Response(data, media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="project.openhmi.zip"'})
        raise HTTPException(404, 'Workspace operation not found')

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            message = await receive()
            context = self.current.router.lifespan_context(self.current)
            await context.__aenter__()
            self.context = context
            self.stopping = False
            try:
                await send({'type': 'lifespan.startup.complete'})
                await receive()
            finally:
                await finish_cleanup(self._shutdown())
            await send({'type': 'lifespan.shutdown.complete'})
            return
        if scope['type'] != 'http':
            return await self.current(scope, receive, send)
        # The complete CSV works in short database batches and stages an
        # independent file. A project switch can cancel staging, while a slow
        # download of the finished file need not delay HMI requests.
        if scope['method'] == 'GET' and scope['path'] == '/api/history/full.csv':
            return await self.current(scope, receive, send)
        if scope['method'] == 'GET' and scope['path'] in ('/api/tags', '/api/project/active'):
            label = 'Tag snapshot' if scope['path'] == '/api/tags' else 'Applied project snapshot'
            async with self.lock:
                identifier = self.current.state.project_instance
                if self.stopping:
                    response = JSONResponse({'detail': f'{label} is unavailable while the workspace is stopping'}, status_code=503)
                else:
                    try:
                        response = await finish_cleanup(prepare_snapshot(self.current, scope, receive))
                    except Exception:
                        logging.exception('%s preparation failed', label)
                        response = JSONResponse({'detail': f'{label} is temporarily unavailable'}, status_code=503)
                response.headers['Cache-Control'] = 'no-store'
                response.headers['X-Content-Type-Options'] = 'nosniff'
                set_response_context(Request(scope, receive), response, identifier)
            return await response(scope, receive, send)
        if scope['method'] == 'POST' and scope['path'] == '/api/workspace/import':
            response = await import_response(self, Request(scope, receive), MAX_BACKUP)
            return await response(scope, receive, send)
        if scope['method'] == 'POST' and scope['path'] in ('/api/workspace/create', '/api/workspace/open'):
            response = await mutation_response(self, Request(scope, receive))
            return await response(scope, receive, send)
        detached_read = scope['method'] == 'GET' and scope['path'] in (
            '/api/workspace', '/api/workspace/artifacts', '/api/workspace/backup')
        # A project switch cannot close a database while an HTTP operation is using it.
        async with self.lock:
            if scope['path'].startswith('/api/workspace'):
                try:
                    request = Request(scope, receive)
                    identifier = self.current.state.project_instance
                    require_project_instance(request, identifier)
                    response = await self.handle(request)
                except HTTPException as error:
                    response = JSONResponse({'detail': error.detail}, status_code=error.status_code)
                if detached_read or scope['path'] == '/api/workspace/backup':
                    response.headers['Cache-Control'] = 'no-store'
                    response.headers['X-Content-Type-Options'] = 'nosniff'
                set_response_context(request, response, identifier)
                if not detached_read:
                    return await response(scope, receive, send)
            else:
                return await self.current(scope, receive, send)
        # Snapshot preparation (including cancellation cleanup) stays serialized.
        # Finished JSON/ZIP responses own their bytes and source identity; sending
        # them no longer needs the runtime or delays reads/switch/shutdown.
        await response(scope, receive, send)
