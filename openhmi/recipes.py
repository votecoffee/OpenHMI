"""SQL recipe revisions, recorded approvals, policy and loaded-copy snapshots."""

import hashlib
from io import BytesIO
import json
import sqlite3

from PIL import Image, ImageOps, UnidentifiedImageError
from .alarms import utc_now
from .recipe_models import RecipePolicy


class RecipeError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def content_hash(content):
    return hashlib.sha256(canonical(content).encode('utf-8')).hexdigest()


def differences(before, after):
    def flatten(content):
        result = {key: content.get(key) for key in ('title', 'description', 'image_id')}
        for parameter in content.get('parameters', []):
            for key, value in parameter.items():
                result[f'parameters.{parameter["name"]}.{key}'] = value
        return result
    old, new = flatten(before), flatten(after)
    return [{'field': key, 'before': old.get(key), 'after': new.get(key)} for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)]


def rows(cursor):
    names = [entry[0] for entry in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


class RecipeService:
    def __init__(self, store, application):
        self.store, self.application = store, application
        with store.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS recipe_entry (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS recipe_revision (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id INTEGER NOT NULL, number INTEGER NOT NULL,
                    status TEXT NOT NULL, version INTEGER NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL,
                    author TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL, parent_revision INTEGER,
                    approved_by TEXT, approved_at TEXT, approval_comment TEXT,
                    UNIQUE(recipe_id,number), FOREIGN KEY(recipe_id) REFERENCES recipe_entry(id));
                CREATE TABLE IF NOT EXISTS recipe_image (id TEXT PRIMARY KEY, png BLOB NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS recipe_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                    actor TEXT NOT NULL, operation TEXT NOT NULL, recipe_id INTEGER, revision_id INTEGER, details TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS recipe_policy (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS recipe_selection (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, snapshot TEXT);
            ''')
            db.execute('INSERT OR IGNORE INTO recipe_policy VALUES(1,1,?)', (canonical(RecipePolicy().model_dump()),))
            db.execute('INSERT OR IGNORE INTO recipe_selection VALUES(1,1,NULL)')
        with self.store._lock:
            selected = self._selection(self.store._db)
        application.driver.load_recipe(selected['snapshot'])

    @staticmethod
    def _audit(db, user, operation, recipe_id=None, revision_id=None, **details):
        db.execute('INSERT INTO recipe_audit(timestamp,actor,operation,recipe_id,revision_id,details) VALUES(?,?,?,?,?,?)',
                   (utc_now(), user.name, operation, recipe_id, revision_id, canonical(details)))

    @staticmethod
    def _policy(db):
        version, content = db.execute('SELECT version,content FROM recipe_policy WHERE id=1').fetchone()
        return {'version': version, 'policy': json.loads(content)}

    @staticmethod
    def _selection(db):
        version, snapshot = db.execute('SELECT version,snapshot FROM recipe_selection WHERE id=1').fetchone()
        return {'version': version, 'snapshot': json.loads(snapshot) if snapshot else None}

    def _gate(self, db, user, operation):
        roles = {'editing': ('engineer',), 'approval': ('approver',), 'loading': ('engineer', 'operator')}
        if not user or not any(user.permits(role) for role in roles[operation]):
            raise RecipeError(f'Recipe {operation} role is required', 403)
        policy = self._policy(db)['policy']
        if not policy[f'{operation}_enabled']:
            raise RecipeError(f'Recipe {operation} is disabled by change policy', 423)
        tag = policy[f'{operation}_permit_tag']
        if tag:
            try:
                value = self.application.driver.read(tag)[0]
            except Exception as error:
                raise RecipeError(f'Recipe permit unavailable: {tag}', 423) from error
            if type(value) is not bool or value is not True:
                raise RecipeError(f'Recipe permit is not true: {tag}', 423)

    @staticmethod
    def _revision(db, identifier):
        result = rows(db.execute('SELECT r.*, e.code FROM recipe_revision r JOIN recipe_entry e ON e.id=r.recipe_id WHERE r.id=?', (identifier,)))
        if not result:
            raise RecipeError('Recipe revision not found', 404)
        revision = result[0]
        revision['content'] = json.loads(revision['content'])
        if content_hash(revision['content']) != revision['content_hash']:
            raise RecipeError('Recipe content integrity check failed')
        return revision

    @staticmethod
    def _image_exists(db, content):
        if content.image_id and not db.execute('SELECT 1 FROM recipe_image WHERE id=?', (content.image_id,)).fetchone():
            raise RecipeError('Recipe image not found', 422)

    def create(self, request, user):
        with self.application.lock, self.store.transaction() as db:
            self._gate(db, user, 'editing')
            self._image_exists(db, request.content)
            try:
                entry = db.execute('INSERT INTO recipe_entry(code) VALUES(?)', (request.code,)).lastrowid
            except sqlite3.IntegrityError as error:
                raise RecipeError('Recipe code already exists') from error
            return self._insert(db, entry, 1, request.content, request.reason, user, None, {})

    def _insert(self, db, recipe_id, number, content, reason, user, parent, before):
        payload = content.model_dump()
        identifier = db.execute('''INSERT INTO recipe_revision(recipe_id,number,status,version,content,content_hash,author,reason,created_at,parent_revision)
                                   VALUES(?,?,'draft',1,?,?,?,?,?,?)''',
                                (recipe_id, number, canonical(payload), content_hash(payload), user.name, reason, utc_now(), parent)).lastrowid
        self._audit(db, user, 'created' if number == 1 else 'content_saved', recipe_id, identifier,
                    reason=reason, parent_revision=parent, content_hash=content_hash(payload), changes=differences(before, payload))
        return self._revision(db, identifier)

    def save(self, recipe_id, request, user):
        with self.application.lock, self.store.transaction() as db:
            self._gate(db, user, 'editing')
            latest = db.execute('SELECT id,status FROM recipe_revision WHERE recipe_id=? ORDER BY number DESC LIMIT 1', (recipe_id,)).fetchone()
            if not latest:
                raise RecipeError('Recipe not found', 404)
            if latest[0] != request.expected_latest_revision:
                raise RecipeError('Recipe changed in another editor; reload before saving')
            if latest[1] == 'in_review':
                raise RecipeError('Recipe is in review; finish the review before saving another revision')
            parent = self._revision(db, request.parent_revision)
            if parent['recipe_id'] != recipe_id:
                raise RecipeError('Parent revision belongs to another recipe', 422)
            self._image_exists(db, request.content)
            if latest[1] == 'draft':
                db.execute("UPDATE recipe_revision SET status='superseded',version=version+1 WHERE id=?", (latest[0],))
            number = db.execute('SELECT MAX(number)+1 FROM recipe_revision WHERE recipe_id=?', (recipe_id,)).fetchone()[0]
            return self._insert(db, recipe_id, number, request.content, request.reason, user, parent['id'], parent['content'])

    def transition(self, identifier, request, user):
        with self.application.lock, self.store.transaction() as db:
            self._gate(db, user, 'editing' if request.action == 'submit' else 'approval')
            revision = self._revision(db, identifier)
            if request.expected_version != revision['version']:
                raise RecipeError('Recipe review state changed; reload before continuing')
            required = {'submit': 'draft', 'approve': 'in_review', 'reject': 'in_review', 'withdraw': 'approved'}
            if revision['status'] != required[request.action]:
                raise RecipeError(f'Cannot {request.action} a {revision["status"]} revision')
            target = {'submit': 'in_review', 'approve': 'approved', 'reject': 'rejected', 'withdraw': 'withdrawn'}[request.action]
            if request.action == 'approve':
                db.execute('UPDATE recipe_revision SET status=?,version=version+1,approved_by=?,approved_at=?,approval_comment=? WHERE id=?',
                           (target, user.name, utc_now(), request.reason, identifier))
            else:
                db.execute('UPDATE recipe_revision SET status=?,version=version+1 WHERE id=?', (target, identifier))
            self._audit(db, user, request.action, revision['recipe_id'], identifier, reason=request.reason,
                        before=revision['status'], after=target, content_hash=revision['content_hash'])
            return self._revision(db, identifier)

    def select(self, request, user):
        with self.application.lock:
            with self.store.transaction() as db:
                self._gate(db, user, 'loading')
                selected = self._selection(db)
                if request.expected_selection_version != selected['version']:
                    raise RecipeError('Loaded recipe changed; reload before loading another copy')
                snapshot = None
                if request.revision_id is not None:
                    revision = self._revision(db, request.revision_id)
                    if request.expected_revision_version != revision['version']:
                        raise RecipeError('Recipe review state changed; reload before loading')
                    snapshot = {**revision, 'production_approved': revision['status'] == 'approved', 'loaded_by': user.name, 'loaded_at': utc_now(), 'load_reason': request.reason}
                db.execute('UPDATE recipe_selection SET version=version+1,snapshot=? WHERE id=1', (canonical(snapshot) if snapshot else None,))
                self._audit(db, user, 'loaded' if snapshot else 'load_cleared', snapshot['recipe_id'] if snapshot else None,
                            request.revision_id, reason=request.reason, before=selected['snapshot'], after=snapshot)
                result = self._selection(db)
            # Keep concurrent loads ordered through the simulated copy publication.
            self.application.driver.load_recipe(result['snapshot'])
            return result

    def update_policy(self, request, user):
        if not user or not user.permits('administrator'):
            raise RecipeError('Recipe administrator role is required', 403)
        with self.application.lock, self.store.transaction() as db:
            previous = self._policy(db)
            if request.expected_version != previous['version']:
                raise RecipeError('Recipe policy changed; reload before updating')
            for tag in [request.policy.editing_permit_tag, request.policy.approval_permit_tag, request.policy.loading_permit_tag]:
                if tag:
                    try:
                        valid = type(self.application.driver.read(tag)[0]) is bool
                    except Exception:
                        valid = False
                    if not valid:
                        raise RecipeError(f'Policy permit requires an existing Boolean tag: {tag}', 422)
            db.execute('UPDATE recipe_policy SET version=version+1,content=? WHERE id=1', (canonical(request.policy.model_dump()),))
            self._audit(db, user, 'policy_changed', reason=request.reason, before=previous['policy'], after=request.policy.model_dump())
            return self._policy(db)

    def image(self, identifier):
        with self.store._lock:
            row = self.store._db.execute('SELECT png FROM recipe_image WHERE id=?', (identifier,)).fetchone()
            if not row:
                raise RecipeError('Recipe image not found', 404)
            return row[0]

    def selected(self):
        with self.application.lock, self.store._lock:
            return self._selection(self.store._db)

    def add_image(self, data, reason, user):
        try:
            with Image.open(BytesIO(data)) as image:
                if image.format not in ('PNG', 'JPEG') or image.width > 4096 or image.height > 4096:
                    raise RecipeError('Use a PNG/JPEG image no larger than 4096 by 4096 pixels', 422)
                image.verify()
            with Image.open(BytesIO(data)) as image:
                normalized = ImageOps.exif_transpose(image).convert('RGBA' if image.mode in ('RGBA', 'LA', 'P') else 'RGB')
                normalized.info.clear()
                output = BytesIO()
                normalized.save(output, format='PNG')
                png, width, height = output.getvalue(), normalized.width, normalized.height
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
            raise RecipeError('Invalid recipe image', 422) from error
        if len(png) > 8 * 1024 * 1024:
            raise RecipeError('Normalized recipe image exceeds 8 MiB', 413)
        identifier = hashlib.sha256(png).hexdigest()
        with self.application.lock, self.store.transaction() as db:
            self._gate(db, user, 'editing')
            db.execute('INSERT OR IGNORE INTO recipe_image VALUES(?,?,?,?)', (identifier, png, width, height))
            self._audit(db, user, 'image_uploaded', reason=reason, image_id=identifier, width=width, height=height)
        return {'image_id': identifier, 'width': width, 'height': height}

    def simulator_permit(self, request, user):
        if not user or not user.permits('administrator'):
            raise RecipeError('Recipe administrator role is required', 403)
        with self.application.lock, self.store.transaction() as db:
            from .drivers import SimulatorDriver
            if not isinstance(self.application.driver, SimulatorDriver):
                raise RecipeError('This action is available only with the simulator')
            before = self.application.driver.read('RecipeChangeAllowed')[0]
            self.application.driver.write('RecipeChangeAllowed', [request.allowed])
            self._audit(db, user, 'simulator_permit', reason=request.reason, before=before, after=request.allowed)
        return {'allowed': request.allowed}

    def snapshot(self):
        with self.application.lock, self.store._lock:
            db = self.store._db
            revisions = rows(db.execute('SELECT r.*,e.code FROM recipe_revision r JOIN recipe_entry e ON e.id=r.recipe_id ORDER BY r.id DESC'))
            for revision in revisions:
                revision['content'] = json.loads(revision['content'])
            audit = rows(db.execute('SELECT * FROM recipe_audit ORDER BY id DESC'))
            for event in audit:
                event['details'] = json.loads(event['details'])
            policy = self._policy(db)
            gates = {}
            for operation in ('editing', 'approval', 'loading'):
                enabled = policy['policy'][f'{operation}_enabled']
                tag = policy['policy'][f'{operation}_permit_tag']
                try:
                    value = self.application.driver.read(tag)[0] if tag else True
                except Exception:
                    value = None
                gates[operation] = {'allowed': enabled and type(value) is bool and value, 'permit_tag': tag, 'permit_value': value}
            return {'revisions': revisions, 'selection': self._selection(db), 'change_policy': policy, 'gates': gates, 'audit': audit}
