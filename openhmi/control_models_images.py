"""Images control schemas; imported by the canonical project model."""
from typing import Literal
from pydantic import Field
from .control_models_base import StrictModel, ControlBase, StateCode, StateControl, ProgressControl


class StaticImageControl(ControlBase):
    kind: Literal['image']
    image: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')
    alt_text: str = Field(default='', max_length=200)
    fit: Literal['contain', 'cover', 'fill'] = 'contain'
    show_label: bool = True


class StateImageControl(ControlBase):
    kind: Literal['state_image']
    tag: str = Field(min_length=1, max_length=200)
    on_image: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')
    off_image: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')
    on_text: str = Field(default='ON', min_length=1, max_length=100)
    off_text: str = Field(default='OFF', min_length=1, max_length=100)
    show_label: bool = True


class ImageState(StrictModel):
    value: StateCode
    label: str = Field(min_length=1, max_length=100)
    image: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')


class MultiStateImageControl(StateControl):
    kind: Literal['multi_state_image']
    states: list[ImageState] = Field(min_length=2, max_length=32)
    show_label: bool = True


class MotionImageControl(ProgressControl):
    image: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')
    show_label: bool = True


class PositionImageControl(MotionImageControl):
    kind: Literal['position_image']
    direction: Literal['left_to_right', 'right_to_left', 'bottom_to_top', 'top_to_bottom'] = 'left_to_right'
    size_percent: int = Field(default=25, ge=10, le=60)


class RotationImageControl(MotionImageControl):
    kind: Literal['rotation_image']
    angle_start: float = Field(default=0.0, ge=-360, le=360, allow_inf_nan=False)
    angle_end: float = Field(default=360.0, ge=-360, le=360, allow_inf_nan=False)
    size_percent: int = Field(default=50, ge=10, le=70)
