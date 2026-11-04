"""Local live HMI builder with simulation and startup-loaded Python actions."""

from pathlib import Path
import argparse
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from .drivers import SimulatorDriver
from .application import Application
from .projects import Project, ProjectStore, RevisionConflict, RevisionRequest, SaveRequest


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def create_app(project_path: Path | None = None, handlers: Path | None = None) -> FastAPI:
    store = ProjectStore(project_path)
    application = Application(SimulatorDriver())
    if handlers:
        try:
            application.load_handlers(handlers)
        except Exception:
            store.close()
            raise

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            store.close()

    app = FastAPI(title="OpenHMI live builder prototype", lifespan=lifespan)
    app.state.driver = application.driver
    app.state.application = application
    app.state.store = store
    web = Path(__file__).parent / "web"

    def validate_bindings(project: Project):
        tags = application.driver.snapshot()
        actions = {action["name"] for action in application.actions()}
        for control in project.controls:
            if control.kind == "button":
                if control.action not in actions:
                    raise HTTPException(422, f"Unknown action: {control.action}")
            else:
                expected = (float, int) if control.kind == "numeric" else (bool,)
                if type(tags.get(control.tag)) not in expected:
                    raise HTTPException(422, f"Unknown or incompatible tag: {control.tag}")

    @app.get("/api/tags")
    def tags() -> dict:
        with application.lock:
            return {"driver": "simulator", "values": application.driver.snapshot()}

    @app.get("/api/catalog")
    def catalog() -> dict:
        return {
            "tags": [{"name": name, "type": "boolean" if type(value) is bool else "number"}
                     for name, value in application.driver.snapshot().items()],
            "actions": application.actions(),
        }

    @app.get("/api/project")
    def project() -> dict:
        return store.snapshot()

    @app.get("/api/project/active")
    def active() -> dict:
        state = store.snapshot()
        return {"revision": state["active_revision"], "project": state["active"]}

    def transact(operation, request):
        try:
            return operation(request)
        except RevisionConflict as error:
            raise HTTPException(409, str(error)) from error

    @app.put("/api/project/draft")
    def save(request: SaveRequest) -> dict:
        validate_bindings(request.project)
        return transact(store.save, request)

    @app.post("/api/project/apply")
    def apply(request: RevisionRequest) -> dict:
        return transact(lambda value: store.apply(value, validate_bindings), request)

    @app.post("/api/actions/{name}")
    def action(name: str, request: ActionRequest) -> dict:
        active_controls = store.snapshot()["active"]["controls"]
        if not any(control.get("action") == name for control in active_controls):
            raise HTTPException(404, "Action is not bound to an active control")
        if name not in {item["name"] for item in application.actions()}:
            raise HTTPException(404, "Action is unavailable; check startup handler configuration")
        try:
            application.invoke(name)
        except Exception as error:
            logging.exception("Application action %s failed", name)
            raise HTTPException(500, "Python action failed; see server log") from error
        return {"ok": True}

    @app.get("/", include_in_schema=False)
    @app.get("/runtime", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web / "index.html")

    app.mount("/static", StaticFiles(directory=web), name="static")
    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="OpenHMI local live builder (simulation)")
    parser.add_argument("--project", type=Path, default=Path(".local/project.sqlite3"), help="Project database path")
    parser.add_argument("--handlers", type=Path, help="Trusted local Python action module loaded at startup")
    args = parser.parse_args()
    assets = Path(__file__).parent / "web" / "vendor" / "app.js"
    if not assets.exists():
        raise SystemExit("Missing designer assets. Run npm ci and npm run build first.")
    uvicorn.run(create_app(args.project, args.handlers), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
