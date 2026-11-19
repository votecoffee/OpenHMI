"""Compatibility request contracts for attributed alarm acknowledgement."""

from pydantic import ConfigDict, Field, model_validator
from .control_contracts import ActionRequest


class AcknowledgeRequest(ActionRequest):
    model_config = ConfigDict(extra='forbid', strict=True)
    comment: str = Field(default='', max_length=1000)


class SelectedAcknowledgement(AcknowledgeRequest):
    occurrence_ids: list[int] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def valid_ids(self):
        if len(set(self.occurrence_ids)) != len(self.occurrence_ids) or any(not 1 <= identifier <= 9223372036854775807 for identifier in self.occurrence_ids):
            raise ValueError('Select 1–200 unique valid occurrence IDs')
        return self
