"""Operator-control request models and input families shared by validation and routing."""

from pydantic import BaseModel, ConfigDict, Field


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control_id: str | None = None


class ButtonRequest(ActionRequest):
    expected_revision: int | None = Field(default=None, strict=True, ge=1, le=9223372036854775807)


CHOICE_INPUTS = ('dropdown', 'radio_group')
BOOLEAN_INPUTS = ('checkbox', 'toggle_switch')
PALETTE_INPUTS = (*CHOICE_INPUTS, *BOOLEAN_INPUTS, 'text_area', 'barcode_input', 'slider', 'stepper', 'date_time')
EDIT_INPUTS = ('input', 'text_input', 'mode_selector', *PALETTE_INPUTS)


class ValueRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    value: float | int | str | bool
    expected_revision: int | None = Field(default=None, ge=1, le=9223372036854775807)
