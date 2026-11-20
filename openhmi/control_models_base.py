"""Shared strict control schemas and reusable bases."""
import math
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class NumericControl(ControlBase):
    kind: Literal["numeric"]
    tag: str = Field(min_length=1, max_length=200)
    unit: str = Field(default="", max_length=30)
    decimals: int = Field(default=1, ge=0, le=4)


class ProgressControl(NumericControl):
    kind: Literal['progress']
    minimum: float = Field(default=0.0, allow_inf_nan=False)
    maximum: float = Field(default=100.0, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered_scale(self):
        if not 0 < self.maximum - self.minimum < math.inf:
            raise ValueError('Scale must have a positive, finite span')
        return self
