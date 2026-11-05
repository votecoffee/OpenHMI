"""Local live HMI builder with simulation and startup-loaded Python actions."""

from pathlib import Path
from contextlib import asynccontextmanager
import logging
import asyncio
import uuid
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import Response, JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .drivers import SimulatorDriver
from .application import Application
from .activity import ActivityJournal
from .commands import CommandService, add_command_routes, validate_commands
from .recipe_transfers import validate_transfers
from .operations_routes import add_operations_routes
from .logix import RuntimeDriver
from .historian import Historian
from .screens import expanded_controls, screen_map, enabled
from .alarms import AlarmMonitor
from .alarm_routes import add_alarm_routes
from .recipe_routes import add_recipe_routes
from .security import Security
from .security_routes import add_security_routes
from .projects import Project, ProjectStore, RevisionConflict, ApplyRequest, SaveRequest
from .project_routes import add_project_routes


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control_id: str | None = None


class SubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    client: str
    screens: list[str]
    preview_root: str = ''


class ValueRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    value: float


class AcknowledgeRequest(ActionRequest):
    model_config = ConfigDict(extra='forbid', strict=True)
    comment: str = Field(default='', max_length=1000)


class SelectedAcknowledgement(AcknowledgeRequest):
    occurrence_ids: list[int] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def valid_ids(self):
        if len(set(self.occurrence_ids)) != len(self.occurrence_ids) or any(not 1 <= identifier <= 9223372036854775807 for identifier in self.occurrence_ids):
            raise ValueError('Select 1–200 unique valid occurrence IDs')
        return self


def create_app(project_path: Path | None = None, handlers: Path | None = None, recipe_users=None, hold_connections=False) -> FastAPI:
    store = ProjectStore(project_path)
    application = Application(RuntimeDriver())
    application.driver.plc_hold = hold_connections
    application.driver.configure(Project.model_validate(store.snapshot()['active']).model_dump())
    historian = Historian(store, application.driver)
    historian.configure(Project.model_validate(store.snapshot()['active']).historian.model_dump())
    if handlers:
        try:
            application.load_handlers(handlers)
        except Exception:
            store.close()
            raise

    def sample_values():
        with application.lock:
            return application.driver.snapshot()

    monitor = AlarmMonitor(store, sample_values)

    def sample_alarms():
        try:
            monitor.sample()
        except Exception:
            logging.exception("Alarm monitor sampling failed")
            monitor.error = "Alarm sampling unavailable"

    async def alarm_loop():
        while True:
            await asyncio.sleep(0.25)
            sample_alarms()

    async def driver_loop():
        while not stopping.is_set():
            try:
                await asyncio.to_thread(application.driver.poll)
                await asyncio.to_thread(commands.poll)
                await asyncio.to_thread(historian.sample)
                await asyncio.to_thread(activity.maintenance)
            except Exception:
                logging.exception('Driver/history cycle failed')
            await asyncio.sleep(0.05)

    stopping = asyncio.Event()

    @asynccontextmanager
    async def lifespan(app):
        stopping.clear()
        sample_alarms()
        task = asyncio.create_task(alarm_loop())
        polling = asyncio.create_task(driver_loop())
        try:
            yield
        finally:
            task.cancel()
            stopping.set()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await polling
            await asyncio.to_thread(application.driver.close)
            store.close()

    app = FastAPI(title="OpenHMI live builder prototype", lifespan=lifespan)
    instance = app.state.project_instance = uuid.uuid4().hex

    @app.middleware('http')
    async def project_identity(request, call_next):
        expected = request.headers.get('x-openhmi-project')
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and expected and expected != instance:
            return JSONResponse({'detail': 'A different project was opened. Reload before making changes.'}, status_code=409)
        response = await call_next(request)
        response.headers['X-OpenHMI-Project'] = instance
        if hasattr(request.state, 'activity_operation'):
            response.headers['X-OpenHMI-Operation-ID'] = request.state.activity_operation
            response.headers['X-OpenHMI-Audit-Status'] = getattr(request.state, 'activity_status', 'pending')
        return response
    app.state.driver = application.driver
    app.state.application = application
    app.state.store = store
    app.state.alarms = monitor
    app.state.historian = historian
    security = app.state.security = Security(store)
    activity = app.state.activity = ActivityJournal(store, security)
    commands = app.state.commands = CommandService(store, application.driver)
    add_command_routes(app, commands, security)
    add_operations_routes(app, activity, security, application.driver)
    add_security_routes(app, security)
    add_recipe_routes(app, store, application, recipe_users, security, commands, activity)
    web = Path(__file__).parent / "web"

    def validate_bindings(project: Project):
        try:
            validate_commands(project.model_dump(), {group['name'] for group in security.snapshot()['groups']})
            validate_transfers(project.model_dump())
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        tags = SimulatorDriver().snapshot()
        kinds = {name: 'boolean' if type(value) is bool else 'string' if type(value) is str else 'number' for name, value in tags.items()}
        for tag in project.tags:
            if tag.name in kinds:
                raise HTTPException(422, 'Built-in simulation/recipe tags cannot be redefined')
            kinds[tag.name] = 'number' if tag.type == 'integer' and (tag.scale != 1 or tag.offset != 0) else tag.type
            for member, kind in tag.members.items():
                alias = tag.name + '.' + member
                if alias in kinds:
                    raise HTTPException(422, 'Tag aliases collide')
                kinds[alias] = kind
        actions = {action["name"] for action in application.actions()}
        for language in project.languages:
            if not (web / "assets" / "flags" / f"{language.flag}.svg").is_file():
                raise HTTPException(422, f"Unknown flag: {language.flag}")
        for alarm in project.alarms:
            if alarm.related_screen:
                target = screen_map(project.model_dump()).get(alarm.related_screen)
                if not target or target.get('popup'):
                    raise HTTPException(422, 'Alarm navigation requires an existing non-popup screen')
            if alarm.enabled:
                expected = ('boolean', 'integer', 'number') if alarm.trigger_type == 'value' else ('integer',)
                if kinds.get(alarm.tag) not in expected:
                    raise HTTPException(422, f"Unknown or incompatible alarm tag: {alarm.tag}")
        project_data = project.model_dump()
        templates = {template.id: template for template in project.faceplates}
        for screen in screen_map(project_data).values():
            for instance in screen['controls']:
                if instance['kind'] == 'faceplate':
                    definition = templates.get(instance['template'])
                    root = next((tag for tag in project.tags if tag.name == instance['root_tag'] and tag.type == 'struct'), None)
                    if not definition or not root or (definition.udt_type and definition.udt_type != root.udt_type):
                        raise HTTPException(422, 'Faceplate requires a compatible UDT tag and definition')
                    if any(root.members.get(member) != kind for member, kind in definition.members.items()):
                        raise HTTPException(422, 'UDT does not satisfy faceplate member types')
        for history in project.historian.tags:
            if kinds.get(history.tag) not in ('boolean', 'integer', 'number'):
                raise HTTPException(422, 'History requires an existing numeric or Boolean tag')
        try:
            controls = expanded_controls(project_data)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if len({control['id'] for control in controls}) != len(controls):
            raise HTTPException(422, 'Expanded control IDs collide; rename the screen, control or faceplate member control')
        known_groups = {group['name'] for group in security.snapshot()['groups']}
        for control in controls:
            for field in ('visible_tag', 'enabled_tag', 'color_tag', '_parent_visible', '_parent_enabled'):
                if control.get(field) and kinds.get(control[field]) != 'boolean':
                    raise HTTPException(422, 'Conditional bindings require a Boolean tag')
            required = control.get('security_groups', [])
            if not set(required) <= known_groups:
                raise HTTPException(422, 'Control references an unknown HMI security group')
            if control['kind'] == 'recipe':
                continue
            if control['kind'] == 'trend':
                if any(kinds.get(tag) not in ('number', 'integer', 'boolean') for tag in control['tags']):
                    raise HTTPException(422, 'Trend requires numeric or Boolean tags')
                continue
            if control['kind'] == "button":
                mode = control.get('mode', 'python')
                if mode == 'command' and control['command'] not in {item.id for item in project.commands}:
                    raise HTTPException(422, 'Button references an unknown command')
                if mode == 'command' and control['command'] in {item.command_id for item in project.recipe_transfers}:
                    raise HTTPException(422, 'Recipe commit channels must be dispatched from the recipe transfer workflow')
                if mode == 'python' and control['action'] not in actions:
                    raise HTTPException(422, f"Unknown action: {control['action']}")
                if mode in ('navigate', 'popup'):
                    target = screen_map(project_data).get(control['screen'])
                    if not target or bool(target.get('popup')) != (mode == 'popup'):
                        raise HTTPException(422, 'Navigation target screen type is incompatible')
                if mode in ('set', 'toggle'):
                    kind = kinds.get(control['target'])
                    if kind not in ('number', 'integer', 'boolean', 'string') or (mode == 'toggle' and kind != 'boolean'):
                        raise HTTPException(422, 'Action target type is incompatible')
            else:
                expected = ('number', 'integer') if control['kind'] in ('numeric', 'analog', 'input') else ('boolean',)
                if kinds.get(control['tag']) not in expected:
                    raise HTTPException(422, f"Unknown or incompatible tag: {control['tag']}")

    @app.get("/api/tags")
    def tags() -> dict:
        with application.lock:
            return {'driver': 'logix' if application.driver.connections else 'simulator', 'values': application.driver.snapshot(), 'samples': application.driver.sample_snapshot(), 'connections': application.driver.status(), 'plc_hold': application.driver.plc_hold}

    @app.get("/api/catalog")
    def catalog() -> dict:
        project = Project.model_validate(store.snapshot()['draft'])
        tag_types = {name: 'boolean' if type(value) is bool else 'string' if type(value) is str else 'number' for name, value in SimulatorDriver().snapshot().items()}
        for tag in project.tags:
            tag_types[tag.name] = 'number' if tag.type == 'integer' else tag.type
            tag_types.update({tag.name + '.' + member: 'number' if kind == 'integer' else kind for member, kind in tag.members.items()})
        return {
            'tags': [{'name': name, 'type': kind} for name, kind in tag_types.items()],
            "actions": application.actions(),
            "flags": sorted(path.stem for path in (web / "assets" / "flags").glob("*.svg")),
            "security_groups": [group['name'] for group in security.snapshot()['groups']],
        }

    @app.get("/api/project")
    def project() -> dict:
        return {**store.snapshot(), 'project_instance': instance}

    @app.get("/api/project/active")
    def active() -> dict:
        state = store.snapshot()
        return {'revision': state['active_revision'], 'project': state['active'], 'project_instance': instance}

    def transact(operation, request):
        try:
            return operation(request)
        except RevisionConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.put("/api/project/draft")
    def save(request: SaveRequest, http: Request) -> dict:
        security.require(http, 'project.edit')
        validate_bindings(request.project)
        return transact(store.save, request)

    @app.post("/api/project/apply")
    def apply(request: ApplyRequest, http: Request) -> dict:
        principal = security.require(http, 'project.edit')
        identity = (principal.name, principal.provider) if principal else ('unsecured-simulation', 'simulation')
        with commands.lock, monitor.lock:
            def validate_apply(project):
                validate_bindings(project)
                commands.validate_apply(project.model_dump())
            result = transact(lambda value: store.apply(value, validate_apply, identity), request)
            application.driver.plc_hold = False
            if hasattr(app.state, 'release_connections'):
                app.state.release_connections()
            application.driver.configure(Project.model_validate(result['active']).model_dump())
            historian.configure(Project.model_validate(result['active']).historian.model_dump())
            sample_alarms()
            return result

    add_project_routes(app, store, security, validate_bindings)

    @app.get("/api/alarms")
    def alarms() -> dict:
        return monitor.snapshot()

    @app.post("/api/alarms/acknowledge-all")
    def acknowledge_all(request: AcknowledgeRequest, http: Request) -> dict:
        return acknowledge_runtime(None, http, request.comment)

    @app.post('/api/alarms/acknowledge-selected')
    def acknowledge_selected(request: SelectedAcknowledgement, http: Request):
        return acknowledge_runtime(None, http, request.comment, request.occurrence_ids)

    @app.post("/api/alarms/{occurrence_id}/acknowledge")
    def acknowledge(occurrence_id: int, request: AcknowledgeRequest, http: Request) -> dict:
        if not 1 <= occurrence_id <= 9223372036854775807:
            raise HTTPException(422, 'Invalid occurrence ID')
        return acknowledge_runtime(occurrence_id, http, request.comment)

    def acknowledge_runtime(identifier, http, comment='', selected=None):
        def execute(ticket):
            principal = security.require(http, 'alarms.acknowledge')
            identity = (principal.name, principal.provider) if principal else ('unsecured-simulation', 'simulation')
            with monitor.lock:
                with store._lock:
                    identifiers = selected if selected is not None else [identifier] if identifier is not None else None
                    if identifiers is not None and store._db.execute('SELECT COUNT(*) FROM alarm_occurrence WHERE id IN (' + ','.join('?' for _ in identifiers) + ')', identifiers).fetchone()[0] != len(identifiers):
                        raise HTTPException(404, 'Alarm occurrence not found')
                ticket.dispatch()
                result = monitor.acknowledge(identifier, occurrence_ids=selected, identity=identity, operation_id=ticket.id, comment=comment)
                ticket.confirm(verification='alarm_acknowledged', occurrences=result['acknowledged'], count=len(result['acknowledged']))
                return result
        return activity.run(http, 'alarm_acknowledge', 'selected' if selected is not None else str(identifier) if identifier is not None else 'all',
                            {'occurrence_id': identifier, 'selected_ids': selected, 'comment': comment}, execute)

    add_alarm_routes(app, monitor, security, activity, application.driver, store)

    @app.post("/api/actions/{name}")
    def action(name: str, request: ActionRequest, http: Request) -> dict:
        active_controls = expanded_controls(store.snapshot()['active'])
        matches = [control for control in active_controls if control.get('action') == name and control.get('mode', 'python') == 'python' and (request.control_id is None or control['id'] == request.control_id)]
        def execute(ticket):
            if not matches:
                raise HTTPException(404, 'Action is not bound to this active control')
            # Old clients without a control ID must satisfy every Python-action binding.
            for control in matches:
                security.require(http, 'runtime.operate', control.get('security_groups', []))
                if not enabled(control, application.driver.snapshot()):
                    raise HTTPException(423, 'Control is disabled by its tag bindings')
            if name not in {item['name'] for item in application.actions()}:
                raise HTTPException(404, 'Action is unavailable; check startup handler configuration')
            ticket.dispatch()
            try:
                application.invoke(name)
            except Exception as error:
                logging.exception('Application action %s failed', name)
                raise HTTPException(500, 'Python action failed; see server log') from error
            ticket.confirm(verification='callback_returned')
            sample_alarms()
            return {'ok': True}
        return activity.run(http, 'python_action', request.control_id or name, {'action': name, 'control_ids': [control['id'] for control in matches], 'binding_count': len(matches)}, execute)

    @app.put('/api/controls/{control_id}/value')
    def write_value(control_id: str, body: ValueRequest, http: Request):
        control = next((item for item in expanded_controls(store.snapshot()['active']) if item['id'] == control_id and item['kind'] == 'input'), {})
        context = {'requested_value': body.value, 'control_id': control_id, 'tag': control.get('tag'), 'screen': control.get('_screen')}
        if control.get('tag'):
            context['before'] = application.driver.sample_snapshot().get(control['tag'])
        return activity.run(http, 'value_write', control_id, context, lambda ticket: write_runtime(control_id, body, http, ticket))

    def write_runtime(control_id, body, http, ticket):
        with application.lock:
            control = next((control for control in expanded_controls(store.snapshot()['active']) if control['id'] == control_id and control['kind'] == 'input'), None)
            if not control:
                raise HTTPException(404, 'Active numeric input not found')
            security.require(http, 'runtime.write', control.get('security_groups', []))
            if not enabled(control, application.driver.snapshot()):
                raise HTTPException(423, 'Control is disabled by its tag bindings')
            if control['tag'] not in application.driver.snapshot():
                raise HTTPException(409, 'Input tag has no good-quality value')
            import math
            if not math.isfinite(body.value) or not control['minimum'] <= body.value <= control['maximum']:
                raise HTTPException(422, 'Value is outside the configured input limits')
            value = application.driver.coerce_number(control['tag'], body.value)
            ticket.dispatch(tag=control['tag'], screen=control['_screen'], before=application.driver.sample_snapshot().get(control['tag']), requested_value=value)
            try:
                application.driver.write(control['tag'], [value])
            except (ValueError, ConnectionError, KeyError) as error:
                raise HTTPException(409, str(error)) from error
            ticket.confirm(verification=write_verification(control['tag']), requested_value=value)
            return {'ok': True, 'value': value}

    @app.post('/api/controls/{control_id}/activate')
    def activate(control_id: str, request: ActionRequest, http: Request):
        # Hold the active contract stable through authorization, reservation and dispatch.
        with commands.lock:
            return activate_locked(control_id, request, http)

    def activate_locked(control_id, request, http):
        control = next((item for item in expanded_controls(store.snapshot()['active']) if item['id'] == control_id and item['kind'] == 'button'), None)
        if control and control.get('mode', 'python') == 'python':
            return action(control['action'], ActionRequest(control_id=control_id), http)
        context = {field: control.get(field) for field in ('mode', 'command', 'target', 'value', 'screen', '_screen')} if control else {}
        if control and control.get('target'):
            context['before'] = application.driver.sample_snapshot().get(control['target'])
        return activity.run(http, 'button_action', control_id, context, lambda ticket: activate_runtime(control, http, ticket))

    def write_verification(tag):
        root, _ = application.driver.sources.get(tag, (None, ''))
        definition = application.driver.definitions.get(root)
        return 'tag_readback' if definition and definition['connection'] else 'local_write'

    def activate_runtime(control, http, ticket):
        if not control:
            raise HTTPException(404, 'Active button not found')
        security.require(http, 'runtime.operate', control.get('security_groups', []))
        values = application.driver.snapshot()
        if not enabled(control, values):
            raise HTTPException(423, 'Control is disabled by its tag bindings')
        mode = control.get('mode', 'python')
        if mode == 'command':
            definition = next((item for item in application.driver.project.get('commands', []) if item['id'] == control['command']), None)
            if not definition:
                raise HTTPException(409, 'Active command definition is unavailable')
            security.require(http, 'runtime.operate', definition['security_groups'])
            return commands.submit(definition, ticket)
        if mode in ('navigate', 'popup', 'close_popup'):
            ticket.dispatch()
            ticket.confirm(verification='navigation_response')
            return {'ok': True, 'mode': mode, 'screen': control.get('screen')}
        try:
            if control['target'] not in values:
                raise ValueError('Target has no good-quality value')
            value = not values[control['target']] if mode == 'toggle' else control['value']
            value = application.driver.coerce_number(control['target'], value)
            ticket.dispatch(tag=control['target'], before=application.driver.sample_snapshot().get(control['target']), requested_value=value)
            application.driver.write(control['target'], [value])
        except (ValueError, ConnectionError, KeyError) as error:
            raise HTTPException(409, str(error)) from error
        ticket.confirm(verification=write_verification(control['target']), requested_value=value)
        return {'ok': True}

    @app.post('/api/subscriptions')
    def subscriptions(body: SubscriptionRequest, request: Request):
        security.origin(request)
        if len(body.client) > 100 or not body.client or len(body.screens) > 20:
            raise HTTPException(422, 'Subscription limits exceeded')
        try:
            if body.preview_root:
                security.require(request, 'project.edit')
            application.driver.lease(body.client, body.screens, preview_root=body.preview_root)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {'expires_in_seconds': 15}

    @app.get('/api/connections')
    def connections(request: Request):
        security.require(request, 'project.edit')
        return {'connections': application.driver.status()}

    @app.get('/api/connections/{identifier}/browse')
    def browse(identifier: str, request: Request):
        security.require(request, 'project.edit')
        connection = application.driver.connections.get(identifier)
        if not connection:
            raise HTTPException(404, 'Apply and enable the connection first')
        return {'tags': list(connection.metadata.values()), 'error': connection.error}

    @app.get('/api/history')
    def history(tags: str, seconds: int = Query(default=300, ge=1, le=31536000), limit: int = Query(default=2000, ge=1, le=20000), end: float | None = None):
        import time
        import math
        names = list(dict.fromkeys(tags.split(',')))
        if len(names) > 12 or any(len(name) > 200 for name in names):
            raise HTTPException(422, 'History tag limits exceeded')
        finish = end if end is not None else time.time()
        if not math.isfinite(finish) or not 0 <= finish <= 32503680000:
            raise HTTPException(422, 'Invalid history end timestamp')
        return historian.query(names, finish - seconds, finish, limit)

    @app.get('/api/history.csv')
    def history_csv(tags: str, seconds: int = Query(default=3600, ge=1, le=31536000), end: float | None = None):
        import csv
        from io import StringIO
        data = history(tags, seconds, 20000, end)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['tag', 'timestamp', 'value', 'quality', 'source_timestamp'])
        for row in data['samples']:
            writer.writerow([row['tag'], row['timestamp'], row['value'], row['quality'], row['source_timestamp']])
        return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="tag-history.csv"', 'X-OpenHMI-Truncated': str(data['truncated']).lower()})

    @app.get("/", include_in_schema=False)
    @app.get("/runtime", include_in_schema=False)
    @app.get("/alarms", include_in_schema=False)
    @app.get("/recipes", include_in_schema=False)
    @app.get("/recipe-editor", include_in_schema=False)
    @app.get('/security', include_in_schema=False)
    @app.get('/projects', include_in_schema=False)
    @app.get('/activity', include_in_schema=False)
    @app.get('/diagnostics', include_in_schema=False)
    @app.get('/commands', include_in_schema=False)
    @app.get('/revisions', include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web / "index.html")

    app.mount("/static", StaticFiles(directory=web), name="static")
    return app


def main() -> None:
    from .launcher import main as launch
    launch()


if __name__ == "__main__":
    main()
