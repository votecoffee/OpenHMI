"""Read-only tag snapshots, viewer scan leases and protected PLC metadata."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from .tag_values import MAX_SAFE_INTEGER


class SubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    client: str
    screens: list[str]
    preview_root: str = ''
    sequence: int | None = Field(default=None, ge=1, le=MAX_SAFE_INTEGER)


def add_acquisition_routes(app, application, security):
    router = APIRouter()

    @router.get("/api/tags")
    def tags(status_only: bool = False) -> dict:
        with application.lock:
            driver = application.driver
            payload = {}
            if not status_only:
                samples = driver.sample_snapshot()
                values = {name: sample['value'] for name, sample in samples.items() if sample['quality'] == 'good'}
                payload.update(values=values, samples=samples)
            return {**payload, 'driver': 'logix' if driver.connections else 'simulator',
                    'connections': driver.status(include_groups=not status_only), 'plc_hold': driver.plc_hold}

    @router.post('/api/subscriptions')
    def subscriptions(body: SubscriptionRequest, request: Request):
        security.origin(request)
        if len(body.client) > 100 or not body.client or len(body.screens) > 20:
            raise HTTPException(422, 'Subscription limits exceeded')
        try:
            if body.preview_root:
                security.require(request, 'project.edit')
            application.driver.lease(body.client, body.screens, preview_root=body.preview_root,
                                     sequence=body.sequence)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {'expires_in_seconds': 15}

    @router.get('/api/connections')
    def connections(request: Request):
        security.require(request, 'project.edit')
        return {'connections': application.driver.status()}

    @router.get('/api/connections/{identifier}/browse')
    def browse(identifier: str, request: Request):
        security.require(request, 'project.edit')
        connection = application.driver.connections.get(identifier)
        if not connection:
            raise HTTPException(404, 'Apply and enable the connection first')
        return {'tags': list(connection.metadata.values()), 'error': connection.error}

    app.include_router(router)
