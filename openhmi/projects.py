"""Editor-independent screen schema and transactional draft/apply persistence."""

import json
import math
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ControlBase(StrictModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=100)


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
    action: str = Field(min_length=1, max_length=100)


Control = Annotated[NumericControl | IndicatorControl | AnalogControl | AlarmControl | ButtonControl, Field(discriminator="kind")]


class Project(StrictModel):
    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=120)
    columns: Literal[1, 2, 3] = 2
    controls: list[Control] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [control.id for control in self.controls]
        if len(ids) != len(set(ids)):
            raise ValueError("Control IDs must be unique")
        return self


class RevisionRequest(StrictModel):
    expected_revision: int = Field(ge=1)


class SaveRequest(RevisionRequest):
    project: Project


def default_project() -> Project:
    return Project.model_validate({
        "title": "Station overview", "columns": 2, "controls": [
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
