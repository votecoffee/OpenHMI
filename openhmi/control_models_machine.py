"""Machine control schemas; imported by the canonical project model."""
from typing import Literal
from pydantic import Field, model_validator
from .control_models_base import StrictModel, ControlBase, StateControl


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


class StackLamp(StrictModel):
    tag: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=100)
    active_when: bool = True
    color: str = Field(default='#555555', pattern=r'^#[a-fA-F0-9]{6}$')


class StackLightControl(ControlBase):
    kind: Literal['stack_light']
    lamps: list[StackLamp] = Field(min_length=1, max_length=6)
    orientation: Literal['vertical', 'horizontal'] = 'vertical'


class BitfieldBit(StrictModel):
    bit: int = Field(ge=0, le=31)
    label: str = Field(min_length=1, max_length=100)


class BitfieldControl(ControlBase):
    kind: Literal['bitfield']
    tag: str = Field(min_length=1, max_length=200)
    bits: list[BitfieldBit] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def unique_bits(self):
        if len({item.bit for item in self.bits}) != len(self.bits):
            raise ValueError('Bitfield positions must be unique')
        return self


class ButtonControl(ControlBase):
    kind: Literal["button"]
    action: str = Field(default='', max_length=100)
    mode: Literal['python', 'set', 'toggle', 'navigate', 'popup', 'close_popup', 'command'] = 'python'
    command: str = Field(default='', max_length=60)
    target: str = Field(default='', max_length=200)
    value: float | int | bool | str = False
    screen: str = Field(default='overview', max_length=60)
    security_groups: list[str] = Field(default_factory=list, max_length=100)


class FaceplateControl(ControlBase):
    kind: Literal['faceplate']
    template: str = Field(min_length=1, max_length=60)
    root_tag: str = Field(min_length=1, max_length=200)
