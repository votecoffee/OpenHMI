"""Project-level tag, protocol, identity, asset and expansion rules."""

from fastapi import HTTPException
from .drivers import SimulatorDriver
from .commands import validate_commands
from .recipe_transfers import validate_transfers
from .screens import expanded_controls, screen_map


def validate_protocols(project, security):
    try:
        validate_commands(project.model_dump(), {group['name'] for group in security.snapshot()['groups']})
        validate_transfers(project.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


def build_tag_index(project):
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
    return kinds, sources, routes


def validate_identity(project, security):
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


def validate_resources(project, kinds, web):
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


def validate_faceplates_and_history(project, project_data, kinds):
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


def expand_checked_controls(project_data):
    try:
        controls = expanded_controls(project_data)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if len({control['id'] for control in controls}) != len(controls):
        raise HTTPException(422, 'Expanded control IDs collide; rename the screen, control or faceplate member control')
    return controls
