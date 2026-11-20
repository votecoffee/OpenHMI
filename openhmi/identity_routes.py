"""HTTP registration for identity publication station ownership."""

from fastapi import Request
from .identity_contracts import StationClaim


def add_identity_routes(app, publisher):
    @app.get('/api/security/publication')
    def status():
        return publisher.snapshot()

    @app.post('/api/security/publication/claim')
    def claim(body: StationClaim, request: Request, renew: bool = False):
        return publisher.claim(request, body.client, renew=renew)

    @app.post('/api/security/publication/release')
    def release(body: StationClaim, request: Request):
        return publisher.release(request, body.client)
