"""Publish completed project files without replacing existing or uncertain data."""

import logging
import os


class PublicationError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def companion_paths(target):
    return (target.with_suffix('.hold'), target.with_suffix('.handlers.py'),
            target.with_suffix('.recipe-users.json'),
            *(target.with_name(target.name + suffix) for suffix in ('-wal', '-shm', '-journal')))


def ensure_available(target):
    if any(os.path.lexists(path) for path in (target, *companion_paths(target))):
        raise PublicationError('Project or support files already exist; choose a new project ID', 409)


def _signature(path):
    info = path.stat(follow_symlinks=False)
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns


def _publish_file(source, target):
    # Staging is on the destination filesystem. Windows rename refuses an
    # existing destination; POSIX link supplies the same no-replace guarantee.
    if os.name == 'nt':
        os.rename(source, target)
    else:
        os.link(source, target)


def _rollback(published):
    retained = False
    for path, signature in reversed(published):
        try:
            if _signature(path) != signature:
                retained = True
                logging.warning('Retained changed project publication artifact: %s', path.name)
                continue
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            retained = True
            logging.exception('Could not roll back project publication artifact: %s', path.name)
    return retained


def publish_project(temporary, target, extras):
    """Stage companions first; publish the fully closed database last."""
    if any(path not in companion_paths(target)[:3] for path in extras):
        raise ValueError('Unsupported project publication companion')
    published = []
    try:
        ensure_available(target)
        staged = []
        for path, content in extras.items():
            source = temporary.parent / path.name
            if source.write_bytes(content) != len(content):
                raise OSError('Incomplete project companion write')
            staged.append((source, path))
        staged.append((temporary, target))
        for source, path in staged:
            signature = _signature(source)
            _publish_file(source, path)
            published.append((path, signature))
    except (OSError, PublicationError) as error:
        # A visible database can mean a competing owner or an uncertain commit.
        # Retain its companions, particularly the PLC hold, rather than guess.
        retained = os.path.lexists(target)
        if retained and published:
            logging.warning('Retained publication companions beside a visible project: %s', target.name)
        if not retained:
            retained = _rollback(published)
        if isinstance(error, PublicationError):
            raise
        suffix = ' Some files were retained; review library files before retrying.' if retained else ' Review the project library before retrying.'
        if isinstance(error, FileExistsError):
            raise PublicationError('Project or support files already exist; choose a new project ID.' + suffix, 409) from error
        logging.exception('Project file publication failed')
        raise PublicationError('Project files could not be published.' + suffix) from error
