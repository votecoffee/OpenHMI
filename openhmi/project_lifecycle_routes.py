"""Project snapshots, draft saves and guarded live apply for one runtime."""

from fastapi import APIRouter, HTTPException, Request
from .projects import Project, ApplyRequest, SaveRequest, RevisionConflict


def add_project_lifecycle_routes(app, store, application, security, commands, monitor, trends,
                                 historian, publisher, validate_bindings, sample_alarms, instance):
    router = APIRouter()

    @router.get("/api/project")
    def project() -> dict:
        return {**store.snapshot(), 'project_instance': instance}

    @router.get("/api/project/active")
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

    @router.put("/api/project/draft")
    def save(request: SaveRequest, http: Request) -> dict:
        security.require(http, 'project.edit')
        if request.project.identity_publication.model_dump() != Project.model_validate(store.snapshot()['draft']).identity_publication.model_dump():
            security.require(http, 'security.manage')
        validate_bindings(request.project)
        return transact(store.save, request)

    @router.post("/api/project/apply")
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

    app.include_router(router)
