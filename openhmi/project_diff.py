"""Identity-aware project comparison and explicit three-way conflict resolution."""

from copy import deepcopy
import hashlib
import json

ABSENT = object()
COLLECTION_KEYS = {'controls': 'id', 'screens': 'id', 'faceplates': 'id', 'connections': 'id',
                   'commands': 'id', 'recipe_transfers': 'id', 'alarms': 'id', 'tags': 'name', 'languages': 'code'}
SCREEN_FIELDS = ('title', 'columns', 'controls', 'update_ms', 'screens', 'faceplates', 'languages', 'default_language')


def encoded(project):
    return json.dumps(project, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(project):
    return hashlib.sha256(encoded(project).encode('utf-8')).hexdigest()


def same(first, second):
    if first is ABSENT or second is ABSENT:
        return first is second
    return encoded(first) == encoded(second)


def pointer(path):
    return '/' + '/'.join(str(part).replace('~', '~0').replace('/', '~1') for part in path)


def shown(value):
    return {'exists': False} if value is ABSENT else {'exists': True, 'value': value}


def collection(path, values):
    key = ('tag' if path == ('historian', 'tags') else COLLECTION_KEYS.get(path[0]) if len(path) == 1 else
           'id' if len(path) == 3 and path[0] in ('screens', 'faceplates') and path[2] == 'controls' else None)
    if key and all(isinstance(value, list) and all(isinstance(item, dict) and key in item for item in value)
                   and len({item[key] for item in value}) == len(value) for value in values):
        return key
    return None


def differences(before, after, path=()):
    if same(before, after):
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return [change for key in sorted(before.keys() | after.keys())
                for change in differences(before.get(key, ABSENT), after.get(key, ABSENT), (*path, key))]
    key = collection(path, (before, after))
    if key:
        old, new = ({item[key]: item for item in value} for value in (before, after))
        changes = [change for name in sorted(old.keys() | new.keys())
                   for change in differences(old.get(name, ABSENT), new.get(name, ABSENT), (*path, '@' + name))]
        if list(old) != list(new):
            changes.append({'path': pointer((*path, '@order')), 'before': shown(list(old)), 'after': shown(list(new))})
        return changes
    return [{'path': pointer(path), 'before': shown(before), 'after': shown(after)}]


def merge_project(base, local, current, choices=None):
    choices = choices or {}
    conflicts = []

    def clone(value):
        return value if value is ABSENT else deepcopy(value)

    def conflict(path, original, mine, theirs):
        location = pointer(path)
        selected = choices.get(location)
        conflicts.append({'path': location, 'base': shown(original), 'local': shown(mine),
                          'current': shown(theirs), 'choice': selected})
        return clone(mine if selected == 'local' else theirs)

    def combine(original, mine, theirs, path=()):
        if same(mine, theirs):
            return clone(mine)
        if same(mine, original):
            return clone(theirs)
        if same(theirs, original):
            return clone(mine)
        if all(isinstance(value, dict) for value in (original, mine, theirs)):
            result = {}
            for name in sorted(original.keys() | mine.keys() | theirs.keys()):
                value = combine(original.get(name, ABSENT), mine.get(name, ABSENT), theirs.get(name, ABSENT), (*path, name))
                if value is not ABSENT:
                    result[name] = value
            return result
        key = collection(path, (original, mine, theirs))
        if key:
            old, own, latest = ({item[key]: item for item in value} for value in (original, mine, theirs))
            result = {}
            for name in sorted(old.keys() | own.keys() | latest.keys()):
                value = combine(old.get(name, ABSENT), own.get(name, ABSENT), latest.get(name, ABSENT), (*path, '@' + name))
                if value is not ABSENT:
                    result[name] = value
            orders = [list(value) for value in (old, own, latest)]
            order = combine(*orders, (*path, '@order'))
            # A chosen order never silently discards another editor's retained additions.
            order = list(dict.fromkeys([*order, *orders[2], *orders[1]]))
            return [result[name] for name in order if name in result]
        return conflict(path, original, mine, theirs)

    project = combine(base, local, current)
    unknown = set(choices) - {item['path'] for item in conflicts}
    if unknown:
        raise ValueError('Conflict choices do not match this comparison; preview again')
    return {'project': project, 'conflicts': conflicts, 'complete': all(item['choice'] in ('local', 'current') for item in conflicts),
            'changes': differences(current, project)}
