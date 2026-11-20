"""Readouts control schemas; imported by the canonical project model."""
import re
from ipaddress import IPv4Address
from typing import Literal
from pydantic import Field, model_validator
from .control_models_base import ControlBase, NumericControl


class LedDisplayControl(NumericControl):
    kind: Literal['led_display']
    digits: int = Field(default=5, ge=2, le=12)

    @model_validator(mode='after')
    def room_for_integer(self):
        if self.decimals >= self.digits:
            raise ValueError('LED display requires at least one whole-number position')
        return self


class TagQualityControl(ControlBase):
    kind: Literal['tag_quality']
    tag: str = Field(min_length=1, max_length=200)
    show_age: bool = True


class ConnectionStatusControl(ControlBase):
    kind: Literal['connection_status']
    connection: str = Field(default='', max_length=60)


class LabelControl(ControlBase):
    kind: Literal['label']
    font_size: int = Field(default=16, ge=8, le=72)
    alignment: Literal['start', 'center', 'end'] = 'start'
    weight: Literal['normal', 'bold'] = 'normal'


class SymbolControl(ControlBase):
    kind: Literal['symbol']
    symbol: Literal['arrow', 'info', 'warning', 'check', 'circle', 'diamond'] = 'arrow'
    size: int = Field(default=28, ge=12, le=96)
    rotation: Literal[0, 90, 180, 270] = 0


class SparklineControl(NumericControl):
    kind: Literal['sparkline']
    seconds: int = Field(default=60, ge=5, le=3600)


class DateTimeDisplayControl(ControlBase):
    kind: Literal['date_time_display']
    tag: str = Field(min_length=1, max_length=200)


class DurationDisplayControl(ControlBase):
    kind: Literal['duration']
    tag: str = Field(min_length=1, max_length=200)
    source_unit: Literal['seconds', 'milliseconds'] = 'milliseconds'
    decimals: int = Field(default=0, ge=0, le=3)


class TextDisplayControl(ControlBase):
    kind: Literal['text']
    tag: str = Field(min_length=1, max_length=200)


class IndicatorControl(ControlBase):
    kind: Literal["indicator"]
    tag: str = Field(min_length=1, max_length=200)
    on_text: str = Field(default="ON", min_length=1, max_length=30)
    off_text: str = Field(default="OFF", min_length=1, max_length=30)


class AlarmControl(ControlBase):
    kind: Literal["alarm"]
    tag: str = Field(min_length=1, max_length=200)
    priority: Literal[1, 2, 3, 4] = 2


class RecipeSelectionControl(ControlBase):
    kind: Literal['recipe']


class CurrentUserControl(ControlBase):
    kind: Literal['current_user']


class WebBrowserControl(ControlBase):
    kind: Literal['web_browser']
    scheme: Literal['http', 'https'] = 'https'
    hosts: str = Field(default='', max_length=1024)
    port: int | None = Field(default=None, ge=1, le=65535)
    path: str = Field(default='/', max_length=512)
    address_tag: str = Field(default='', max_length=200)
    refresh_tag: str = Field(default='', max_length=200)

    @model_validator(mode='after')
    def valid_destination(self):
        if not re.fullmatch(r'/[A-Za-z0-9._~/-]*', self.path) or '//' in self.path or any(
            segment in ('.', '..') for segment in self.path.split('/')
        ):
            raise ValueError('Browser path must be an absolute plain path without traversal, query or fragment')
        hosts = [host.strip().lower() for host in self.hosts.split(',')] if self.hosts.strip() else []
        if len(hosts) > 16 or len(set(hosts)) != len(hosts):
            raise ValueError('Browser hosts must be unique and limited to 16')
        for host in hosts:
            try:
                IPv4Address(host)
            except ValueError:
                labels = host.split('.')
                if len(host) > 253 or not re.match(r'[a-z]', labels[-1]) or any(
                    not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels
                ):
                    raise ValueError('Browser hosts must be exact DNS names or IPv4 addresses') from None
        return self
