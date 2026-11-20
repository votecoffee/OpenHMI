"""Station ownership request contract for identity publication."""
from pydantic import Field
from .runtime_models import Model


class StationClaim(Model):
    client: str = Field(min_length=1, max_length=100)
