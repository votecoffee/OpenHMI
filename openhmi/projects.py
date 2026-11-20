"""Transactional SQLite project revisions, recovery, staging and merge persistence."""
import json
import sqlite3
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from .project_diff import encoded, digest, same, differences, merge_project, SCREEN_FIELDS

# Compatibility exports: schema consumers can import project_models directly.
from .project_models import (
    MAX_PLC_CONNECTIONS, Connection, TagDefinition, HistorianSettings, CommandDefinition,
    RecipeTransferDefinition, IdentityPublication, CanvasLayout, MAX_UTC_EPOCH, StrictModel,
    ControlBase, StateCode, MachineState, StateControl, MultiStateControl, ModeSelectorControl,
    PermissiveRow, PermissiveControl, StackLamp, StackLightControl, BitfieldBit, BitfieldControl,
    NumericControl, LedDisplayControl, TagQualityControl, ConnectionStatusControl,
    StaticImageControl, StateImageControl, ImageState, MultiStateImageControl, LabelControl,
    SymbolControl, SparklineControl, DateTimeDisplayControl, DurationDisplayControl,
    TextDisplayControl, IndicatorControl, ProgressControl, MotionImageControl, PositionImageControl,
    RotationImageControl, SetpointComparisonControl, AnalogControl, TankControl, GaugeControl,
    ChartSeries, RadarAxis, RadarControl, BarGraphControl, PieControl, XYSeries, XYControl,
    AlarmControl, ButtonControl, NumericInputControl, NumericStepperControl, DateTimeControl,
    RecipeSelectionControl, TextInputControl, ChoiceOption, ChoiceInputControl, BooleanInputControl,
    CurrentUserControl, FaceplateControl, TrendSeries, TrendRecording, TrendControl, Language,
    AlarmDefinition, WebBrowserControl, Control, Screen, FaceplateDefinition, Project,
    RevisionRequest, SaveRequest, ApplyRequest, StageRequest, RecoveryRequest, MergePreview,
    MergeRequest, default_project,
)


class RevisionConflict(Exception):
    pass


class ProjectStore:
    def __init__(self, path: Path | None = None, *, initial_project: Project | None = None):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        try:
            tables = {row[0] for row in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and 'project' not in tables:
                raise ValueError('Database is not an OpenHMI project; no migration was performed')
            existing = 'project' in tables
            if existing:
                if initial_project is not None:
                    raise ValueError('Initial project settings cannot replace an existing project')
                state = self._read()
                Project.model_validate(state['draft'])
                Project.model_validate(state['active'])
                for key in ('draft_revision', 'active_revision'):
                    if type(state[key]) is not int or not 1 <= state[key] <= 9223372036854775807:
                        raise ValueError('Invalid project revision counters')
            else:
                initial = (initial_project or default_project()).model_dump()
                state = {'draft_revision': 1, 'active_revision': 1, 'draft': initial, 'active': initial}
            if 'project_storage' in tables:
                version = self._db.execute('SELECT version FROM project_storage WHERE id=1').fetchone()
                if version != (1,):
                    raise ValueError('Unsupported OpenHMI project storage version; no migration was performed')
                if not {'project_revision', 'project_recovery'} <= tables:
                    raise ValueError('Project history storage is incomplete')
                identifier = self._db.execute('SELECT project_id FROM project_storage WHERE id=1').fetchone()[0]
                if not isinstance(identifier, str) or len(identifier) != 32 or any(part not in '0123456789abcdef' for part in identifier):
                    raise ValueError('Project storage identity is invalid')
                current = self.revision(state['active_revision'])
                if not same(current['project'], Project.model_validate(state['active']).model_dump()):
                    raise ValueError('Active project does not match its recorded revision')
            else:
                if {'project_revision', 'project_recovery'} & tables:
                    raise ValueError('Unversioned project history storage is incomplete')
                with self.transaction() as db:
                    db.execute("CREATE TABLE IF NOT EXISTS project(id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL)")
                    db.execute('INSERT OR IGNORE INTO project VALUES(1,?)', (encoded(state),))
                    db.execute('CREATE TABLE project_storage(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL,project_id TEXT NOT NULL)')
                    db.execute('INSERT INTO project_storage VALUES(1,1,?)', (uuid.uuid4().hex,))
                    db.execute('CREATE TABLE project_revision(revision INTEGER PRIMARY KEY,timestamp TEXT NOT NULL,actor TEXT NOT NULL,provider TEXT NOT NULL,reason TEXT NOT NULL,source_revision INTEGER,project_json TEXT NOT NULL,content_hash TEXT NOT NULL,baseline INTEGER NOT NULL)')
                    db.execute('CREATE TABLE project_recovery(id TEXT PRIMARY KEY,timestamp TEXT NOT NULL,actor TEXT NOT NULL,provider TEXT NOT NULL,reason TEXT NOT NULL,base_revision INTEGER NOT NULL,base_json TEXT NOT NULL,local_json TEXT NOT NULL,base_hash TEXT NOT NULL,local_hash TEXT NOT NULL)')
                    self._record(db, state, ('unknown', 'legacy') if existing else ('system', 'system'),
                                 'Existing active project captured during history migration; earlier revisions are unavailable' if existing else 'Initial project', baseline=True)
        except Exception:
            self._db.close()
            raise

    @staticmethod
    def stamp():
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

    def _read(self) -> dict:
        row = self._db.execute('SELECT state FROM project WHERE id=1').fetchone()
        if not row:
            raise ValueError('Project state is missing')
        return json.loads(row[0])

    def snapshot(self) -> dict:
        with self._lock:
            return {**self._read(), 'project_id': self._db.execute('SELECT project_id FROM project_storage WHERE id=1').fetchone()[0]}

    def fork_identity(self):
        with self.transaction() as db:
            db.execute('UPDATE project_storage SET project_id=? WHERE id=1', (uuid.uuid4().hex,))

    @contextmanager
    def transaction(self):
        with self._lock, self._db:
            self._db.execute('BEGIN IMMEDIATE')
            yield self._db

    def _record(self, db, state, identity, reason, source=None, baseline=False):
        project = Project.model_validate(state['active']).model_dump()
        db.execute('INSERT INTO project_revision VALUES(?,?,?,?,?,?,?,?,?)',
                   (state['active_revision'], self.stamp(), *identity, reason, source, encoded(project), digest(project), int(baseline)))

    def revision(self, identifier):
        with self._lock:
            cursor = self._db.execute('SELECT * FROM project_revision WHERE revision=?', (identifier,))
            row = cursor.fetchone()
        if not row:
            raise KeyError('Applied project revision not found')
        item = dict(zip([column[0] for column in cursor.description], row))
        project = json.loads(item.pop('project_json'))
        if digest(project) != item['content_hash']:
            raise ValueError('Project revision integrity check failed')
        item['project'] = Project.model_validate(project).model_dump()
        item['baseline'] = bool(item['baseline'])
        return item

    def revisions(self, limit=50, before=None):
        with self._lock:
            ids = [row[0] for row in self._db.execute('SELECT revision FROM project_revision WHERE revision < ? ORDER BY revision DESC LIMIT ?',
                                                    (before or 9223372036854775807, limit + 1))]
            state = self._read()
        return {'items': [{key: value for key, value in self.revision(identifier).items() if key != 'project'} for identifier in ids[:limit]],
                'has_more': len(ids) > limit, 'next_before_revision': ids[limit - 1] if len(ids) > limit else None,
                'active_revision': state['active_revision'], 'draft_revision': state['draft_revision'], 'storage_version': 1}

    def verify_history(self):
        with self._lock:
            for (identifier,) in self._db.execute('SELECT revision FROM project_revision'):
                self.revision(identifier)
            for (identifier,) in self._db.execute('SELECT id FROM project_recovery'):
                self.recovery(identifier)

    @staticmethod
    def check_revision(state, expected):
        if expected != state['draft_revision']:
            raise RevisionConflict('Draft changed in another editor. Review and merge your local changes before saving or applying.')
        if state['draft_revision'] >= 9223372036854775807 or state['active_revision'] >= 9223372036854775807:
            raise ValueError('Project revision counter exhausted')

    def _update(self, expected_revision, project, validator=None, identity=('system', 'system'), reason='Live apply'):
        with self.transaction() as db:
            state = self._read()
            self.check_revision(state, expected_revision)
            if project is None:
                if validator:
                    validator(Project.model_validate(state['draft']))
                origin = state.get('draft_origin')
                if not same(state['active'], state['draft']) or origin:
                    state['active'] = state['draft']
                    state['active_revision'] += 1
                    self._record(db, state, identity, origin['reason'] if origin and reason == 'Live apply' else reason,
                                 origin['source_revision'] if origin else None)
                    state.pop('draft_origin', None)
            elif not same(state['draft'], project.model_dump()):
                state['draft'] = project.model_dump()
                state['draft_revision'] += 1
            db.execute('UPDATE project SET state=? WHERE id=1', (encoded(state),))
            return state

    def save(self, request):
        return self._update(request.expected_revision, request.project)

    def apply(self, request, validator=None, identity=('system', 'system')):
        return self._update(request.expected_revision, None, validator, identity, getattr(request, 'reason', 'Live apply'))

    def _recover(self, db, base, local, base_revision, reason, identity):
        identifier = uuid.uuid4().hex
        db.execute('INSERT INTO project_recovery VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (identifier, self.stamp(), *identity, reason, base_revision, encoded(base), encoded(local), digest(base), digest(local)))
        return identifier

    def recover(self, request, identity):
        with self.transaction() as db:
            identifier = self._recover(db, request.base.model_dump(), request.local.model_dump(), request.base_revision, request.reason, identity)
        return self.recovery(identifier)

    def recovery(self, identifier):
        with self._lock:
            cursor = self._db.execute('SELECT * FROM project_recovery WHERE id=?', (identifier,))
            row = cursor.fetchone()
        if not row:
            raise KeyError('Project recovery copy not found')
        item = dict(zip([column[0] for column in cursor.description], row))
        for name in ('base', 'local'):
            project = json.loads(item.pop(name + '_json'))
            if digest(project) != item[name + '_hash']:
                raise ValueError('Project recovery integrity check failed')
            item[name] = Project.model_validate(project).model_dump()
        return item

    def recoveries(self, limit=50, before=None):
        with self._lock:
            if before:
                cursor = self._db.execute('SELECT timestamp,id FROM project_recovery WHERE id=?', (before,)).fetchone()
                if not cursor:
                    raise KeyError('Project recovery cursor not found')
                rows = self._db.execute('SELECT id,timestamp FROM project_recovery WHERE (timestamp,id) < (?,?) ORDER BY timestamp DESC,id DESC LIMIT ?', (*cursor, limit + 1)).fetchall()
            else:
                rows = self._db.execute('SELECT id,timestamp FROM project_recovery ORDER BY timestamp DESC,id DESC LIMIT ?', (limit + 1,)).fetchall()
        return {'items': [{key: value for key, value in self.recovery(identifier).items() if key not in ('base', 'local')} for identifier, _ in rows[:limit]],
                'has_more': len(rows) > limit, 'next_before_id': rows[limit - 1][0] if len(rows) > limit else None}

    def stage(self, identifier, request, validator, identity):
        with self.transaction() as db:
            state = self._read()
            self.check_revision(state, request.expected_revision)
            historical = self.revision(identifier)['project']
            target = deepcopy(state['draft']) if request.scope == 'screens' else historical
            if request.scope == 'screens':
                for field in SCREEN_FIELDS:
                    target[field] = deepcopy(historical[field])
            project = Project.model_validate(target)
            validator(project)
            recovery = self._recover(db, state['draft'], state['draft'], state['draft_revision'], 'Server draft before staging revision ' + str(identifier), identity)
            state['draft'] = project.model_dump()
            state['draft_revision'] += 1
            state['draft_origin'] = {'source_revision': identifier, 'scope': request.scope, 'reason': request.reason}
            db.execute('UPDATE project SET state=? WHERE id=1', (encoded(state),))
        return {**state, 'preserved_recovery_id': recovery}

    def merge(self, request, validator, identity):
        with self.transaction() as db:
            state = self._read()
            self.check_revision(state, request.expected_revision)
            result = merge_project(request.base.model_dump(), request.local.model_dump(), Project.model_validate(state['draft']).model_dump(), request.choices)
            if not result['complete']:
                raise RevisionConflict('Choose local or current for every overlapping change before merging')
            project = Project.model_validate(result['project'])
            validator(project)
            recovery = self._recover(db, state['draft'], state['draft'], state['draft_revision'], 'Server draft before merge: ' + request.reason, identity)
            self._recover(db, request.base.model_dump(), request.local.model_dump(), request.base_revision, 'Local candidate before merge: ' + request.reason, identity)
            state['draft'] = project.model_dump()
            state['draft_revision'] += 1
            db.execute('UPDATE project SET state=? WHERE id=1', (encoded(state),))
        return {**state, 'preserved_recovery_id': recovery}

    def close(self):
        with self._lock:
            self._db.close()
