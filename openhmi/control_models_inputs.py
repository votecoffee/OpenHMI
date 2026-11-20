"""Inputs control schemas; imported by the canonical project model."""
import math
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .edit_limits import MAX_UTC_EPOCH
from .control_models_base import StrictModel, ControlBase, StateCode, NumericControl


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


class NumericStepperControl(NumericInputControl):
    kind: Literal['stepper']
    step: float = Field(default=1.0, ge=0.00000001, le=1e12, allow_inf_nan=False)


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
