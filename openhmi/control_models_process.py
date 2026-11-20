"""Process control schemas; imported by the canonical project model."""
import math
from typing import Literal
from pydantic import Field, model_validator
from .control_models_base import StrictModel, ControlBase, NumericControl


class SetpointComparisonControl(NumericControl):
    kind: Literal['setpoint_comparison']
    setpoint_tag: str = Field(default='', max_length=200)
    tolerance: float = Field(default=1.0, ge=0, allow_inf_nan=False)
    tolerance_tag: str = Field(default='', max_length=200)


class AnalogControl(NumericControl):
    kind: Literal["analog"]
    minimum: float = Field(default=0.0, allow_inf_nan=False)
    maximum: float = Field(default=100.0, allow_inf_nan=False)
    normal_low: float = Field(default=20.0, allow_inf_nan=False)
    normal_high: float = Field(default=80.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_range(self):
        if not math.isfinite(self.maximum - self.minimum) or not self.minimum <= self.normal_low < self.normal_high <= self.maximum:
            raise ValueError("Range must satisfy minimum <= normal low < normal high <= maximum")
        return self


class TankControl(AnalogControl):
    kind: Literal['tank']


class GaugeControl(AnalogControl):
    kind: Literal['gauge']


class ChartSeries(StrictModel):
    tag: str = Field(min_length=1, max_length=200)
    label: str = Field(default='', max_length=100)
    decimals: int = Field(default=1, ge=0, le=4)


class RadarAxis(ChartSeries):
    unit: str = Field(default='', max_length=30)
    minimum: float = Field(default=0, allow_inf_nan=False)
    maximum: float = Field(default=100, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered_range(self):
        if not 0 < self.maximum - self.minimum < math.inf:
            raise ValueError('Radar axis minimum must be less than maximum with a finite span')
        return self


class RadarControl(ControlBase):
    kind: Literal['radar']
    series: list[RadarAxis] = Field(min_length=3, max_length=8)


class BarGraphControl(ControlBase):
    kind: Literal['bar']
    series: list[ChartSeries] = Field(min_length=1, max_length=12)
    unit: str = Field(default='', max_length=30)
    minimum: float = Field(default=0, allow_inf_nan=False)
    maximum: float = Field(default=100, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered_range(self):
        if not 0 < self.maximum - self.minimum < math.inf:
            raise ValueError('Bar graph minimum must be less than maximum with a finite span')
        return self


class PieControl(ControlBase):
    kind: Literal['pie']
    series: list[ChartSeries] = Field(min_length=2, max_length=8)
    unit: str = Field(default='', max_length=30)

    @model_validator(mode='after')
    def distinct_tags(self):
        if len({item.tag for item in self.series}) != len(self.series):
            raise ValueError('Pie slices require distinct tags')
        return self


class XYSeries(StrictModel):
    x_tag: str = Field(min_length=1, max_length=200)
    y_tag: str = Field(min_length=1, max_length=200)
    label: str = Field(default='', max_length=100)


class XYControl(ControlBase):
    kind: Literal['xy']
    series: list[XYSeries] = Field(min_length=1, max_length=8)
    x_minimum: float = Field(default=0.0, allow_inf_nan=False)
    x_maximum: float = Field(default=100.0, allow_inf_nan=False)
    y_minimum: float = Field(default=0.0, allow_inf_nan=False)
    y_maximum: float = Field(default=100.0, allow_inf_nan=False)
    x_unit: str = Field(default='', max_length=30)
    y_unit: str = Field(default='', max_length=30)
    decimals: int = Field(default=1, ge=0, le=4)

    @model_validator(mode='after')
    def ordered_axes(self):
        if not all(0 < span < math.inf for span in (
            self.x_maximum - self.x_minimum, self.y_maximum - self.y_minimum
        )):
            raise ValueError('XY scales require positive finite spans')
        return self


class TrendSeries(StrictModel):
    decimals: int = Field(default=1, ge=0, le=8)
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered_scale(self):
        if self.minimum is None and self.maximum is None:
            return self
        if (self.minimum is None or self.maximum is None or self.minimum >= self.maximum
                or not math.isfinite(self.maximum - self.minimum)):
            raise ValueError('Fixed trend scale requires a finite minimum less than maximum')
        return self


class TrendRecording(StrictModel):
    sample_ms: int = Field(default=250, ge=100, le=60000)
    max_samples: int = Field(default=4000, ge=10, le=20000)
    start_tag: str = Field(default='', max_length=200)
    stop_tag: str = Field(default='', max_length=200)

    @model_validator(mode='after')
    def distinct_triggers(self):
        if self.start_tag and self.start_tag == self.stop_tag:
            raise ValueError('Trend start and stop must use different Boolean tags')
        return self


class TrendControl(ControlBase):
    kind: Literal['trend']
    tags: list[str] = Field(min_length=1, max_length=12)
    seconds: int = Field(default=300, ge=10, le=604800)
    series: dict[str, TrendSeries] = Field(default_factory=dict, max_length=12)
    recording: TrendRecording | None = None

    @model_validator(mode='after')
    def known_series(self):
        if self.series.keys() - set(self.tags):
            raise ValueError('Trend series settings require a selected tag')
        return self
