"""Canonical project-library snapshots and operation acknowledgements."""
from pydantic import Field, model_validator
from .project_models import StrictModel

FILENAME = r'^[^/\\\x00]+$'
CREATED_FILE = r'^[A-Za-z][A-Za-z0-9_-]{0,59}\.openhmi\.sqlite3$'


class LibraryProject(StrictModel):
    file: str = Field(min_length=1, max_length=255, pattern=FILENAME)
    current: bool


class LibrarySnapshot(StrictModel):
    current: str = Field(min_length=1, max_length=255, pattern=FILENAME)
    projects: list[LibraryProject] = Field(min_length=1)
    handlers: bool
    plc_hold: bool

    @model_validator(mode='after')
    def coherent(self):
        names = [project.file for project in self.projects]
        if len(set(names)) != len(names):
            raise ValueError('Project filenames must be unique')
        active = [project.file for project in self.projects if project.current]
        if active != [self.current]:
            raise ValueError('Exactly the named current project must be marked open')
        return self


class CreatedProject(StrictModel):
    file: str = Field(pattern=CREATED_FILE)


class ImportedProject(CreatedProject):
    handlers_saved_for_review: bool
    plc_hold: bool

    @model_validator(mode='after')
    def held(self):
        if not self.plc_hold:
            raise ValueError('Imported connections must be held')
        return self


class OpenedProject(StrictModel):
    ok: bool
    current: str = Field(min_length=1, max_length=255, pattern=FILENAME)

    @model_validator(mode='after')
    def confirmed(self):
        if not self.ok:
            raise ValueError('Project open must be confirmed')
        return self
