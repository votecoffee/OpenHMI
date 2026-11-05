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
from .runtime_workers import RuntimeWorkers
from .historian import Historian
from .history_export import CSV_COLUMNS, complete_history_csv, csv_row
from .trend_recording import TrendRecorder, add_trend_routes
from .screens import expanded_controls, screen_map, enabled
from .alarms import AlarmMonitor
from .alarm_routes import add_alarm_routes
from .edit_limits import LIMIT_TAGS, edit_limits, validate_entry
from .identity_publish import IdentityPublisher, add_identity_routes
from .recipe_routes import add_recipe_routes
from .security import Security
from .security_routes import add_security_routes
from .projects import Project, ProjectStore, RevisionConflict, ApplyRequest, SaveRequest
from .project_routes import add_project_routes
from .canvas import CanvasImages, add_canvas_routes


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control_id: str | None = None


class ButtonRequest(ActionRequest):
    expected_revision: int | None = Field(default=None, strict=True, ge=1, le=9223372036854775807)


class SubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    client: str
    screens: list[str]
    preview_root: str = ''


class ValueRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    value: float | int | str
    expected_revision: int | None = Field(default=None, ge=1, le=9223372036854775807)


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
    historian.configure(application.driver.project['historian'])
    trends = TrendRecorder(store, application.driver)
    trends.configure(application.driver.project)
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

    def sample_alarms(*, propagate=False):
        with monitor.lock:
            try:
                monitor.sample()
            except Exception:
                monitor.error = "Alarm sampling unavailable"
                if propagate:
                    raise
                logging.exception("Alarm monitor sampling failed")

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(sample_alarms)
        try:
            async with workers.running():
                yield
        finally:
            for name, cleanup in (
                ('trends', trends.shutdown), ('identity', publisher.shutdown),
                ('acquisition', application.driver.close), ('project store', store.close),
            ):
                try:
                    await asyncio.to_thread(cleanup)
                except Exception:
                    logging.exception('Runtime cleanup failed for %s', name)

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
    app.state.trends = trends
    security = app.state.security = Security(store)
    publisher = app.state.identity_publisher = IdentityPublisher(application.driver, security)
    add_identity_routes(app, publisher)
    activity = app.state.activity = ActivityJournal(store, security)
    commands = app.state.commands = CommandService(store, application.driver)
    add_command_routes(app, commands, security)
    workers = RuntimeWorkers({
        'acquisition': (0.05, lambda: application.driver.poll(wait=False)),
        'commands': (0.05, lambda: commands.poll()),
        'alarms': (0.25, lambda: sample_alarms(propagate=True)),
        'trends': (0.05, lambda: trends.sample()),
        'historian': (0.05, lambda: historian.sample()),
        'activity': (60, lambda: activity.maintenance(force=True)),
        'identity': (0.05, lambda: publisher.poll()),
    })
    app.state.runtime_workers = workers
    add_operations_routes(app, activity, security, application.driver, workers)
    add_security_routes(app, security)
    canvas_images = CanvasImages(store)
    add_canvas_routes(app, canvas_images, security)
    add_trend_routes(app, trends, security)
    add_recipe_routes(app, store, application, recipe_users, security, commands, activity)
    web = Path(__file__).parent / "web"

    def validate_bindings(project: Project):
        canvas_images.validate(project)
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
        publication = project.identity_publication
        if publication.enabled:
            from .security import PERMISSIONS
            definitions = {tag.name: tag for tag in project.tags}
            physical_targets = set()
            for name, kind in ((publication.username_tag, 'string'), (publication.privileges_tag, 'integer'), *([(publication.heartbeat_tag, 'integer')] if publication.heartbeat_tag else [])):
                definition = definitions.get(name)
                if not definition or definition.type != kind or not definition.writable or definition.scale != 1 or definition.offset != 0:
                    raise HTTPException(422, 'Identity publication requires writable, unscaled root STRING/integer logical tags')
                physical = (definition.connection, definition.address if definition.connection else definition.name)
                if physical in physical_targets:
                    raise HTTPException(422, 'Identity outputs must use separate physical PLC tags')
                physical_targets.add(physical)
            groups = {item['name'] for item in security.legend()}
            if any(bit.name not in (PERMISSIONS if bit.source == 'permission' else groups) for bit in publication.bits):
                raise HTTPException(422, 'Identity bit references an unknown permission or group')
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
            if publication.enabled and ((control['kind'] in ('input', 'text_input') and control.get('tag') in (publication.username_tag, publication.privileges_tag, publication.heartbeat_tag)) or (control['kind'] == 'button' and control.get('mode') in ('set', 'toggle') and control.get('target') in (publication.username_tag, publication.privileges_tag, publication.heartbeat_tag))):
                raise HTTPException(422, 'Identity publication tags cannot be edit or button write targets')
            for field in LIMIT_TAGS:
                if control.get(field) and kinds.get(control[field]) not in ('number', 'integer'):
                    raise HTTPException(422, 'Edit limits require an existing numeric tag')
            for field in ('visible_tag', 'enabled_tag', 'color_tag', '_parent_visible', '_parent_enabled'):
                if control.get(field) and kinds.get(control[field]) != 'boolean':
                    raise HTTPException(422, 'Conditional bindings require a Boolean tag')
            required = control.get('security_groups', [])
            if not set(required) <= known_groups:
                raise HTTPException(422, 'Control references an unknown HMI security group')
            if control['kind'] in ('recipe', 'current_user'):
                continue
            if control['kind'] == 'web_browser':
                if control['address_tag'] and kinds.get(control['address_tag']) != 'string':
                    raise HTTPException(422, 'Web Browser address requires a STRING tag')
                if control['refresh_tag'] and kinds.get(control['refresh_tag']) not in ('boolean', 'integer'):
                    raise HTTPException(422, 'Web Browser refresh requires a BOOL or integer tag')
                continue
            if control['kind'] in ('bar', 'radar'):
                if any(kinds.get(series['tag']) not in ('number', 'integer') for series in control['series']):
                    raise HTTPException(422, 'Bar and radar charts require numeric tags')
                continue
            if control['kind'] == 'trend':
                if any(kinds.get(tag) not in ('number', 'integer', 'boolean') for tag in control['tags']):
                    raise HTTPException(422, 'Trend requires numeric or Boolean tags')
                recording = control.get('recording')
                if recording and any(recording[field] and kinds.get(recording[field]) != 'boolean' for field in ('start_tag', 'stop_tag')):
                    raise HTTPException(422, 'Trend recording triggers require Boolean tags')
                if recording and recording['start_tag'] and recording['start_tag'] == recording['stop_tag']:
                    raise HTTPException(422, 'Trend recording triggers must resolve to different tags')
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
                expected = ('number', 'integer') if control['kind'] in ('numeric', 'analog', 'tank', 'input') else ('string',) if control['kind'] in ('text', 'text_input') else ('boolean',)
                if kinds.get(control['tag']) not in expected:
                    raise HTTPException(422, f"Unknown or incompatible tag: {control['tag']}")

    @app.get("/api/tags")
    def tags() -> dict:
        with application.lock:
            samples = application.driver.sample_snapshot()
            values = {name: sample['value'] for name, sample in samples.items() if sample['quality'] == 'good'}
            return {'driver': 'logix' if application.driver.connections else 'simulator', 'values': values, 'samples': samples, 'connections': application.driver.status(), 'plc_hold': application.driver.plc_hold}

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
            "security_permissions": security.snapshot()["permissions"],
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
        if request.project.identity_publication.model_dump() != Project.model_validate(store.snapshot()['draft']).identity_publication.model_dump():
            security.require(http, 'security.manage')
        validate_bindings(request.project)
        return transact(store.save, request)

    @app.post("/api/project/apply")
    def apply(request: ApplyRequest, http: Request) -> dict:
        principal = security.require(http, 'project.edit')
        identity = (principal.name, principal.provider) if principal else ('unsecured-simulation', 'simulation')
        with commands.lock, monitor.lock, trends.lock, historian.lock:
            def validate_apply(project):
                old_publication = (application.driver.project or {}).get('identity_publication', {})
                if old_publication.get('enabled') or publisher.last_config:
                    old_tags = {tag['name']: tag for tag in application.driver.project['tags']}
                    new_tags = {tag.name: tag.model_dump() for tag in project.tags}
                    protected = publisher.last_config or old_publication
                    if any(old_tags.get(protected[field]) != new_tags.get(protected[field]) for field in ('username_tag', 'privileges_tag', *(['heartbeat_tag'] if protected.get('heartbeat_tag') else []))) or (project.identity_publication.enabled and any(getattr(project.identity_publication, field) != protected[field] for field in ('username_tag', 'privileges_tag', *(['heartbeat_tag'] if protected.get('heartbeat_tag') else [])))):
                        raise HTTPException(409, 'Disable identity publication and wait for its cleared status before changing its target tags')
                if project.identity_publication.model_dump() != Project.model_validate(store.snapshot()['active']).identity_publication.model_dump():
                    security.require(http, 'security.manage')
                validate_bindings(project)
                commands.validate_apply(project.model_dump())
            result = transact(lambda value: store.apply(value, validate_apply, identity), request)
            application.driver.plc_hold = False
            if hasattr(app.state, 'release_connections'):
                app.state.release_connections()
            application.driver.configure(Project.model_validate(result['active']).model_dump())
            historian.configure(application.driver.project['historian'])
            trends.configure(application.driver.project)
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
        # Live apply uses the same lock through driver configuration.
        with commands.lock:
            state = store.snapshot()
            stale = body.expected_revision is not None and body.expected_revision != state['active_revision']
            control = None if stale else next((item for item in expanded_controls(state['active'])
                                               if item['id'] == control_id and item['kind'] in ('input', 'text_input')), None)
            context = {'requested_value': body.value, 'control_id': control_id,
                       'expected_revision': body.expected_revision, 'active_revision': state['active_revision'],
                       'tag': control.get('tag') if control else None, 'screen': control.get('_screen') if control else None}
            if control:
                context['before'] = application.driver.sample_snapshot().get(control['tag'])
            return activity.run(http, 'value_write', control_id, context, lambda ticket: write_runtime(control, body, http, ticket, stale))

    def write_runtime(control, body, http, ticket, stale):
        with application.lock:
            if stale:
                raise HTTPException(409, 'The applied project changed. Reopen the keypad or clear and re-enter the value.')
            if not control:
                raise HTTPException(404, 'Active edit control not found')
            security.require(http, 'runtime.write', control.get('security_groups', []))
            if not enabled(control, application.driver.snapshot()):
                raise HTTPException(423, 'Control is disabled by its tag bindings')
            if control['tag'] not in application.driver.snapshot():
                raise HTTPException(409, 'Input tag has no good-quality value')
            try:
                limits = edit_limits(control, application.driver.snapshot())
            except ValueError as error:
                raise HTTPException(409, str(error)) from error
            try:
                validate_entry(control, body.value, limits)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            value = application.driver.coerce_number(control['tag'], body.value) if control['kind'] == 'input' else body.value
            ticket.dispatch(tag=control['tag'], screen=control['_screen'], before=application.driver.sample_snapshot().get(control['tag']), requested_value=value)
            try:
                application.driver.write(control['tag'], [value])
            except (ValueError, ConnectionError, KeyError) as error:
                raise HTTPException(409, str(error)) from error
            ticket.confirm(verification=write_verification(control['tag']), requested_value=value)
            return {'ok': True, 'value': value}

    @app.post('/api/controls/{control_id}/activate')
    def activate(control_id: str, request: ButtonRequest, http: Request):
        # Hold the active contract stable through authorization, reservation and dispatch.
        with commands.lock:
            return activate_locked(control_id, request, http)

    def activate_locked(control_id, request, http):
        state = store.snapshot()
        stale = request.expected_revision is not None and request.expected_revision != state['active_revision']
        control = None if stale else next((item for item in expanded_controls(state['active'])
                                           if item['id'] == control_id and item['kind'] == 'button'), None)
        if control and control.get('mode', 'python') == 'python':
            return action(control['action'], ActionRequest(control_id=control_id), http)
        context = {field: control.get(field) for field in ('mode', 'command', 'target', 'value', 'screen', '_screen')} if control else {}
        if request.expected_revision is not None:
            context.update(expected_revision=request.expected_revision, active_revision=state['active_revision'])
        if control and control.get('target'):
            context['before'] = application.driver.sample_snapshot().get(control['target'])
        return activity.run(http, 'button_action', control_id, context, lambda ticket: activate_runtime(control, http, ticket, stale))

    def write_verification(tag):
        root, _ = application.driver.sources.get(tag, (None, ''))
        definition = application.driver.definitions.get(root)
        return 'tag_readback' if definition and definition['connection'] else 'local_write'

    def activate_runtime(control, http, ticket, stale):
        if stale:
            raise HTTPException(409, 'The applied project changed. Review the updated button before trying again.')
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

    def history_window(tags, seconds, end, start=None):
        import time
        import math
        names = list(dict.fromkeys(tags.split(',')))
        if len(names) > 12 or any(len(name) > 200 for name in names):
            raise HTTPException(422, 'History tag limits exceeded')
        finish = end if end is not None else time.time()
        if not math.isfinite(finish) or not 0 <= finish <= 32503680000:
            raise HTTPException(422, 'Invalid history end timestamp')
        if start is not None and (not math.isfinite(start) or not 0 <= start < finish or finish - start > 31536000):
            raise HTTPException(422, 'History start must be before the end and within 365 days')
        return names, finish - seconds if start is None else start, finish

    @app.get('/api/history')
    def history(tags: str, seconds: int = Query(default=300, ge=1, le=31536000), limit: int = Query(default=2000, ge=1, le=20000), end: float | None = None, trend_context: bool = False):
        return historian.query(*history_window(tags, seconds, end), limit, trend_context)

    def require_history_project(project_instance):
        if project_instance is not None and project_instance != instance:
            raise HTTPException(409, 'A different project was opened. Reload before exporting history.')

    @app.get('/api/history/tags')
    def history_tags(prefix: str = Query(default='', max_length=200), after: str | None = Query(default=None, max_length=200),
                     limit: int = Query(default=50, ge=1, le=100),
                     project_instance: str | None = Query(default=None, max_length=32)):
        require_history_project(project_instance)
        if after is not None and not after.startswith(prefix):
            raise HTTPException(422, 'History tag cursor must match the search prefix')
        return historian.recorded_tags(prefix, after, limit)

    @app.get('/api/history.csv')
    def history_csv(tags: str, seconds: int = Query(default=3600, ge=1, le=31536000),
                    end: float | None = None, start: float | None = None):
        import csv
        from io import StringIO
        data = historian.query(*history_window(tags, seconds, end, start), 20000)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(CSV_COLUMNS)
        for row in data['samples']:
            writer.writerow(csv_row(row['tag'], row['timestamp'], row['value'], row['quality'], row['source_timestamp']))
        return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="tag-history.csv"', 'X-OpenHMI-Truncated': str(data['truncated']).lower()})

    @app.get('/api/history/full.csv')
    def history_full_csv(tags: str, seconds: int = Query(default=3600, ge=1, le=31536000),
                         end: float | None = None, start: float | None = None,
                         project_instance: str | None = Query(default=None, max_length=32)):
        require_history_project(project_instance)
        return complete_history_csv(historian, *history_window(tags, seconds, end, start))

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
