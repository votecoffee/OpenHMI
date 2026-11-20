"""Strict saved-trend action request contract."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class CaptureCommand(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['start', 'stop', 'delete']
    capture_id: int = Field(default=0, ge=0, le=9223372036854775807)
