"""Bounded project-library metadata inventory; never reads contents or follows links."""
import os
import stat
from typing import Literal
from pydantic import Field, model_validator
from .project_models import StrictModel

MAX_SCANNED_ENTRIES = 10000
MAX_SAFE_SIZE = 9007199254740991
NAME_PATTERN = r'^[^/\\\x00]+$'
RULES = (
    ('.openhmi.hold', 'connection_hold'),
    ('.openhmi.handlers.py', 'python_review'),
    ('.openhmi.recipe-users.json', 'recipe_accounts'),
    ('.openhmi.sqlite3-wal', 'sqlite_wal'),
    ('.openhmi.sqlite3-shm', 'sqlite_shm'),
    ('.openhmi.sqlite3-journal', 'sqlite_journal'),
)
EntryType = Literal['file', 'directory', 'link', 'other', 'unavailable']
ArtifactKind = Literal['connection_hold', 'python_review', 'recipe_accounts', 'sqlite_wal', 'sqlite_shm', 'sqlite_journal']


def artifact_identity(name):
    for suffix, kind in RULES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)] + '.openhmi.sqlite3', kind
    return None


class ArtifactQuery(StrictModel):
    limit: int = Field(default=50, ge=1, le=100, strict=False)
    after: str = Field(default='', max_length=255, pattern=r'^[^/\\\x00]*$')


class LibraryArtifact(StrictModel):
    file: str = Field(min_length=1, max_length=255, pattern=NAME_PATTERN)
    project_file: str = Field(min_length=1, max_length=512, pattern=NAME_PATTERN)
    kind: ArtifactKind
    entry_type: EntryType
    project_entry_type: Literal['file', 'directory', 'link', 'other', 'unavailable', 'missing']
    size_bytes: int | None = Field(default=None, ge=0, le=MAX_SAFE_SIZE)

    @model_validator(mode='after')
    def coherent(self):
        if artifact_identity(self.file) != (self.project_file, self.kind):
            raise ValueError('Artifact identity does not match its filename')
        if self.entry_type != 'file' and self.size_bytes is not None:
            raise ValueError('Only regular files have byte sizes')
        return self


class ArtifactPage(StrictModel):
    items: list[LibraryArtifact] = Field(max_length=100)
    next_after: str | None = Field(default=None, min_length=1, max_length=255, pattern=NAME_PATTERN)
    scan_limited: bool

    @model_validator(mode='after')
    def coherent(self):
        names = [item.file for item in self.items]
        if names != sorted(set(names)):
            raise ValueError('Artifact filenames must be unique and ordered')
        if self.next_after is not None and (not names or self.next_after != names[-1]):
            raise ValueError('Artifact cursor must match the last filename')
        return self


class InventoryUnavailable(Exception):
    pass


def entry_metadata(path, *, missing='unavailable'):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return missing, None
    except OSError:
        return 'unavailable', None
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
        return 'link', None
    if stat.S_ISREG(info.st_mode):
        return 'file', info.st_size if 0 <= info.st_size <= MAX_SAFE_SIZE else None
    return ('directory' if stat.S_ISDIR(info.st_mode) else 'other'), None


def inventory(root, query):
    names, limited = [], False
    try:
        with os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_SCANNED_ENTRIES:
                    limited = True
                    break
                if entry.name > query.after and artifact_identity(entry.name):
                    try:
                        entry.name.encode('utf-8')
                    except UnicodeError:
                        limited = True
                        continue
                    names.append(entry.name)
    except OSError as error:
        raise InventoryUnavailable('Project file inventory is unavailable; review server logs and retry.') from error
    names.sort()
    items = []
    for name in names[:query.limit]:
        project_file, kind = artifact_identity(name)
        entry_type, size = entry_metadata(root / name)
        project_type, _ = entry_metadata(root / project_file, missing='missing')
        items.append(LibraryArtifact(file=name, project_file=project_file, kind=kind,
                                     entry_type=entry_type, project_entry_type=project_type, size_bytes=size))
    return ArtifactPage(items=items, next_after=items[-1].file if len(names) > query.limit else None,
                        scan_limited=limited).model_dump()
