"""Build a self-contained OpenHMI demo and a complete project backup."""

import argparse
from io import BytesIO
from pathlib import Path
import time

from PIL import Image, ImageDraw

from openhmi.projects import Project, ProjectStore
from openhmi.recipe_auth import RecipeUser
from openhmi.recipe_models import RecipeCreate, RecipeSelect, RecipeTransition
from openhmi.workspace import ProjectWorkspace


def control(kind, identifier, label, **settings):
    return {'kind': kind, 'id': identifier, 'label': label, **settings}


def button(identifier, label, **settings):
    return control('button', identifier, label, **settings)


def local_tag(name, kind, value, **settings):
    return {'name': name, 'type': kind, 'initial': value, 'writable': True, **settings}


def simulation():
    return {
        'title': 'Process demonstration', 'columns': 3, 'update_ms': 250,
        'tags': [
            local_tag('DemoLevel', 'number', 62.0),
            local_tag('DemoFlow', 'number', 35.0),
            local_tag('DemoTemperature', 'number', 68.0),
            local_tag('DemoRunning', 'boolean', True),
            local_tag('DemoFault', 'boolean', False),
            local_tag('DemoNote', 'string', 'Simulation ready'),
            local_tag('DemoUnit', 'struct', {'Speed': 54.0, 'Running': True},
                      udt_type='DemoEquipment', members={'Speed': 'number', 'Running': 'boolean'}),
        ],
        'languages': [
            {'code': 'en', 'name': 'English', 'flag': 'us'},
            {'code': 'es', 'name': 'Español', 'flag': 'es', 'translations': {
                'screen.title': 'Demostración de proceso',
                'control.tank.label': 'Nivel del tanque',
                'control.flow.label': 'Caudal',
                'control.running.label': 'Bomba',
                'control.running.on_text': 'EN MARCHA',
                'control.running.off_text': 'PARADA',
                'alarm.demo_fault.message': 'Fallo simulado de la bomba',
                'alarm.demo_fault.cause': 'Se activó el fallo de demostración.',
                'alarm.demo_fault.response': '1. Abra Simulador.\n2. Borre el fallo simulado.',
            }},
        ],
        'alarms': [{
            'id': 'demo_fault', 'tag': 'DemoFault', 'message': 'Simulated pump fault', 'priority': 2,
            'cause': 'The simulator fault toggle is on.',
            'response': '1. Open Simulator.\n2. Clear the simulated fault.\n3. Verify the alarm returns to normal.',
            'related_screen': 'simulator',
        }],
        'historian': {
            'tags': [{'tag': tag, 'sample_ms': 250, 'deadband': 0} for tag in ('DemoLevel', 'DemoFlow', 'DemoRunning', 'DemoFault')],
            'retention_days': 7, 'max_rows': 100000,
        },
        'faceplates': [{
            'id': 'equipment', 'name': 'Pump module', 'udt_type': 'DemoEquipment',
            'members': {'Speed': 'number', 'Running': 'boolean'},
            'controls': [
                control('analog', 'speed', 'Speed', tag='$.Speed', unit='%', decimals=1),
                control('indicator', 'running', 'Motor status', tag='$.Running', on_text='RUNNING', off_text='STOPPED'),
            ],
        }],
        'controls': [
            control('tank', 'tank', 'Tank level', tag='DemoLevel', unit='%', decimals=1, normal_low=35, normal_high=78),
            control('analog', 'flow', 'Flow', tag='DemoFlow', unit='L/min', decimals=1),
            control('indicator', 'running', 'Pump', tag='DemoRunning', on_text='RUNNING', off_text='STOPPED'),
            control('faceplate', 'pump', 'Pump module', template='equipment', root_tag='DemoUnit'),
            control('recipe', 'recipe', 'Loaded recipe'),
            control('text', 'note', 'Operator note', tag='DemoNote'),
            control('alarm', 'fault', 'Pump fault', tag='DemoFault', priority=2),
            button('simulator', 'Open simulator', mode='navigate', screen='simulator'),
            button('trends', 'Open trends', mode='navigate', screen='trends'),
        ],
        'screens': [
            {'id': 'simulator', 'title': 'Simulator', 'columns': 3, 'update_ms': 250, 'controls': [
                control('input', 'level', 'Tank level', tag='DemoLevel', unit='%', decimals=1, minimum=0, maximum=100),
                control('input', 'flow', 'Flow', tag='DemoFlow', unit='L/min', decimals=1, minimum=0, maximum=100),
                control('input', 'temperature', 'Temperature', tag='DemoTemperature', unit='°C', decimals=1, minimum=0, maximum=100),
                control('text_input', 'note', 'Operator note', tag='DemoNote', max_length=40),
                button('running', 'Toggle pump', mode='toggle', target='DemoRunning'),
                button('fault', 'Toggle simulated fault', mode='toggle', target='DemoFault'),
                control('current_user', 'user', 'Current user'),
                control('bar', 'compare', 'Level and speed', unit='%', series=[
                    {'tag': 'DemoLevel', 'label': 'Tank level'}, {'tag': 'DemoUnit.Speed', 'label': 'Pump speed'},
                ]),
                control('radar', 'profile', 'Process profile', series=[
                    {'tag': 'DemoLevel', 'label': 'Level', 'unit': '%'},
                    {'tag': 'DemoFlow', 'label': 'Flow', 'unit': 'L/min', 'maximum': 80},
                    {'tag': 'DemoTemperature', 'label': 'Temperature', 'unit': '°C', 'maximum': 120},
                ]),
            ]},
            {'id': 'trends', 'title': 'Trends', 'columns': 1, 'update_ms': 250, 'controls': [
                control('trend', 'profile', 'Process trends', tags=['DemoLevel', 'DemoFlow', 'DemoRunning', 'DemoFault'], seconds=60,
                        series={'DemoLevel': {'minimum': 0, 'maximum': 100, 'decimals': 1}, 'DemoFlow': {'decimals': 2}},
                        recording={'sample_ms': 250, 'max_samples': 4000}),
            ]},
        ],
    }


def add_plc_preview(project, route, udt_type, bits):
    project['connections'] = [{'id': 'read_only_demo', 'name': 'Read-only PLC demo',
                               'path': route, 'enabled': True, 'program_tags': False}]
    scalar = {'DINT': 'integer', 'REAL': 'number', 'STRING': 'string', 'BOOL': 'boolean'}
    project['tags'].extend({'name': 'PLCDemo' + suffix, 'type': kind, 'connection': 'read_only_demo',
                            'address': '_Demo_' + suffix, 'writable': False} for suffix, kind in scalar.items())
    project['tags'].append({'name': 'PLCDemoUDT', 'type': 'struct', 'connection': 'read_only_demo',
                            'address': '_Demo_UDT', 'writable': False, 'udt_type': udt_type,
                            'members': dict.fromkeys(bits, 'boolean')})
    project['faceplates'].append({
        'id': 'plcflags', 'name': 'Demo UDT flags', 'udt_type': udt_type,
        'members': dict.fromkeys(bits, 'boolean'),
        'controls': [control('indicator', f'flag{index}', bit, tag='$.' + bit) for index, bit in enumerate(bits)],
    })
    project['screens'].append({
        'id': 'plcpreview', 'title': 'PLC preview (read-only)', 'columns': 2, 'update_ms': 2000, 'controls': [
            control('numeric', 'dint', 'Demo integer', tag='PLCDemoDINT'),
            control('numeric', 'real', 'Demo real', tag='PLCDemoREAL', decimals=2),
            control('text', 'string', 'Demo string', tag='PLCDemoSTRING'),
            control('indicator', 'bool', 'Demo Boolean', tag='PLCDemoBOOL'),
            control('faceplate', 'udt', 'Demo UDT flags', template='plcflags', root_tag='PLCDemoUDT'),
        ],
    })


def seed_recipes(app):
    service = app.state.recipes
    actor = RecipeUser('demo-seed', frozenset({'engineer', 'approver', 'operator'}))
    for code, title, setpoint, approved in [('DEMO-STANDARD', 'Standard profile', 62, True),
                                            ('DEMO-TRIAL', 'Trial profile', 48, False)]:
        image = Image.new('RGB', (360, 160), '#dddddd')
        draw = ImageDraw.Draw(image)
        draw.rectangle((18, 20, 142, 140), fill='#f1f1f1', outline='#555555', width=3)
        draw.rectangle((21, 138 - setpoint, 139, 137), fill='#46618c')
        draw.text((160, 67), title, fill='#333333')
        png = BytesIO()
        image.save(png, format='PNG')
        image_id = service.add_image(png.getvalue(), 'Generated demo profile graphic', actor)['image_id']
        recipe = service.create(RecipeCreate(code=code, reason='Seed demo recipe', content={
            'title': title, 'image_id': image_id, 'description': 'Simulation example',
            'parameters': [{'name': 'targetLevel', 'label': 'Target level', 'type': 'number',
                            'value': setpoint, 'unit': '%', 'minimum': 0, 'maximum': 100}],
        }), actor)
        if approved:
            for action in ('submit', 'approve'):
                recipe = service.transition(recipe['id'], RecipeTransition(action=action, expected_version=recipe['version'],
                                            reason='Demonstration of recipe review'), actor)
            service.select(RecipeSelect(revision_id=recipe['id'], expected_selection_version=service.selected()['version'],
                                       expected_revision_version=recipe['version'], reason='Load the demo profile'), actor)


def seed_history(app, recording):
    driver = app.state.driver
    historian = app.state.historian
    trends = app.state.trends
    if recording:
        with trends.lock:
            capture = trends._start('trends__profile', time.time() - 60)
    wall = time.time() - 60
    for index in range(121):
        level = 40.0 + (index % 48 if index % 96 < 48 else 48 - index % 48) * 0.8
        driver.write('DemoLevel', [level])
        driver.write('DemoFlow', [20.0 + (index % 25) * 1.1])
        driver.write('DemoRunning', [index % 32 < 24])
        driver.write('DemoFault', [55 <= index < 62])
        historian.sample(1000 + index / 2, wall + index / 2)
        if recording:
            trends.sample(1000 + index / 2, wall + index / 2)
    if recording:
        trends.stop('trends__profile', capture)
    for tag, value in [('DemoLevel', 62.0), ('DemoFlow', 35.0), ('DemoRunning', True), ('DemoFault', False)]:
        driver.write(tag, [value])
    app.state.alarms.sample()


def build(output, route=None, udt_type=None, bits=()):
    project = simulation()
    if route:
        add_plc_preview(project, route, udt_type, bits)
    model = Project.model_validate(project)
    output.mkdir(parents=True, exist_ok=False)
    database = output / 'OpenHMI-Demo.openhmi.sqlite3'
    if route:
        database.with_suffix('.hold').write_text('Review the read-only PLC preview before Apply live.\n', encoding='utf-8')
    ProjectStore(database, initial_project=model).close()
    workspace = ProjectWorkspace(database)
    try:
        seed_recipes(workspace.current)
        seed_history(workspace.current, recording=not route)
        (output / 'OpenHMI-Demo-backup.zip').write_bytes(workspace.export())
    finally:
        workspace.current.state.store.close()
    return database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='A new output directory')
    parser.add_argument('--read-only-route', help='Optional verified controller route for the private PLC preview')
    parser.add_argument('--udt-type', help='Type name of _Demo_UDT')
    parser.add_argument('--udt-bit', action='append', default=[], help='Visible Boolean _Demo_UDT member, repeat for each flag')
    args = parser.parse_args()
    if args.read_only_route and (not args.udt_type or not args.udt_bit):
        parser.error('A PLC preview requires --udt-type and at least one --udt-bit')
    if not args.read_only_route and (args.udt_type or args.udt_bit):
        parser.error('UDT options require --read-only-route')
    if len(args.udt_bit) > 12 or len(set(args.udt_bit)) != len(args.udt_bit) or any(not bit.isidentifier() for bit in args.udt_bit):
        parser.error('Provide up to twelve unique scalar Boolean member names')
    print(build(args.output, args.read_only_route, args.udt_type, args.udt_bit))


if __name__ == '__main__':
    main()
