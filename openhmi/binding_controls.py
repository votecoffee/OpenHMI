"""Shared control guards, edit bindings and action/value fallbacks."""

from fastapi import HTTPException
from .edit_limits import LIMIT_TAGS, TEXT_INPUTS
from .control_contracts import CHOICE_INPUTS, PALETTE_INPUTS, EDIT_INPUTS
from .screens import screen_map


def validate_common_control(control, project, kinds, known_groups):
    publication = project.identity_publication
    if publication.enabled and ((control['kind'] in EDIT_INPUTS and control.get('tag') in (publication.username_tag, publication.privileges_tag, publication.heartbeat_tag)) or (control['kind'] == 'button' and control.get('mode') in ('set', 'toggle') and control.get('target') in (publication.username_tag, publication.privileges_tag, publication.heartbeat_tag))):
        raise HTTPException(422, 'Identity publication tags cannot be edit or button write targets')
    for field in LIMIT_TAGS:
        if control.get(field) and kinds.get(control[field]) not in ('number', 'integer'):
            raise HTTPException(422, 'Edit limits require an existing numeric tag')
    for field in ('visible_tag', 'enabled_tag', 'color_tag', '_parent_visible', '_parent_enabled'):
        if control.get(field) and kinds.get(control[field]) != 'boolean':
            raise HTTPException(422, 'Conditional bindings require a Boolean tag')
    required = control.get('security_groups', [])
    if not set(required) <= known_groups:
        raise HTTPException(422, 'Control references an unknown HMI security group')


def validate_edit_control(control, kinds, sources):
    if control['kind'] in PALETTE_INPUTS:
        target, _ = sources.get(control['tag'], (None, ''))
        expected = ('string',) if control['kind'] in TEXT_INPUTS else ('boolean',)
        if control['kind'] in CHOICE_INPUTS:
            expected = ('integer',) if type(control['options'][0]['value']) is int else ('string',)
        if control['kind'] == 'date_time':
            expected = ('integer',)
        if control['kind'] in ('slider', 'stepper'):
            expected = ('integer',) if target and target.type == 'integer' else ('integer', 'number')
        if control['kind'] == 'stepper' and target and target.type == 'integer' and not control['step'].is_integer():
            raise HTTPException(422, 'Integer stepper tags require a whole-number step')
        if not target or not target.writable or kinds.get(control['tag']) not in expected:
            raise HTTPException(422, f"Control requires a configured writable tag of type {' or '.join(expected)}: {control['tag']}")
        return True
    return False


def validate_action_or_value(control, project, kinds, actions, project_data):
    if control['kind'] == "button":
        mode = control.get('mode', 'python')
        if mode == 'command' and control['command'] not in {item.id for item in project.commands}:
            raise HTTPException(422, 'Button references an unknown command')
        if mode == 'command' and control['command'] in {item.command_id for item in project.recipe_transfers}:
            raise HTTPException(422, 'Recipe commit channels must be dispatched from the recipe transfer workflow')
        if mode == 'python' and control['action'] not in actions:
            raise HTTPException(422, f"Unknown action: {control['action']}")
        if mode in ('navigate', 'popup'):
            target = screen_map(project_data).get(control['screen'])
            if not target or bool(target.get('popup')) != (mode == 'popup'):
                raise HTTPException(422, 'Navigation target screen type is incompatible')
        if mode in ('set', 'toggle'):
            kind = kinds.get(control['target'])
            if kind not in ('number', 'integer', 'boolean', 'string') or (mode == 'toggle' and kind != 'boolean'):
                raise HTTPException(422, 'Action target type is incompatible')
    else:
        expected = ('number', 'integer') if control['kind'] in ('numeric', 'analog', 'tank', 'gauge', 'progress', 'position_image', 'rotation_image', 'sparkline', 'duration', 'led_display', 'input') else ('string',) if control['kind'] in ('text', 'text_input') else ('boolean',)
        if kinds.get(control['tag']) not in expected:
            raise HTTPException(422, f"Unknown or incompatible tag: {control['tag']}")
