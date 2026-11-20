"""Canvas layout schemas without image processing, HTTP or persistence services."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CanvasBox(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    x: int = Field(ge=0, le=4096)
    y: int = Field(ge=0, le=4096)
    width: int = Field(ge=32, le=4096)
    height: int = Field(ge=24, le=4096)
    z: int = Field(default=0, ge=0, le=9999)
    group: str = Field(default='', max_length=100)


class CanvasContainer(CanvasBox):
    mode: Literal['grid', 'stack']
    columns: int = Field(default=2, ge=1, le=8)
    members: list[str] = Field(default_factory=list, max_length=100)


class CanvasDecoration(CanvasBox):
    kind: Literal['image', 'rectangle', 'ellipse']
    label: str = Field(min_length=1, max_length=100)
    locked: bool = False
    image: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')
    fill: str = Field(default='#aaaaaa', pattern=r'^#[a-fA-F0-9]{6}$')

    @model_validator(mode='after')
    def valid_decoration(self):
        if (self.kind == 'image') != bool(self.image):
            raise ValueError('Only image objects require an image reference')
        if self.locked and self.group:
            raise ValueError('Locked background objects cannot belong to a group')
        return self


class CanvasLayout(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    width: int = Field(default=1024, ge=160, le=4096)
    height: int = Field(default=640, ge=120, le=4096)
    grid: int = Field(default=8, ge=2, le=100)
    snap: bool = True
    background: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')
    boxes: dict[str, CanvasBox] = Field(default_factory=dict, max_length=100)
    containers: dict[str, CanvasContainer] = Field(default_factory=dict, max_length=30)
    decorations: dict[str, CanvasDecoration] = Field(default_factory=dict, max_length=60)

    @model_validator(mode='after')
    def consistent(self):
        keys = [*self.boxes, *self.containers, *self.decorations]
        if len(keys) != len(set(keys)):
            raise ValueError('Canvas object IDs must be distinct')
        members = [member for container in self.containers.values() for member in container.members]
        if len(members) != len(set(members)) or set(members) - self.boxes.keys():
            raise ValueError('A control can belong to one canvas container')
        for box in (*self.boxes.values(), *self.containers.values(), *self.decorations.values()):
            if box.x + box.width > self.width or box.y + box.height > self.height:
                raise ValueError('Canvas objects must fit within the screen')
        return self
