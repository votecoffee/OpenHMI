"""Canonical project schemas and control union; no SQLite store dependency.

Control families share strict bases. Legacy imports from openhmi.projects and
this module resolve to the same model objects.
"""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .runtime_models import MAX_PLC_CONNECTIONS, Connection, TagDefinition, HistorianSettings
from .runtime_models import CommandDefinition, RecipeTransferDefinition
from .identity_publish import IdentityPublication
from .canvas import CanvasLayout
from .edit_limits import MAX_UTC_EPOCH  # compatibility export
from .control_models_base import (
    StrictModel, ControlBase, StateCode, MachineState, StateControl, NumericControl,
    ProgressControl,
)
from .control_models_machine import (
    MultiStateControl, ModeSelectorControl, PermissiveRow, PermissiveControl, StackLamp,
    StackLightControl, BitfieldBit, BitfieldControl, ButtonControl, FaceplateControl,
)
from .control_models_inputs import (
    NumericInputControl, NumericStepperControl, DateTimeControl, TextInputControl, ChoiceOption,
    ChoiceInputControl, BooleanInputControl,
)
from .control_models_images import (
    StaticImageControl, StateImageControl, ImageState, MultiStateImageControl, MotionImageControl,
    PositionImageControl, RotationImageControl,
)
from .control_models_process import (
    SetpointComparisonControl, AnalogControl, TankControl, GaugeControl, ChartSeries, RadarAxis,
    RadarControl, BarGraphControl, PieControl, XYSeries, XYControl, TrendSeries, TrendRecording,
    TrendControl,
)
from .control_models_readouts import (
    LedDisplayControl, TagQualityControl, ConnectionStatusControl, LabelControl, SymbolControl,
    SparklineControl, DateTimeDisplayControl, DurationDisplayControl, TextDisplayControl,
    IndicatorControl, AlarmControl, CurrentUserControl, RecipeSelectionControl, WebBrowserControl,
)


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


Control = Annotated[NumericControl | NumericInputControl | NumericStepperControl | LedDisplayControl | TagQualityControl | ConnectionStatusControl | DateTimeControl | DateTimeDisplayControl | DurationDisplayControl | LabelControl | StaticImageControl | StateImageControl | MultiStateImageControl | SymbolControl | SparklineControl | TextDisplayControl | TextInputControl | ChoiceInputControl | BooleanInputControl | CurrentUserControl | IndicatorControl | AnalogControl | SetpointComparisonControl | ProgressControl | PositionImageControl | RotationImageControl | TankControl | GaugeControl | BarGraphControl | PieControl | RadarControl | XYControl | AlarmControl | ButtonControl | RecipeSelectionControl | FaceplateControl | TrendControl | WebBrowserControl | MultiStateControl | ModeSelectorControl | PermissiveControl | StackLightControl | BitfieldControl, Field(discriminator="kind")]


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
