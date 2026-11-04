"""Typed recipe content and change-control requests."""

import math
from typing import Literal
from pydantic import Field, model_validator
from .projects import StrictModel


class RecipeParameter(StrictModel):
    name: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,59}$')
    label: str = Field(min_length=1, max_length=100)
    type: Literal['number', 'integer', 'boolean', 'text']
    value: float | int | bool | str
    unit: str = Field(default='', max_length=30)
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode='after')
    def typed_value(self):
        valid = {'number': (int, float), 'integer': (int,), 'boolean': (bool,), 'text': (str,)}
        if type(self.value) not in valid[self.type]:
            raise ValueError(f'{self.name}: value does not match {self.type}')
        if self.type in ('number', 'integer'):
            if abs(self.value) > 1e100 or not math.isfinite(self.value):
                raise ValueError('Numeric recipe values must be finite')
            if self.type == 'integer' and abs(self.value) > 9007199254740991:
                raise ValueError('Integer recipe values must be exactly representable by the editor')
            if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
                raise ValueError('Minimum must not exceed maximum')
            if self.minimum is not None and self.value < self.minimum or self.maximum is not None and self.value > self.maximum:
                raise ValueError(f'{self.name}: value is outside its limits')
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError('Only numeric parameters have numeric limits')
        if isinstance(self.value, str) and len(self.value) > 1000:
            raise ValueError('Recipe text value is too long')
        return self


class RecipeContent(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=2000)
    image_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    parameters: list[RecipeParameter] = Field(default_factory=list, max_length=200)

    @model_validator(mode='after')
    def unique_parameters(self):
        if len({parameter.name for parameter in self.parameters}) != len(self.parameters):
            raise ValueError('Parameter names must be unique')
        return self


class ChangeReason(StrictModel):
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def reason_required(self):
        if not self.reason.strip():
            raise ValueError('A meaningful change reason is required')
        return self


class RecipeCreate(ChangeReason):
    code: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$')
    content: RecipeContent


class RecipeSave(ChangeReason):
    expected_latest_revision: int = Field(ge=1)
    parent_revision: int = Field(ge=1)
    content: RecipeContent


class RecipeTransition(ChangeReason):
    expected_version: int = Field(ge=1)
    action: Literal['submit', 'approve', 'reject', 'withdraw']


class RecipeSelect(ChangeReason):
    revision_id: int | None = Field(default=None, ge=1)
    expected_selection_version: int = Field(ge=1)
    expected_revision_version: int | None = Field(default=None, ge=1)


class RecipeTransfer(ChangeReason):
    revision_id: int = Field(ge=1, le=2147483647)
    expected_revision_version: int = Field(ge=1)


class RecipePolicy(StrictModel):
    editing_enabled: bool = True
    approval_enabled: bool = True
    loading_enabled: bool = True
    editing_permit_tag: str | None = Field(default=None, min_length=1, max_length=200)
    approval_permit_tag: str | None = Field(default=None, min_length=1, max_length=200)
    loading_permit_tag: str | None = Field(default=None, min_length=1, max_length=200)


class PolicyChange(ChangeReason):
    expected_version: int = Field(ge=1)
    policy: RecipePolicy


class SimulationPermit(ChangeReason):
    allowed: bool
