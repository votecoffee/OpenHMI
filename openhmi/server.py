"""Local live HMI builder with simulation and startup-loaded Python actions."""

from pathlib import Path
from contextlib import asynccontextmanager
import logging
import asyncio
import uuid
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .http_context import add_project_context_middleware
from .application import Application
from .activity import ActivityJournal
from .commands import CommandService
from .command_routes import add_command_routes
from .operations_routes import add_operations_routes
from .logix import RuntimeDriver
from .runtime_workers import RuntimeWorkers
from .historian import Historian
from .history_routes import add_history_routes
from .trend_recording import TrendRecorder
from .trend_routes import add_trend_routes
from .alarms import AlarmMonitor
from .alarm_routes import add_alarm_routes
from .identity_publish import IdentityPublisher
from .identity_routes import add_identity_routes
from .recipe_routes import add_recipe_routes
from .security import Security
from .security_routes import add_security_routes
from .project_models import Project, ApplyRequest, SaveRequest
from .projects import ProjectStore, RevisionConflict
from .project_routes import add_project_routes
from .canvas import CanvasImages
from .canvas_routes import add_canvas_routes


# Compatibility imports for existing callers of the application entry point.
from .control_contracts import (ActionRequest, ButtonRequest, ValueRequest, CHOICE_INPUTS,
                                BOOLEAN_INPUTS, PALETTE_INPUTS, EDIT_INPUTS)
from .control_routes import add_control_routes
from .acquisition_routes import SubscriptionRequest, add_acquisition_routes
from .alarm_contracts import AcknowledgeRequest, SelectedAcknowledgement
from .alarm_ack_routes import add_alarm_ack_routes
from .project_lifecycle_routes import add_project_lifecycle_routes
from .project_validation import create_binding_validator
from .engineering_routes import add_engineering_routes


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

    add_project_context_middleware(app, instance)
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

    validate_bindings = create_binding_validator(application, security, canvas_images, web)

    add_engineering_routes(app, store, application, security, web)

    add_project_lifecycle_routes(app, store, application, security, commands, monitor, trends,
                                 historian, publisher, validate_bindings, sample_alarms, instance)

    add_project_routes(app, store, security, validate_bindings)

    add_alarm_ack_routes(app, monitor, security, activity, store)

    add_alarm_routes(app, monitor, security, activity, application.driver, store)

    add_control_routes(app, store, application, security, activity, commands, sample_alarms)

    add_acquisition_routes(app, application, security)

    add_history_routes(app, historian, instance)

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
