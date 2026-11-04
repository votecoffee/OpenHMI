"""Loopback-only simulation server. No controller or browser write endpoint."""

from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .drivers import SimulatorDriver


def create_app() -> FastAPI:
    app = FastAPI(title="OpenHMI simulation prototype")
    driver = SimulatorDriver()
    app.state.driver = driver
    web = Path(__file__).parent / "web"

    @app.get("/api/tags")
    def tags() -> dict:
        return {"driver": "simulator", "values": driver.snapshot()}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web / "index.html")

    app.mount("/static", StaticFiles(directory=web), name="static")
    return app


def main() -> None:
    import uvicorn

    assets = Path(__file__).parent / "web" / "vendor" / "grapes.min.js"
    if not assets.exists():
        raise SystemExit("Missing designer assets. Run npm ci and npm run build first.")
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
