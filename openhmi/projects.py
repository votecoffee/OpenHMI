"""Editor-independent screen schema and transactional draft/apply persistence."""

import json
import math
import re
from ipaddress import IPv4Address
import sqlite3
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .runtime_models import MAX_PLC_CONNECTIONS, Connection, TagDefinition, HistorianSettings
from .runtime_models import CommandDefinition, RecipeTransferDefinition
from .identity_publish import IdentityPublication
from .canvas import CanvasLayout
from .edit_limits import MAX_UTC_EPOCH
from .project_diff import encoded, digest, same, differences, merge_project, SCREEN_FIELDS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ControlBase(StrictModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=100)
    visible_tag: str = Field(default='', max_length=200)
    enabled_tag: str = Field(default='', max_length=200)
    color_tag: str = Field(default='', max_length=200)
    active_color: str = Field(default='#002878', pattern=r'^#[a-fA-F0-9]{6}$')


StateCode = Annotated[int, Field(ge=-(2**53 - 1), le=2**53 - 1)]


class MachineState(StrictModel):
    value: StateCode
    label: str = Field(min_length=1, max_length=100)
    symbol: Literal['circle', 'square', 'triangle', 'diamond'] = 'circle'
    color: str = Field(default='#333333', pattern=r'^#[a-fA-F0-9]{6}$')


class StateControl(ControlBase):
    tag: str = Field(min_length=1, max_length=200)
    states: list[MachineState] = Field(min_length=2, max_length=32)

    @model_validator(mode='after')
    def unique_states(self):
        if len({state.value for state in self.states}) != len(self.states):
            raise ValueError('Machine state codes must be unique')
        return self


class MultiStateControl(StateControl):
    kind: Literal['multi_state']


class ModeSelectorControl(StateControl):
    kind: Literal['mode_selector']
    confirmed_tag: str = Field(min_length=1, max_length=200)
    presentation: Literal['dropdown', 'segments'] = 'dropdown'
    security_groups: list[str] = Field(default_factory=list, max_length=100)


class PermissiveRow(StrictModel):
    tag: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=100)
    expected: bool = True


class PermissiveControl(ControlBase):
    kind: Literal['permissives']
    checks: list[PermissiveRow] = Field(min_length=1, max_length=32)


class NumericControl(ControlBase):
    kind: Literal["numeric"]
    tag: str = Field(min_length=1, max_length=200)
    unit: str = Field(default="", max_length=30)
    decimals: int = Field(default=1, ge=0, le=4)


class LabelControl(ControlBase):
    kind: Literal['label']
    font_size: int = Field(default=16, ge=8, le=72)
    alignment: Literal['start', 'center', 'end'] = 'start'
    weight: Literal['normal', 'bold'] = 'normal'


class SymbolControl(ControlBase):
    kind: Literal['symbol']
    symbol: Literal['arrow', 'info', 'warning', 'check', 'circle', 'diamond'] = 'arrow'
    size: int = Field(default=28, ge=12, le=96)
    rotation: Literal[0, 90, 180, 270] = 0


class SparklineControl(NumericControl):
    kind: Literal['sparkline']
    seconds: int = Field(default=60, ge=5, le=3600)


class DateTimeDisplayControl(ControlBase):
    kind: Literal['date_time_display']
    tag: str = Field(min_length=1, max_length=200)


class DurationDisplayControl(ControlBase):
    kind: Literal['duration']
    tag: str = Field(min_length=1, max_length=200)
    source_unit: Literal['seconds', 'milliseconds'] = 'milliseconds'
    decimals: int = Field(default=0, ge=0, le=3)


class TextDisplayControl(ControlBase):
    kind: Literal['text']
    tag: str = Field(min_length=1, max_length=200)


class IndicatorControl(ControlBase):
    kind: Literal["indicator"]
    tag: str = Field(min_length=1, max_length=200)
    on_text: str = Field(default="ON", min_length=1, max_length=30)
    off_text: str = Field(default="OFF", min_length=1, max_length=30)


class ProgressControl(NumericControl):
    kind: Literal['progress']
    minimum: float = Field(default=0.0, allow_inf_nan=False)
    maximum: float = Field(default=100.0, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered_scale(self):
        if not 0 < self.maximum - self.minimum < math.inf:
            raise ValueError('Progress scale must have a positive, finite span')
        return self


class AnalogControl(NumericControl):
    kind: Literal["analog"]
    minimum: float = Field(default=0.0, allow_inf_nan=False)
    maximum: float = Field(default=100.0, allow_inf_nan=False)
    normal_low: float = Field(default=20.0, allow_inf_nan=False)
    normal_high: float = Field(default=80.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_range(self):
        if not math.isfinite(self.maximum - self.minimum) or not self.minimum <= self.normal_low < self.normal_high <= self.maximum:
            raise ValueError("Range must satisfy minimum <= normal low < normal high <= maximum")
        return self


class TankControl(AnalogControl):
    kind: Literal['tank']


class GaugeControl(AnalogControl):
    kind: Literal['gauge']


class ChartSeries(StrictModel):
    tag: str = Field(min_length=1, max_length=200)
    label: str = Field(default='', max_length=100)
    decimals: int = Field(default=1, ge=0, le=4)


class RadarAxis(ChartSeries):
    unit: str = Field(default='', max_length=30)
    minimum: float = Field(default=0, allow_inf_nan=False)
    maximum: float = Field(default=100, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered_range(self):
        if not 0 < self.maximum - self.minimum < math.inf:
            raise ValueError('Radar axis minimum must be less than maximum with a finite span')
        return self


class RadarControl(ControlBase):
    kind: Literal['radar']
    series: list[RadarAxis] = Field(min_length=3, max_length=8)


class BarGraphControl(ControlBase):
    kind: Literal['bar']
    series: list[ChartSeries] = Field(min_length=1, max_length=12)
    unit: str = Field(default='', max_length=30)
    minimum: float = Field(default=0, allow_inf_nan=False)
    maximum: float = Field(default=100, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered_range(self):
        if not 0 < self.maximum - self.minimum < math.inf:
            raise ValueError('Bar graph minimum must be less than maximum with a finite span')
        return self


class PieControl(ControlBase):
    kind: Literal['pie']
    series: list[ChartSeries] = Field(min_length=2, max_length=8)
    unit: str = Field(default='', max_length=30)

    @model_validator(mode='after')
    def distinct_tags(self):
        if len({item.tag for item in self.series}) != len(self.series):
            raise ValueError('Pie slices require distinct tags')
        return self


class XYSeries(StrictModel):
    x_tag: str = Field(min_length=1, max_length=200)
    y_tag: str = Field(min_length=1, max_length=200)
    label: str = Field(default='', max_length=100)


class XYControl(ControlBase):
    kind: Literal['xy']
    series: list[XYSeries] = Field(min_length=1, max_length=8)
    x_minimum: float = Field(default=0.0, allow_inf_nan=False)
    x_maximum: float = Field(default=100.0, allow_inf_nan=False)
    y_minimum: float = Field(default=0.0, allow_inf_nan=False)
    y_maximum: float = Field(default=100.0, allow_inf_nan=False)
    x_unit: str = Field(default='', max_length=30)
    y_unit: str = Field(default='', max_length=30)
    decimals: int = Field(default=1, ge=0, le=4)

    @model_validator(mode='after')
    def ordered_axes(self):
        if not all(0 < span < math.inf for span in (
            self.x_maximum - self.x_minimum, self.y_maximum - self.y_minimum
        )):
            raise ValueError('XY scales require positive finite spans')
        return self


class AlarmControl(ControlBase):
    kind: Literal["alarm"]
    tag: str = Field(min_length=1, max_length=200)
    priority: Literal[1, 2, 3, 4] = 2


class ButtonControl(ControlBase):
    kind: Literal["button"]
    action: str = Field(default='', max_length=100)
    mode: Literal['python', 'set', 'toggle', 'navigate', 'popup', 'close_popup', 'command'] = 'python'
    command: str = Field(default='', max_length=60)
    target: str = Field(default='', max_length=200)
    value: float | int | bool | str = False
    screen: str = Field(default='overview', max_length=60)
    security_groups: list[str] = Field(default_factory=list, max_length=100)


class NumericInputControl(NumericControl):
    kind: Literal['input', 'slider']
    minimum: float = Field(default=0.0, allow_inf_nan=False)
    maximum: float = Field(default=100.0, allow_inf_nan=False)
    security_groups: list[str] = Field(default_factory=list, max_length=100)
    minimum_tag: str = Field(default='', max_length=200)
    maximum_tag: str = Field(default='', max_length=200)

    @model_validator(mode='after')
    def ordered_limits(self):
        if self.minimum >= self.maximum:
            raise ValueError('Input minimum must be less than maximum')
        if self.kind == 'slider' and not math.isfinite(self.maximum - self.minimum):
            raise ValueError('Slider range must have a finite span')
        return self


class DateTimeControl(ControlBase):
    kind: Literal['date_time']
    tag: str = Field(min_length=1, max_length=200)
    minimum: int = Field(default=0, ge=0, le=MAX_UTC_EPOCH)
    maximum: int = Field(default=MAX_UTC_EPOCH, ge=0, le=MAX_UTC_EPOCH)
    minimum_tag: str = Field(default='', max_length=200)
    maximum_tag: str = Field(default='', max_length=200)
    security_groups: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def ordered_limits(self):
        if self.minimum > self.maximum:
            raise ValueError('Earliest date/time must not exceed latest date/time')
        return self


class RecipeSelectionControl(ControlBase):
    kind: Literal['recipe']


class TextInputControl(ControlBase):
    kind: Literal['text_input', 'text_area', 'barcode_input']
    tag: str = Field(min_length=1, max_length=200)
    min_length: int = Field(default=0, ge=0, le=4096)
    max_length: int = Field(default=82, ge=0, le=4096)
    min_length_tag: str = Field(default='', max_length=200)
    max_length_tag: str = Field(default='', max_length=200)
    security_groups: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def ordered_lengths(self):
        if self.min_length > self.max_length:
            raise ValueError('Minimum text length must not exceed maximum text length')
        return self


class ChoiceOption(StrictModel):
    value: StateCode | Annotated[str, Field(max_length=4096, pattern=r'^[^\x00]*$')]
    label: str = Field(min_length=1, max_length=100)


class ChoiceInputControl(ControlBase):
    kind: Literal['dropdown', 'radio_group']
    tag: str = Field(min_length=1, max_length=200)
    options: list[ChoiceOption] = Field(min_length=2, max_length=32)
    security_groups: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def unique_options(self):
        values = {option.value for option in self.options}
        if len(values) != len(self.options) or len({type(value) for value in values}) != 1:
            raise ValueError('Choice values must be unique and all have the same type')
        return self


class BooleanInputControl(ControlBase):
    kind: Literal['checkbox', 'toggle_switch']
    tag: str = Field(min_length=1, max_length=200)
    security_groups: list[str] = Field(default_factory=list, max_length=100)


class CurrentUserControl(ControlBase):
    kind: Literal['current_user']


class FaceplateControl(ControlBase):
    kind: Literal['faceplate']
    template: str = Field(min_length=1, max_length=60)
    root_tag: str = Field(min_length=1, max_length=200)


class TrendSeries(StrictModel):
    decimals: int = Field(default=1, ge=0, le=8)
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered_scale(self):
        if self.minimum is None and self.maximum is None:
            return self
        if (self.minimum is None or self.maximum is None or self.minimum >= self.maximum
                or not math.isfinite(self.maximum - self.minimum)):
            raise ValueError('Fixed trend scale requires a finite minimum less than maximum')
        return self


class TrendRecording(StrictModel):
    sample_ms: int = Field(default=250, ge=100, le=60000)
    max_samples: int = Field(default=4000, ge=10, le=20000)
    start_tag: str = Field(default='', max_length=200)
    stop_tag: str = Field(default='', max_length=200)

    @model_validator(mode='after')
    def distinct_triggers(self):
        if self.start_tag and self.start_tag == self.stop_tag:
            raise ValueError('Trend start and stop must use different Boolean tags')
        return self


class TrendControl(ControlBase):
    kind: Literal['trend']
    tags: list[str] = Field(min_length=1, max_length=12)
    seconds: int = Field(default=300, ge=10, le=604800)
    series: dict[str, TrendSeries] = Field(default_factory=dict, max_length=12)
    recording: TrendRecording | None = None

    @model_validator(mode='after')
    def known_series(self):
        if self.series.keys() - set(self.tags):
            raise ValueError('Trend series settings require a selected tag')
        return self


class Language(StrictModel):
    code: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$", max_length=35)
    name: str = Field(min_length=1, max_length=60)
    flag: str = Field(pattern=r"^[a-z]{2}(?:-[a-z0-9]+)*$", max_length=20)
    direction: Literal["ltr", "rtl"] = "ltr"
    translations: dict[str, str] = Field(default_factory=dict, max_length=3000)

    @model_validator(mode="after")
    def bounded_translations(self):
        if any(not key or len(key) > 200 or len(value) > 2000 for key, value in self.translations.items()):
            raise ValueError("Translation keys/values exceed the allowed size")
        return self


class AlarmDefinition(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=100)
    tag: str = Field(min_length=1, max_length=200)
    trigger_type: Literal["value", "bit", "lsbit"] = "value"
    trigger_value: int = Field(default=1, ge=-2147483648, le=2147483647)
    message: str = Field(min_length=1, max_length=500)
    cause: str = Field(default='', max_length=2000)
    response: str = Field(default='', max_length=2000)
    related_screen: str = Field(default='', max_length=60)
    priority: Literal[1, 2, 3, 4] = 2
    ack_required: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def valid_trigger(self):
        if self.trigger_value == 0 or (self.trigger_type != "value" and not 1 <= self.trigger_value <= 32):
            raise ValueError("Value triggers must be nonzero; bit/lsbit positions are 1..32")
        return self


class WebBrowserControl(ControlBase):
    kind: Literal['web_browser']
    scheme: Literal['http', 'https'] = 'https'
    hosts: str = Field(default='', max_length=1024)
    port: int | None = Field(default=None, ge=1, le=65535)
    path: str = Field(default='/', max_length=512)
    address_tag: str = Field(default='', max_length=200)
    refresh_tag: str = Field(default='', max_length=200)

    @model_validator(mode='after')
    def valid_destination(self):
        if not re.fullmatch(r'/[A-Za-z0-9._~/-]*', self.path) or '//' in self.path or any(
            segment in ('.', '..') for segment in self.path.split('/')
        ):
            raise ValueError('Browser path must be an absolute plain path without traversal, query or fragment')
        hosts = [host.strip().lower() for host in self.hosts.split(',')] if self.hosts.strip() else []
        if len(hosts) > 16 or len(set(hosts)) != len(hosts):
            raise ValueError('Browser hosts must be unique and limited to 16')
        for host in hosts:
            try:
                IPv4Address(host)
            except ValueError:
                labels = host.split('.')
                if len(host) > 253 or not re.match(r'[a-z]', labels[-1]) or any(
                    not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels
                ):
                    raise ValueError('Browser hosts must be exact DNS names or IPv4 addresses') from None
        return self


Control = Annotated[NumericControl | NumericInputControl | DateTimeControl | DateTimeDisplayControl | DurationDisplayControl | LabelControl | SymbolControl | SparklineControl | TextDisplayControl | TextInputControl | ChoiceInputControl | BooleanInputControl | CurrentUserControl | IndicatorControl | AnalogControl | ProgressControl | TankControl | GaugeControl | BarGraphControl | PieControl | RadarControl | XYControl | AlarmControl | ButtonControl | RecipeSelectionControl | FaceplateControl | TrendControl | WebBrowserControl | MultiStateControl | ModeSelectorControl | PermissiveControl, Field(discriminator="kind")]


class Screen(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,59}$')
    title: str = Field(min_length=1, max_length=120)
    columns: Literal[1, 2, 3] = 2
    update_ms: int = Field(default=500, ge=100, le=60000)
    popup: bool = False
    layout: CanvasLayout | None = None
    controls: list[Control] = Field(default_factory=list, max_length=100)


class FaceplateDefinition(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,59}$')
    name: str = Field(min_length=1, max_length=100)
    udt_type: str = Field(default='', max_length=100)
    members: dict[str, Literal['boolean', 'number', 'integer', 'string']] = Field(default_factory=dict, max_length=100)
    controls: list[Control] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def nonrecursive(self):
        if any(control.kind == 'faceplate' for control in self.controls):
            raise ValueError('Nested faceplates are not supported')
        return self


class Project(StrictModel):
    identity_publication: IdentityPublication = Field(default_factory=IdentityPublication)
    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=120)
    columns: Literal[1, 2, 3] = 2
    controls: list[Control] = Field(max_length=100)
    layout: CanvasLayout | None = None
    update_ms: int = Field(default=500, ge=100, le=60000)
    screens: list[Screen] = Field(default_factory=list, max_length=100)
    faceplates: list[FaceplateDefinition] = Field(default_factory=list, max_length=100)
    connections: list[Connection] = Field(default_factory=list, max_length=MAX_PLC_CONNECTIONS)
    tags: list[TagDefinition] = Field(default_factory=list, max_length=5000)
    historian: HistorianSettings = Field(default_factory=HistorianSettings)
    commands: list[CommandDefinition] = Field(default_factory=list, max_length=100)
    recipe_transfers: list[RecipeTransferDefinition] = Field(default_factory=list, max_length=100)
    languages: list[Language] = Field(default_factory=lambda: [Language(code="en", name="English", flag="us")], min_length=1, max_length=30)
    default_language: str = "en"
    alarms: list[AlarmDefinition] = Field(default_factory=list, max_length=1000)
    alarm_history_limit: int = Field(default=1000, ge=50, le=10000)

    @model_validator(mode="after")
    def unique_ids(self):
        from .drivers import SimulatorDriver
        if any(tag.name in SimulatorDriver().snapshot() for tag in self.tags):
            raise ValueError('Built-in simulation and recipe tags cannot be redefined')
        aliases = [name for tag in self.tags for name in [tag.name, *(tag.name + '.' + member for member in tag.members)]]
        if len(aliases) != len(set(aliases)):
            raise ValueError('Logical tag and UDT member names collide')
        ids = [control.id for control in self.controls]
        if len(ids) != len(set(ids)):
            raise ValueError("Control IDs must be unique")
        languages = [language.code.lower() for language in self.languages]
        if len(languages) != len(set(languages)) or self.default_language not in [language.code for language in self.languages]:
            raise ValueError("Language codes must be unique and the default must be configured")
        if len({alarm.id for alarm in self.alarms}) != len(self.alarms):
            raise ValueError("Alarm IDs must be unique")
        for name, items in [('screen', self.screens), ('faceplate', self.faceplates), ('connection', self.connections), ('command', self.commands), ('recipe transfer', self.recipe_transfers)]:
            if len({item.id for item in items}) != len(items):
                raise ValueError(f'{name} IDs must be unique')
        if any(screen.id == 'overview' for screen in self.screens):
            raise ValueError('overview is the reserved main screen ID')
        if len({tag.name for tag in self.tags}) != len(self.tags):
            raise ValueError('Tag names must be unique')
        connections = {connection.id for connection in self.connections}
        if any(tag.connection and tag.connection not in connections for tag in self.tags):
            raise ValueError('Tag references an unknown connection')
        for layout, controls in [(self.layout, self.controls), *((screen.layout, screen.controls) for screen in self.screens)]:
            if layout and layout.boxes.keys() != {control.id for control in controls}:
                raise ValueError('Freeform layout must include a position for every control')
        for screen in self.screens:
            if len({control.id for control in screen.controls}) != len(screen.controls):
                raise ValueError('Control IDs must be unique within a screen')
        return self


class RevisionRequest(StrictModel):
    expected_revision: int = Field(ge=1, le=9223372036854775807)


class SaveRequest(RevisionRequest):
    project: Project


class ApplyRequest(RevisionRequest):
    reason: str = Field(default='Live apply', min_length=1, max_length=1000, pattern=r'\S')


class StageRequest(RevisionRequest):
    reason: str = Field(min_length=1, max_length=1000, pattern=r'\S')
    scope: Literal['screens', 'project'] = 'screens'


class RecoveryRequest(StrictModel):
    base_revision: int = Field(ge=1, le=9223372036854775807)
    base: Project
    local: Project
    reason: str = Field(min_length=1, max_length=1000, pattern=r'\S')


class MergePreview(StrictModel):
    base: Project
    local: Project
    choices: dict[str, Literal['local', 'current']] = Field(default_factory=dict, max_length=20000)


class MergeRequest(MergePreview, RevisionRequest):
    base_revision: int = Field(ge=1, le=9223372036854775807)
    reason: str = Field(min_length=1, max_length=1000, pattern=r'\S')


def default_project() -> Project:
    return Project.model_validate({
        "title": "Station overview", "columns": 2,
        "tags": [{"name": "OperatorText", "type": "string", "initial": "", "writable": True}],
        "alarms": [{"id": "process_alarm", "tag": "ProcessAlarm", "message": "Process alarm"}],
        "controls": [
            {"id": "level", "kind": "numeric", "label": "Tank level", "tag": "TankLevel", "unit": "%", "decimals": 1},
            {"id": "motor", "kind": "indicator", "label": "Motor", "tag": "MotorRunning"},
            {"id": "toggle", "kind": "button", "label": "Toggle simulated motor", "action": "toggle_motor"},
            {"id": "range", "kind": "analog", "label": "Tank operating range", "tag": "TankLevel", "unit": "%", "decimals": 1},
            {"id": "alarm", "kind": "alarm", "label": "Process alarm", "tag": "ProcessAlarm", "priority": 2},
        ],
    })


class RevisionConflict(Exception):
    pass


class ProjectStore:
    def __init__(self, path: Path | None = None, *, initial_project: Project | None = None):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        try:
            tables = {row[0] for row in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and 'project' not in tables:
                raise ValueError('Database is not an OpenHMI project; no migration was performed')
            existing = 'project' in tables
            if existing:
                if initial_project is not None:
                    raise ValueError('Initial project settings cannot replace an existing project')
                state = self._read()
                Project.model_validate(state['draft'])
                Project.model_validate(state['active'])
                for key in ('draft_revision', 'active_revision'):
                    if type(state[key]) is not int or not 1 <= state[key] <= 9223372036854775807:
                        raise ValueError('Invalid project revision counters')
            else:
                initial = (initial_project or default_project()).model_dump()
                state = {'draft_revision': 1, 'active_revision': 1, 'draft': initial, 'active': initial}
            if 'project_storage' in tables:
                version = self._db.execute('SELECT version FROM project_storage WHERE id=1').fetchone()
                if version != (1,):
                    raise ValueError('Unsupported OpenHMI project storage version; no migration was performed')
                if not {'project_revision', 'project_recovery'} <= tables:
                    raise ValueError('Project history storage is incomplete')
                identifier = self._db.execute('SELECT project_id FROM project_storage WHERE id=1').fetchone()[0]
                if not isinstance(identifier, str) or len(identifier) != 32 or any(part not in '0123456789abcdef' for part in identifier):
                    raise ValueError('Project storage identity is invalid')
                current = self.revision(state['active_revision'])
                if not same(current['project'], Project.model_validate(state['active']).model_dump()):
                    raise ValueError('Active project does not match its recorded revision')
            else:
                if {'project_revision', 'project_recovery'} & tables:
                    raise ValueError('Unversioned project history storage is incomplete')
                with self.transaction() as db:
                    db.execute("CREATE TABLE IF NOT EXISTS project(id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL)")
                    db.execute('INSERT OR IGNORE INTO project VALUES(1,?)', (encoded(state),))
                    db.execute('CREATE TABLE project_storage(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL,project_id TEXT NOT NULL)')
                    db.execute('INSERT INTO project_storage VALUES(1,1,?)', (uuid.uuid4().hex,))
                    db.execute('CREATE TABLE project_revision(revision INTEGER PRIMARY KEY,timestamp TEXT NOT NULL,actor TEXT NOT NULL,provider TEXT NOT NULL,reason TEXT NOT NULL,source_revision INTEGER,project_json TEXT NOT NULL,content_hash TEXT NOT NULL,baseline INTEGER NOT NULL)')
                    db.execute('CREATE TABLE project_recovery(id TEXT PRIMARY KEY,timestamp TEXT NOT NULL,actor TEXT NOT NULL,provider TEXT NOT NULL,reason TEXT NOT NULL,base_revision INTEGER NOT NULL,base_json TEXT NOT NULL,local_json TEXT NOT NULL,base_hash TEXT NOT NULL,local_hash TEXT NOT NULL)')
                    self._record(db, state, ('unknown', 'legacy') if existing else ('system', 'system'),
                                 'Existing active project captured during history migration; earlier revisions are unavailable' if existing else 'Initial project', baseline=True)
        except Exception:
            self._db.close()
            raise

    @staticmethod
    def stamp():
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

    def _read(self) -> dict:
        row = self._db.execute('SELECT state FROM project WHERE id=1').fetchone()
        if not row:
            raise ValueError('Project state is missing')
        return json.loads(row[0])

    def snapshot(self) -> dict:
        with self._lock:
            return {**self._read(), 'project_id': self._db.execute('SELECT project_id FROM project_storage WHERE id=1').fetchone()[0]}

    def fork_identity(self):
        with self.transaction() as db:
            db.execute('UPDATE project_storage SET project_id=? WHERE id=1', (uuid.uuid4().hex,))

    @contextmanager
    def transaction(self):
        with self._lock, self._db:
            self._db.execute('BEGIN IMMEDIATE')
            yield self._db

    def _record(self, db, state, identity, reason, source=None, baseline=False):
        project = Project.model_validate(state['active']).model_dump()
        db.execute('INSERT INTO project_revision VALUES(?,?,?,?,?,?,?,?,?)',
                   (state['active_revision'], self.stamp(), *identity, reason, source, encoded(project), digest(project), int(baseline)))

    def revision(self, identifier):
        with self._lock:
            cursor = self._db.execute('SELECT * FROM project_revision WHERE revision=?', (identifier,))
            row = cursor.fetchone()
        if not row:
            raise KeyError('Applied project revision not found')
        item = dict(zip([column[0] for column in cursor.description], row))
        project = json.loads(item.pop('project_json'))
        if digest(project) != item['content_hash']:
            raise ValueError('Project revision integrity check failed')
        item['project'] = Project.model_validate(project).model_dump()
        item['baseline'] = bool(item['baseline'])
        return item

    def revisions(self, limit=50, before=None):
        with self._lock:
            ids = [row[0] for row in self._db.execute('SELECT revision FROM project_revision WHERE revision < ? ORDER BY revision DESC LIMIT ?',
                                                    (before or 9223372036854775807, limit + 1))]
            state = self._read()
        return {'items': [{key: value for key, value in self.revision(identifier).items() if key != 'project'} for identifier in ids[:limit]],
                'has_more': len(ids) > limit, 'next_before_revision': ids[limit - 1] if len(ids) > limit else None,
                'active_revision': state['active_revision'], 'draft_revision': state['draft_revision'], 'storage_version': 1}

    def verify_history(self):
        with self._lock:
            for (identifier,) in self._db.execute('SELECT revision FROM project_revision'):
                self.revision(identifier)
            for (identifier,) in self._db.execute('SELECT id FROM project_recovery'):
                self.recovery(identifier)

    @staticmethod
    def check_revision(state, expected):
        if expected != state['draft_revision']:
            raise RevisionConflict('Draft changed in another editor. Review and merge your local changes before saving or applying.')
        if state['draft_revision'] >= 9223372036854775807 or state['active_revision'] >= 9223372036854775807:
            raise ValueError('Project revision counter exhausted')

    def _update(self, expected_revision, project, validator=None, identity=('system', 'system'), reason='Live apply'):
        with self.transaction() as db:
            state = self._read()
            self.check_revision(state, expected_revision)
            if project is None:
                if validator:
                    validator(Project.model_validate(state['draft']))
                origin = state.get('draft_origin')
                if not same(state['active'], state['draft']) or origin:
                    state['active'] = state['draft']
                    state['active_revision'] += 1
                    self._record(db, state, identity, origin['reason'] if origin and reason == 'Live apply' else reason,
                                 origin['source_revision'] if origin else None)
                    state.pop('draft_origin', None)
            elif not same(state['draft'], project.model_dump()):
                state['draft'] = project.model_dump()
                state['draft_revision'] += 1
            db.execute('UPDATE project SET state=? WHERE id=1', (encoded(state),))
            return state

    def save(self, request):
        return self._update(request.expected_revision, request.project)

    def apply(self, request, validator=None, identity=('system', 'system')):
        return self._update(request.expected_revision, None, validator, identity, getattr(request, 'reason', 'Live apply'))

    def _recover(self, db, base, local, base_revision, reason, identity):
        identifier = uuid.uuid4().hex
        db.execute('INSERT INTO project_recovery VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (identifier, self.stamp(), *identity, reason, base_revision, encoded(base), encoded(local), digest(base), digest(local)))
        return identifier

    def recover(self, request, identity):
        with self.transaction() as db:
            identifier = self._recover(db, request.base.model_dump(), request.local.model_dump(), request.base_revision, request.reason, identity)
        return self.recovery(identifier)

    def recovery(self, identifier):
        with self._lock:
            cursor = self._db.execute('SELECT * FROM project_recovery WHERE id=?', (identifier,))
            row = cursor.fetchone()
        if not row:
            raise KeyError('Project recovery copy not found')
        item = dict(zip([column[0] for column in cursor.description], row))
        for name in ('base', 'local'):
            project = json.loads(item.pop(name + '_json'))
            if digest(project) != item[name + '_hash']:
                raise ValueError('Project recovery integrity check failed')
            item[name] = Project.model_validate(project).model_dump()
        return item

    def recoveries(self, limit=50, before=None):
        with self._lock:
            if before:
                cursor = self._db.execute('SELECT timestamp,id FROM project_recovery WHERE id=?', (before,)).fetchone()
                if not cursor:
                    raise KeyError('Project recovery cursor not found')
                rows = self._db.execute('SELECT id,timestamp FROM project_recovery WHERE (timestamp,id) < (?,?) ORDER BY timestamp DESC,id DESC LIMIT ?', (*cursor, limit + 1)).fetchall()
            else:
                rows = self._db.execute('SELECT id,timestamp FROM project_recovery ORDER BY timestamp DESC,id DESC LIMIT ?', (limit + 1,)).fetchall()
        return {'items': [{key: value for key, value in self.recovery(identifier).items() if key not in ('base', 'local')} for identifier, _ in rows[:limit]],
                'has_more': len(rows) > limit, 'next_before_id': rows[limit - 1][0] if len(rows) > limit else None}

    def stage(self, identifier, request, validator, identity):
        with self.transaction() as db:
            state = self._read()
            self.check_revision(state, request.expected_revision)
            historical = self.revision(identifier)['project']
            target = deepcopy(state['draft']) if request.scope == 'screens' else historical
            if request.scope == 'screens':
                for field in SCREEN_FIELDS:
                    target[field] = deepcopy(historical[field])
            project = Project.model_validate(target)
            validator(project)
            recovery = self._recover(db, state['draft'], state['draft'], state['draft_revision'], 'Server draft before staging revision ' + str(identifier), identity)
            state['draft'] = project.model_dump()
            state['draft_revision'] += 1
            state['draft_origin'] = {'source_revision': identifier, 'scope': request.scope, 'reason': request.reason}
            db.execute('UPDATE project SET state=? WHERE id=1', (encoded(state),))
        return {**state, 'preserved_recovery_id': recovery}

    def merge(self, request, validator, identity):
        with self.transaction() as db:
            state = self._read()
            self.check_revision(state, request.expected_revision)
            result = merge_project(request.base.model_dump(), request.local.model_dump(), Project.model_validate(state['draft']).model_dump(), request.choices)
            if not result['complete']:
                raise RevisionConflict('Choose local or current for every overlapping change before merging')
            project = Project.model_validate(result['project'])
            validator(project)
            recovery = self._recover(db, state['draft'], state['draft'], state['draft_revision'], 'Server draft before merge: ' + request.reason, identity)
            self._recover(db, request.base.model_dump(), request.local.model_dump(), request.base_revision, 'Local candidate before merge: ' + request.reason, identity)
            state['draft'] = project.model_dump()
            state['draft_revision'] += 1
            db.execute('UPDATE project SET state=? WHERE id=1', (encoded(state),))
        return {**state, 'preserved_recovery_id': recovery}

    def close(self):
        with self._lock:
            self._db.close()
