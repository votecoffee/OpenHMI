"""Connections, logical tags and history configuration, independent of the editor."""

from typing import Literal
import json
import math
import re
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Connection(Model):
    id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,59}$')
    name: str = Field(min_length=1, max_length=100)
    kind: Literal['logix'] = 'logix'
    path: str = Field(min_length=1, max_length=200)
    enabled: bool = False
    timeout_seconds: float = Field(default=2.0, ge=0.2, le=10)
    program_tags: bool = True


class TagDefinition(Model):
    name: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_.\[\]:-]{0,199}$')
    connection: str = ''
    address: str = Field(default='', max_length=200)
    type: Literal['boolean', 'number', 'integer', 'string', 'struct'] = 'number'
    initial: float | int | bool | str | dict = 0.0
    writable: bool = False
    scale: float = Field(default=1.0, allow_inf_nan=False)
    offset: float = Field(default=0.0, allow_inf_nan=False)
    members: dict[str, Literal['boolean', 'number', 'integer', 'string']] = Field(default_factory=dict, max_length=500)
    udt_type: str = Field(default='', max_length=100)

    @model_validator(mode='after')
    def valid_tag(self):
        try:
            json.dumps(self.initial, allow_nan=False)
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError('Initial values must be finite JSON data') from error
        if self.connection and not self.address:
            raise ValueError('PLC tags require an address')
        if self.scale == 0 or (self.type not in ('number', 'integer') and (self.scale != 1 or self.offset != 0)):
            raise ValueError('Scaling requires a numeric tag and nonzero scale')
        if self.type != 'struct' and self.members:
            raise ValueError('Only structure tags define members')
        if any(not key or len(key) > 160 or not all(part.isidentifier() or part.isdigit() for part in key.replace('[', '.').replace(']', '').split('.')) for key in self.members):
            raise ValueError('Invalid UDT member path')
        if not self.connection:
            types = {'boolean': (bool,), 'number': (int, float), 'integer': (int,), 'string': (str,), 'struct': (dict,)}
            if type(self.initial) not in types[self.type]:
                raise ValueError('Initial value must match the local tag type')
            if self.scale != 1 or self.offset != 0:
                raise ValueError('Local tags use engineering values directly; scaling is for PLC sources')
            for path, kind in self.members.items():
                try:
                    value = self.initial
                    for part in re.findall(r'[^.\[\]]+', path):
                        value = value[int(part)] if isinstance(value, list) else value[part]
                    if type(value) not in types[kind]:
                        raise ValueError('Initial UDT member type does not match its declaration')
                except (KeyError, TypeError, IndexError) as error:
                    raise ValueError('Initial UDT data must contain all declared members') from error
        return self


class HistoryTag(Model):
    tag: str = Field(min_length=1, max_length=200)
    sample_ms: int = Field(default=1000, ge=100, le=3600000)
    deadband: float = Field(default=0.0, ge=0, allow_inf_nan=False)


class HistorianSettings(Model):
    tags: list[HistoryTag] = Field(default_factory=list, max_length=1000)
    retention_days: int = Field(default=30, ge=1, le=3650)
    max_rows: int = Field(default=1000000, ge=1000, le=10000000)

    @model_validator(mode='after')
    def distinct_tags(self):
        if len({tag.tag for tag in self.tags}) != len(self.tags):
            raise ValueError('History tags must be unique')
        return self


class CommandDefinition(Model):
    id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,59}$')
    name: str = Field(min_length=1, max_length=100)
    root_tag: str = Field(min_length=1, max_length=200)
    request_member: str = 'RequestSequence'
    accepted_member: str = 'AcceptedSequence'
    completed_member: str = 'CompletedSequence'
    result_member: str = 'ResultCode'
    permit_member: str = Field(default='', max_length=160)
    timeout_seconds: float = Field(default=30.0, ge=1, le=3600, allow_inf_nan=False)
    update_ms: int = Field(default=250, ge=100, le=5000)
    security_groups: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def distinct_members(self):
        names = [self.request_member, self.accepted_member, self.completed_member, self.result_member]
        if self.permit_member:
            names.append(self.permit_member)
        if any(not name or len(name) > 160 for name in names) or len(set(names)) != len(names):
            raise ValueError('Command members must be nonempty and distinct')
        return self
