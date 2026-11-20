"""Identity publication configuration, independent of publisher and HTTP services."""
from typing import Literal
from pydantic import Field, model_validator
from .runtime_models import Model


class PrivilegeBit(Model):
    bit: int = Field(ge=0, le=31)
    source: Literal['permission', 'group'] = 'permission'
    name: str = Field(min_length=1, max_length=100)


class IdentityPublication(Model):
    enabled: bool = False
    username_tag: str = Field(default='', max_length=200)
    privileges_tag: str = Field(default='', max_length=200)
    heartbeat_tag: str = Field(default='', max_length=200)
    username_bytes: int = Field(default=82, ge=1, le=4096)
    bits: list[PrivilegeBit] = Field(default_factory=list, max_length=32)

    @model_validator(mode='after')
    def unique(self):
        if len({item.bit for item in self.bits}) != len(self.bits):
            raise ValueError('Privilege bit positions must be unique')
        if self.enabled and (not self.username_tag or not self.privileges_tag or self.username_tag == self.privileges_tag):
            raise ValueError('Identity publication requires separate STRING and DINT tags')
        if self.heartbeat_tag and self.heartbeat_tag in (self.username_tag, self.privileges_tag):
            raise ValueError('Heartbeat must use its own DINT tag')
        return self
