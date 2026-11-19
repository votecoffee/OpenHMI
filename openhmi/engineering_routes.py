"""Engineering catalog for the current draft; no controller I/O."""

from fastapi import APIRouter
from .drivers import SimulatorDriver
from .projects import Project


def add_engineering_routes(app, store, application, security, web):
    router = APIRouter()

    @router.get("/api/catalog")
    def catalog() -> dict:
        project = Project.model_validate(store.snapshot()['draft'])
        builtins = SimulatorDriver().snapshot()
        tag_types = {name: 'boolean' if type(value) is bool else 'string' if type(value) is str else 'number' for name, value in builtins.items()}
        for tag in project.tags:
            tag_types[tag.name] = 'number' if tag.type == 'integer' else tag.type
            tag_types.update({tag.name + '.' + member: 'number' if kind == 'integer' else kind for member, kind in tag.members.items()})
        return {
            'tags': [{'name': name, 'type': kind, 'integer': type(builtins.get(name)) is int} for name, kind in tag_types.items()],
            "actions": application.actions(),
            "flags": sorted(path.stem for path in (web / "assets" / "flags").glob("*.svg")),
            "security_permissions": security.snapshot()["permissions"],
            "security_groups": [group['name'] for group in security.snapshot()['groups']],
        }

    app.include_router(router)
