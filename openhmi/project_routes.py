"""Protected history, draft staging and reviewed merge endpoints; no equipment writes."""

from fastapi import HTTPException, Path, Query, Request
from .projects import Project, StageRequest, RecoveryRequest, MergePreview, MergeRequest, RevisionConflict
from .project_diff import differences, merge_project, SCREEN_FIELDS


def add_project_routes(app, store, security, validate):
    def identity(request):
        principal = security.require(request, 'project.edit')
        return (principal.name, principal.provider) if principal else ('unsecured-simulation', 'simulation')

    def invoke(callback):
        try:
            return callback()
        except RevisionConflict as error:
            raise HTTPException(409, str(error)) from error
        except KeyError as error:
            raise HTTPException(404, str(error).strip("'")) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get('/api/project/revisions')
    def revisions(request: Request, limit: int = Query(default=50, ge=1, le=100),
                  before_revision: int | None = Query(default=None, ge=1, le=9223372036854775807)):
        identity(request)
        return invoke(lambda: store.revisions(limit, before_revision))

    @app.get('/api/project/revisions/{revision}')
    def revision_detail(request: Request, revision: int = Path(ge=1, le=9223372036854775807)):
        identity(request)
        return invoke(lambda: store.revision(revision))

    @app.get('/api/project/revisions/{revision}/compare')
    def compare(request: Request, revision: int = Path(ge=1, le=9223372036854775807), scope: str = Query(default='screens', pattern='^(screens|project)$')):
        identity(request)
        def inspect():
            historical = store.revision(revision)
            current = store.snapshot()
            draft = Project.model_validate(current['draft']).model_dump()
            candidate = {**draft, **{field: historical['project'][field] for field in SCREEN_FIELDS}} if scope == 'screens' else historical['project']
            return {'revision': historical, 'draft_revision': current['draft_revision'], 'scope': scope,
                    'changes': differences(draft, candidate), 'active_changes': differences(Project.model_validate(current['active']).model_dump(), candidate)}
        return invoke(inspect)

    @app.post('/api/project/revisions/{revision}/stage')
    def stage(body: StageRequest, request: Request, revision: int = Path(ge=1, le=9223372036854775807)):
        actor = identity(request)
        return invoke(lambda: store.stage(revision, body, validate, actor))

    @app.get('/api/project/recoveries')
    def recoveries(request: Request, limit: int = Query(default=50, ge=1, le=100), before_id: str | None = Query(default=None, pattern=r'^[a-f0-9]{32}$')):
        identity(request)
        return invoke(lambda: store.recoveries(limit, before_id))

    @app.get('/api/project/recoveries/{identifier}')
    def recovery(request: Request, identifier: str = Path(pattern=r'^[a-f0-9]{32}$')):
        identity(request)
        return invoke(lambda: store.recovery(identifier))

    @app.post('/api/project/recoveries')
    def retain(body: RecoveryRequest, request: Request):
        actor = identity(request)
        return invoke(lambda: store.recover(body, actor))

    @app.post('/api/project/merge-preview')
    def preview(body: MergePreview, request: Request):
        identity(request)
        def inspect():
            state = store.snapshot()
            return {**merge_project(body.base.model_dump(), body.local.model_dump(), Project.model_validate(state['draft']).model_dump(), body.choices),
                    'draft_revision': state['draft_revision']}
        return invoke(inspect)

    @app.post('/api/project/merge')
    def merge(body: MergeRequest, request: Request):
        actor = identity(request)
        return invoke(lambda: store.merge(body, validate, actor))
