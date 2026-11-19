"""Alarm snapshots and attributed acknowledgement without PLC writes."""

from fastapi import APIRouter, HTTPException, Request
from .alarm_contracts import AcknowledgeRequest, SelectedAcknowledgement


def add_alarm_ack_routes(app, monitor, security, activity, store):
    router = APIRouter()

    @router.get("/api/alarms")
    def alarms() -> dict:
        return monitor.snapshot()

    @router.post("/api/alarms/acknowledge-all")
    def acknowledge_all(request: AcknowledgeRequest, http: Request) -> dict:
        return acknowledge_runtime(None, http, request.comment)

    @router.post('/api/alarms/acknowledge-selected')
    def acknowledge_selected(request: SelectedAcknowledgement, http: Request):
        return acknowledge_runtime(None, http, request.comment, request.occurrence_ids)

    @router.post("/api/alarms/{occurrence_id}/acknowledge")
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

    app.include_router(router)
