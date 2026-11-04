"""Editor-independent screen schema and transactional draft/apply persistence."""

import json
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .runtime_models import Connection, TagDefinition, HistorianSettings


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ControlBase(StrictModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=100)
    visible_tag: str = Field(default='', max_length=200)
    enabled_tag: str = Field(default='', max_length=200)
    color_tag: str = Field(default='', max_length=200)
    active_color: str = Field(default='#002878', pattern=r'^#[a-fA-F0-9]{6}$')


class NumericControl(ControlBase):
    kind: Literal["numeric"]
    tag: str = Field(min_length=1, max_length=200)
    unit: str = Field(default="", max_length=30)
    decimals: int = Field(default=1, ge=0, le=4)


class IndicatorControl(ControlBase):
    kind: Literal["indicator"]
    tag: str = Field(min_length=1, max_length=200)
    on_text: str = Field(default="ON", min_length=1, max_length=30)
    off_text: str = Field(default="OFF", min_length=1, max_length=30)


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


class AlarmControl(ControlBase):
    kind: Literal["alarm"]
    tag: str = Field(min_length=1, max_length=200)
    priority: Literal[1, 2, 3, 4] = 2


class ButtonControl(ControlBase):
    kind: Literal["button"]
    action: str = Field(default='', max_length=100)
    mode: Literal['python', 'set', 'toggle', 'navigate', 'popup', 'close_popup'] = 'python'
    target: str = Field(default='', max_length=200)
    value: float | int | bool | str = False
    screen: str = Field(default='overview', max_length=60)
    security_groups: list[str] = Field(default_factory=list, max_length=100)


class NumericInputControl(NumericControl):
    kind: Literal['input']
    minimum: float = Field(default=0.0, allow_inf_nan=False)
    maximum: float = Field(default=100.0, allow_inf_nan=False)
    security_groups: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def ordered_limits(self):
        if self.minimum >= self.maximum:
            raise ValueError('Input minimum must be less than maximum')
        return self


class RecipeSelectionControl(ControlBase):
    kind: Literal['recipe']


class FaceplateControl(ControlBase):
    kind: Literal['faceplate']
    template: str = Field(min_length=1, max_length=60)
    root_tag: str = Field(min_length=1, max_length=200)


class TrendControl(ControlBase):
    kind: Literal['trend']
    tags: list[str] = Field(min_length=1, max_length=12)
    seconds: int = Field(default=300, ge=10, le=604800)


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
    priority: Literal[1, 2, 3, 4] = 2
    ack_required: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def valid_trigger(self):
        if self.trigger_value == 0 or (self.trigger_type != "value" and not 1 <= self.trigger_value <= 32):
            raise ValueError("Value triggers must be nonzero; bit/lsbit positions are 1..32")
        return self


Control = Annotated[NumericControl | NumericInputControl | IndicatorControl | AnalogControl | AlarmControl | ButtonControl | RecipeSelectionControl | FaceplateControl | TrendControl, Field(discriminator="kind")]


class Screen(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,59}$')
    title: str = Field(min_length=1, max_length=120)
    columns: Literal[1, 2, 3] = 2
    update_ms: int = Field(default=500, ge=100, le=60000)
    popup: bool = False
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
    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=120)
    columns: Literal[1, 2, 3] = 2
    controls: list[Control] = Field(max_length=100)
    update_ms: int = Field(default=500, ge=100, le=60000)
    screens: list[Screen] = Field(default_factory=list, max_length=100)
    faceplates: list[FaceplateDefinition] = Field(default_factory=list, max_length=100)
    connections: list[Connection] = Field(default_factory=list, max_length=20)
    tags: list[TagDefinition] = Field(default_factory=list, max_length=5000)
    historian: HistorianSettings = Field(default_factory=HistorianSettings)
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
        for name, items in [('screen', self.screens), ('faceplate', self.faceplates), ('connection', self.connections)]:
            if len({item.id for item in items}) != len(items):
                raise ValueError(f'{name} IDs must be unique')
        if any(screen.id == 'overview' for screen in self.screens):
            raise ValueError('overview is the reserved main screen ID')
        if len({tag.name for tag in self.tags}) != len(self.tags):
            raise ValueError('Tag names must be unique')
        connections = {connection.id for connection in self.connections}
        if any(tag.connection and tag.connection not in connections for tag in self.tags):
            raise ValueError('Tag references an unknown connection')
        for screen in self.screens:
            if len({control.id for control in screen.controls}) != len(screen.controls):
                raise ValueError('Control IDs must be unique within a screen')
        return self


class RevisionRequest(StrictModel):
    expected_revision: int = Field(ge=1)


class SaveRequest(RevisionRequest):
    project: Project


def default_project() -> Project:
    return Project.model_validate({
        "title": "Station overview", "columns": 2,
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
    def __init__(self, path: Path | None = None):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        with self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS project (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL)")
            initial = default_project().model_dump()
            state = {"draft_revision": 1, "active_revision": 1, "draft": initial, "active": initial}
            self._db.execute("INSERT OR IGNORE INTO project VALUES (1, ?)", (json.dumps(state),))
        state = self.snapshot()
        Project.model_validate(state["draft"])
        Project.model_validate(state["active"])

    def _read(self) -> dict:
        return json.loads(self._db.execute("SELECT state FROM project WHERE id=1").fetchone()[0])

    def snapshot(self) -> dict:
        with self._lock:
            return self._read()

    @contextmanager
    def transaction(self):
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            yield self._db

    def _update(self, expected_revision: int, project: Project | None, validator=None) -> dict:
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            state = self._read()
            if expected_revision != state["draft_revision"]:
                raise RevisionConflict("Draft changed in another editor. Reload the draft before saving or applying.")
            if project is None:
                if validator:
                    validator(Project.model_validate(state["draft"]))
                if state["active"] != state["draft"]:
                    state["active"] = state["draft"]
                    state["active_revision"] += 1
            elif state["draft"] != project.model_dump():
                state["draft"] = project.model_dump()
                state["draft_revision"] += 1
            self._db.execute("UPDATE project SET state=? WHERE id=1", (json.dumps(state),))
            return state

    def save(self, request: SaveRequest) -> dict:
        return self._update(request.expected_revision, request.project)

    def apply(self, request: RevisionRequest, validator=None) -> dict:
        return self._update(request.expected_revision, None, validator)

    def close(self):
        with self._lock:
            self._db.close()
