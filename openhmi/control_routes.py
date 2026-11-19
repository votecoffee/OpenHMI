"""Audited operator actions and value writes, with the live-apply lock preserved."""

import logging
from fastapi import APIRouter, HTTPException, Request

from .control_contracts import (ActionRequest, ButtonRequest, ValueRequest, CHOICE_INPUTS,
                                BOOLEAN_INPUTS, PALETTE_INPUTS, EDIT_INPUTS)
from .edit_limits import edit_limits, validate_entry
from .screens import expanded_controls, enabled


def add_control_routes(app, store, application, security, activity, commands, sample_alarms):
    router = APIRouter()

    @router.post("/api/actions/{name}")
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

    @router.put('/api/controls/{control_id}/value')
    def write_value(control_id: str, body: ValueRequest, http: Request):
        # Live apply uses the same lock through driver configuration.
        with commands.lock:
            state = store.snapshot()
            stale = body.expected_revision is not None and body.expected_revision != state['active_revision']
            control = None if stale else next((item for item in expanded_controls(state['active'])
                                               if item['id'] == control_id and item['kind'] in EDIT_INPUTS), None)
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
            values = application.driver.snapshot()
            if not enabled(control, values):
                raise HTTPException(423, 'Control is disabled by its tag bindings')
            if control['tag'] not in values:
                raise HTTPException(409, 'Input tag has no good-quality value')
            kind = control['kind']
            if kind in (*PALETTE_INPUTS, 'mode_selector') and body.expected_revision is None:
                raise HTTPException(422, 'This input requires the applied project revision')
            if kind == 'mode_selector':
                if control['confirmed_tag'] not in values:
                    raise HTTPException(409, 'Mode confirmation tag has no good-quality value')
                if type(body.value) is not int or body.value not in {state['value'] for state in control['states']}:
                    raise HTTPException(422, 'Unknown machine mode')
            elif kind in CHOICE_INPUTS:
                if not any(type(body.value) is type(option['value']) and body.value == option['value']
                           for option in control['options']):
                    raise HTTPException(422, 'Value is outside the configured choices')
            elif kind in BOOLEAN_INPUTS:
                if type(body.value) is not bool:
                    raise HTTPException(422, 'Boolean input requires true or false')
            else:
                try:
                    limits = edit_limits(control, values)
                except ValueError as error:
                    raise HTTPException(409, str(error)) from error
                try:
                    validate_entry(control, body.value, limits)
                except ValueError as error:
                    raise HTTPException(422, str(error)) from error
            value = application.driver.coerce_number(control['tag'], body.value) if kind in ('input', 'slider', 'stepper') else body.value
            ticket.dispatch(tag=control['tag'], screen=control['_screen'], before=application.driver.sample_snapshot().get(control['tag']), requested_value=value)
            try:
                application.driver.write(control['tag'], [value])
            except (ValueError, ConnectionError, KeyError) as error:
                raise HTTPException(409, str(error)) from error
            ticket.confirm(verification=write_verification(control['tag']), requested_value=value)
            return {'ok': True, 'value': value}

    @router.post('/api/controls/{control_id}/activate')
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

    app.include_router(router)
