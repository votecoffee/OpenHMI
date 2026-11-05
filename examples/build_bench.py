"""Build an offline, held read-only OpenHMI project from approved bench inputs."""

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from openhmi.projects import Project, ProjectStore
from openhmi.runtime_models import Model
from openhmi.workspace import ProjectWorkspace


PLC_COMPONENT = r'[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]+(?:,[0-9]+){0,2}\])?'
PLC_ADDRESS = rf'^(?:Program:[A-Za-z_][A-Za-z0-9_]*\.)?{PLC_COMPONENT}(?:\.{PLC_COMPONENT})*(?:\.[0-9]+)?$'


class BenchTag(Model):
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(max_length=200, pattern=PLC_ADDRESS)
    type: Literal['boolean', 'integer', 'number', 'string']
    label: str | None = Field(default=None, min_length=1, max_length=100)
    scale: float = 1.0
    offset: float = 0.0


class BenchSpec(Model):
    route: str = Field(min_length=1, max_length=200, pattern=r'^\S+$')
    overview_update_ms: int = Field(ge=100, le=60000)
    comparison_update_ms: int | None = Field(default=None, ge=100, le=60000)
    comparison_tags: list[str] = Field(default_factory=list, max_length=100)
    program_tags: bool = False
    tags: list[BenchTag] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def validate_comparison(self):
        if bool(self.comparison_tags) != (self.comparison_update_ms is not None):
            raise ValueError('Provide both comparison_update_ms and comparison_tags for a comparison screen')
        names = set(self.comparison_tags)
        if len(names) != len(self.comparison_tags) or not names.issubset({tag.name for tag in self.tags}):
            raise ValueError('Comparison tags must be unique approved logical names')
        if not self.program_tags and any(tag.address.startswith('Program:') for tag in self.tags):
            raise ValueError('Program-scoped addresses require program_tags to be true')
        return self


def project_from(spec):
    controls = {}
    tags = []
    for index, tag in enumerate(spec.tags):
        kind = {'boolean': 'indicator', 'string': 'text'}.get(tag.type, 'numeric')
        controls[tag.name] = {'id': f'read_{index + 1}', 'kind': kind, 'label': tag.label or tag.name, 'tag': tag.name}
        if tag.type == 'integer' and tag.scale == 1 and tag.offset == 0:
            controls[tag.name]['decimals'] = 0
        tags.append({**tag.model_dump(exclude={'label'}), 'connection': 'bench', 'writable': False})

    screens = []
    if spec.comparison_tags:
        screens.append({'id': 'comparison', 'title': 'Overlap comparison', 'update_ms': spec.comparison_update_ms,
                        'controls': [controls[name] for name in spec.comparison_tags]})
    return Project.model_validate({
        'title': 'Read-only ControlLogix bench',
        'update_ms': spec.overview_update_ms,
        'connections': [{'id': 'bench', 'name': 'ControlLogix bench', 'path': spec.route,
                         'enabled': True, 'program_tags': spec.program_tags}],
        'tags': tags,
        'controls': list(controls.values()),
        'screens': screens,
    })


def build(spec, output):
    project = project_from(spec)
    output.mkdir(parents=True, exist_ok=False)
    database = output / 'OpenHMI-Bench.openhmi.sqlite3'
    database.with_suffix('.hold').write_text('Review the approved bench configuration before Apply live.\n', encoding='utf-8')
    ProjectStore(database, initial_project=project).close()
    workspace = ProjectWorkspace(database)
    try:
        (output / 'OpenHMI-Bench-backup.zip').write_bytes(workspace.export())
    finally:
        workspace.current.state.store.close()
    return database


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate bench configuration field: {key}')
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path, help='Reviewed JSON route, screen rates and read-only tag list')
    parser.add_argument('output', type=Path, help='New directory for the held project and backup')
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding='utf-8-sig'), object_pairs_hook=unique_object)
        database = build(BenchSpec.model_validate(config), args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f'OpenHMI bench: {error}\n')
    print(database)


if __name__ == '__main__':
    main()
