"""Project binding checks shared by draft, merge, staging and guarded live apply."""

from fastapi import HTTPException
from .drivers import SimulatorDriver
from .projects import Project
from .commands import validate_commands
from .recipe_transfers import validate_transfers
from .screens import CHART_TAG_FIELDS, chart_tags, expanded_controls, screen_map
from .edit_limits import LIMIT_TAGS, TEXT_INPUTS
from .control_contracts import CHOICE_INPUTS, BOOLEAN_INPUTS, PALETTE_INPUTS, EDIT_INPUTS


def create_binding_validator(application, security, canvas_images, web):
    def validate_bindings(project: Project):
        canvas_images.validate(project)
        try:
            validate_commands(project.model_dump(), {group['name'] for group in security.snapshot()['groups']})
            validate_transfers(project.model_dump())
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        tags = SimulatorDriver().snapshot()
        kinds = {name: 'boolean' if type(value) is bool else 'string' if type(value) is str else 'integer' if type(value) is int else 'number' for name, value in tags.items()}
        sources = {}
        routes = {route.id: route.path.rstrip('/').casefold() for route in project.connections}
        for tag in project.tags:
            if tag.name in kinds:
                raise HTTPException(422, 'Built-in simulation/recipe tags cannot be redefined')
            kinds[tag.name] = 'number' if tag.type == 'integer' and (tag.scale != 1 or tag.offset != 0) else tag.type
            sources[tag.name] = (tag, '')
            for member, kind in tag.members.items():
                alias = tag.name + '.' + member
                if alias in kinds:
                    raise HTTPException(422, 'Tag aliases collide')
                kinds[alias] = kind
                sources[alias] = (tag, '.' + member)
        publication = project.identity_publication
        if publication.enabled:
            from .security import PERMISSIONS
            definitions = {tag.name: tag for tag in project.tags}
            physical_targets = set()
            for name, kind in ((publication.username_tag, 'string'), (publication.privileges_tag, 'integer'), *([(publication.heartbeat_tag, 'integer')] if publication.heartbeat_tag else [])):
                definition = definitions.get(name)
                if not definition or definition.type != kind or not definition.writable or definition.scale != 1 or definition.offset != 0:
                    raise HTTPException(422, 'Identity publication requires writable, unscaled root STRING/integer logical tags')
                physical = (definition.connection, definition.address if definition.connection else definition.name)
                if physical in physical_targets:
                    raise HTTPException(422, 'Identity outputs must use separate physical PLC tags')
                physical_targets.add(physical)
            groups = {item['name'] for item in security.legend()}
            if any(bit.name not in (PERMISSIONS if bit.source == 'permission' else groups) for bit in publication.bits):
                raise HTTPException(422, 'Identity bit references an unknown permission or group')
        actions = {action["name"] for action in application.actions()}
        for language in project.languages:
            if not (web / "assets" / "flags" / f"{language.flag}.svg").is_file():
                raise HTTPException(422, f"Unknown flag: {language.flag}")
        for alarm in project.alarms:
            if alarm.related_screen:
                target = screen_map(project.model_dump()).get(alarm.related_screen)
                if not target or target.get('popup'):
                    raise HTTPException(422, 'Alarm navigation requires an existing non-popup screen')
            if alarm.enabled:
                expected = ('boolean', 'integer', 'number') if alarm.trigger_type == 'value' else ('integer',)
                if kinds.get(alarm.tag) not in expected:
                    raise HTTPException(422, f"Unknown or incompatible alarm tag: {alarm.tag}")
        project_data = project.model_dump()
        templates = {template.id: template for template in project.faceplates}
        for screen in screen_map(project_data).values():
            for instance in screen['controls']:
                if instance['kind'] == 'faceplate':
                    definition = templates.get(instance['template'])
                    root = next((tag for tag in project.tags if tag.name == instance['root_tag'] and tag.type == 'struct'), None)
                    if not definition or not root or (definition.udt_type and definition.udt_type != root.udt_type):
                        raise HTTPException(422, 'Faceplate requires a compatible UDT tag and definition')
                    if any(root.members.get(member) != kind for member, kind in definition.members.items()):
                        raise HTTPException(422, 'UDT does not satisfy faceplate member types')
        for history in project.historian.tags:
            if kinds.get(history.tag) not in ('boolean', 'integer', 'number'):
                raise HTTPException(422, 'History requires an existing numeric or Boolean tag')
        try:
            controls = expanded_controls(project_data)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if len({control['id'] for control in controls}) != len(controls):
            raise HTTPException(422, 'Expanded control IDs collide; rename the screen, control or faceplate member control')
        known_groups = {group['name'] for group in security.snapshot()['groups']}
        for control in controls:
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
            if control['kind'] in ('recipe', 'current_user', 'label', 'symbol', 'image'):
                continue
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
                continue
            if control['kind'] == 'connection_status':
                if control['connection'] and control['connection'] not in routes:
                    raise HTTPException(422, 'PLC connection status requires an existing connection')
                continue
            if control['kind'] == 'setpoint_comparison':
                tags = [control['tag'], control['setpoint_tag'], control['tolerance_tag']]
                if any(tag and kinds.get(tag) not in ('number', 'integer') for tag in tags):
                    raise HTTPException(422, 'Setpoint comparisons require numeric tags')
                continue
            if control['kind'] == 'tag_quality':
                if control['tag'] not in kinds:
                    raise HTTPException(422, 'Tag quality requires an existing tag')
                continue
            if control['kind'] == 'bitfield':
                if kinds.get(control['tag']) != 'integer':
                    raise HTTPException(422, 'Bitfield display requires an unscaled integer tag')
                continue
            if control['kind'] == 'date_time_display':
                if kinds.get(control['tag']) != 'integer':
                    raise HTTPException(422, 'Date/time display requires an unscaled integer tag')
                continue
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
                continue
            if control['kind'] == 'stack_light':
                if any(kinds.get(lamp['tag']) != 'boolean' for lamp in control['lamps']):
                    raise HTTPException(422, 'Stack lights require Boolean tags')
                continue
            if control['kind'] == 'permissives':
                if any(kinds.get(check['tag']) != 'boolean' for check in control['checks']):
                    raise HTTPException(422, 'Permissive checks require Boolean tags')
                continue
            if control['kind'] == 'web_browser':
                if control['address_tag'] and kinds.get(control['address_tag']) != 'string':
                    raise HTTPException(422, 'Web Browser address requires a STRING tag')
                if control['refresh_tag'] and kinds.get(control['refresh_tag']) not in ('boolean', 'integer'):
                    raise HTTPException(422, 'Web Browser refresh requires a BOOL or integer tag')
                continue
            if control['kind'] in CHART_TAG_FIELDS:
                tags = chart_tags(control)
                if any(kinds.get(tag) not in ('number', 'integer') for tag in tags):
                    raise HTTPException(422, 'Live charts require numeric tags')
                if control['kind'] == 'pie' and len(set(tags)) != len(tags):
                    raise HTTPException(422, 'Pie slices require distinct tags')
                continue
            if control['kind'] == 'trend':
                if any(kinds.get(tag) not in ('number', 'integer', 'boolean') for tag in control['tags']):
                    raise HTTPException(422, 'Trend requires numeric or Boolean tags')
                recording = control.get('recording')
                if recording and any(recording[field] and kinds.get(recording[field]) != 'boolean' for field in ('start_tag', 'stop_tag')):
                    raise HTTPException(422, 'Trend recording triggers require Boolean tags')
                if recording and recording['start_tag'] and recording['start_tag'] == recording['stop_tag']:
                    raise HTTPException(422, 'Trend recording triggers must resolve to different tags')
                continue
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

    return validate_bindings
