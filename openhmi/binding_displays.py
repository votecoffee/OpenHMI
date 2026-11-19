"""Display, machine-state and browser binding rules."""

from fastapi import HTTPException


def validate_display_control(control, kinds, sources, routes):
    if control['kind'] == 'connection_status':
        if control['connection'] and control['connection'] not in routes:
            raise HTTPException(422, 'PLC connection status requires an existing connection')
        return True
    if control['kind'] == 'setpoint_comparison':
        tags = [control['tag'], control['setpoint_tag'], control['tolerance_tag']]
        if any(tag and kinds.get(tag) not in ('number', 'integer') for tag in tags):
            raise HTTPException(422, 'Setpoint comparisons require numeric tags')
        return True
    if control['kind'] == 'tag_quality':
        if control['tag'] not in kinds:
            raise HTTPException(422, 'Tag quality requires an existing tag')
        return True
    if control['kind'] == 'bitfield':
        if kinds.get(control['tag']) != 'integer':
            raise HTTPException(422, 'Bitfield display requires an unscaled integer tag')
        return True
    if control['kind'] == 'date_time_display':
        if kinds.get(control['tag']) != 'integer':
            raise HTTPException(422, 'Date/time display requires an unscaled integer tag')
        return True
    if control['kind'] in ('multi_state', 'multi_state_image', 'mode_selector'):
        if kinds.get(control['tag']) != 'integer':
            raise HTTPException(422, 'Machine states require an unscaled integer tag')
        if control['kind'] == 'mode_selector':
            request_tag, request_member = sources.get(control['tag'], (None, ''))
            confirmed, confirmed_member = sources.get(control['confirmed_tag'], (None, ''))
            if not request_tag or not request_tag.writable:
                raise HTTPException(422, 'Mode selector requires a configured writable integer request tag')
            if kinds.get(control['confirmed_tag']) != 'integer':
                raise HTTPException(422, 'Mode confirmation requires an unscaled integer tag')
            same_address = (request_tag.connection and confirmed and confirmed.connection
                            and routes[request_tag.connection] == routes[confirmed.connection]
                            and (request_tag.address + request_member).casefold()
                            == (confirmed.address + confirmed_member).casefold())
            if control['tag'] == control['confirmed_tag'] or same_address:
                raise HTTPException(422, 'Mode request and confirmation must use separate tags')
        return True
    if control['kind'] == 'stack_light':
        if any(kinds.get(lamp['tag']) != 'boolean' for lamp in control['lamps']):
            raise HTTPException(422, 'Stack lights require Boolean tags')
        return True
    if control['kind'] == 'permissives':
        if any(kinds.get(check['tag']) != 'boolean' for check in control['checks']):
            raise HTTPException(422, 'Permissive checks require Boolean tags')
        return True
    if control['kind'] == 'web_browser':
        if control['address_tag'] and kinds.get(control['address_tag']) != 'string':
            raise HTTPException(422, 'Web Browser address requires a STRING tag')
        if control['refresh_tag'] and kinds.get(control['refresh_tag']) not in ('boolean', 'integer'):
            raise HTTPException(422, 'Web Browser refresh requires a BOOL or integer tag')
        return True
    return False
