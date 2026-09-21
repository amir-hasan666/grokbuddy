from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3

from grokbuddy.domain.model import Conflict, NotFound


TABLES = {
    'actors', 'tasks', 'task_events', 'review_requests', 'review_rounds', 'reviews',
    'review_findings', 'finding_events', 'artifacts', 'audit_logs', 'outbox_events',
    'inbox_events', 'processed_events', 'human_approvals', 'approval_events',
    'command_receipts', 'review_profiles', 'mock_jobs', 'github_bindings',
    'github_events', 'github_comment_projections',
    'grok_reviewer_routes', 'worker_assignments', 'intake_receipts',
}
IMMUTABLE = {'actors', 'task_events', 'reviews', 'finding_events', 'artifacts',
             'audit_logs', 'approval_events', 'processed_events', 'command_receipts',
             'review_profiles', 'github_bindings', 'grok_reviewer_routes'}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class SQLiteRepository:
    def __init__(self, connection):
        self.connection = connection

    def _table(self, table):
        if table not in TABLES:
            raise ValueError('Unknown repository collection')
        return table

    def get(self, table, identity):
        row = self.connection.execute(f'SELECT data FROM {self._table(table)} WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise NotFound(f'{table} record not found')
        return json.loads(row[0])

    def find(self, table, **filters):
        clauses, values = [], []
        for key, value in filters.items():
            if not re.fullmatch(r'[a-z_]+', key):
                raise ValueError('Invalid repository field')
            clauses.append(f"json_extract(data, '$.{key}') IS ?")
            values.append(value)
        suffix = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        rows = self.connection.execute(f'SELECT data FROM {self._table(table)}{suffix} ORDER BY rowid', values)
        return [json.loads(row[0]) for row in rows]

    def add(self, table, record):
        self.connection.execute(f'INSERT INTO {self._table(table)}(id,data) VALUES (?,?)',
                                (record['id'], encode(record)))

    def save(self, table, record, expected_version=None):
        query = f'UPDATE {self._table(table)} SET data=? WHERE id=?'
        args = [encode(record), record['id']]
        if expected_version is not None:
            query += " AND json_extract(data, '$.version')=?"
            args.append(expected_version)
        if self.connection.execute(query, args).rowcount != 1:
            raise Conflict('Stale record version')

    def compare_and_swap(self, table, record, expected):
        """Conditionally replace one JSON row, including status and lease fencing fields."""
        if not expected:
            raise ValueError('A compare-and-swap predicate is required')
        clauses, args = [], [encode(record), record['id']]
        for key, value in expected.items():
            if not re.fullmatch(r'[a-z_]+', key):
                raise ValueError('Invalid repository field')
            clauses.append(f"json_extract(data, '$.{key}') IS ?")
            args.append(value)
        query = (f'UPDATE {self._table(table)} SET data=? WHERE id=? AND '
                 + ' AND '.join(clauses))
        if self.connection.execute(query, args).rowcount != 1:
            raise Conflict('Stale record or lease')


class SQLiteDatabase:
    """Short, serialized write transactions. One connection per UoW; safe across threads."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=5000')
        return conn

    def initialize(self):
        with self.connect() as c:
            version = c.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2, 3, 4):
                raise RuntimeError('Unsupported database schema version')
            c.execute('PRAGMA journal_mode=WAL')
            c.execute('PRAGMA synchronous=FULL')
            schema = (Path(__file__).with_name('schema.sql')).read_text(encoding='utf-8')
            existing = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()
            if existing and 'PLAN_HUMAN_REVIEW' not in existing[0]:
                self._migrate_tasks_v4(c, schema)
            c.executescript(schema)
            for table in IMMUTABLE:
                for operation in ('UPDATE', 'DELETE'):
                    c.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only record'); END")
            for table, statuses in (
                ('outbox_events', ('READY','LEASED','RETRY','SENT','FAILED','UNKNOWN','CANCELLED')),
                ('github_comment_projections', ('READY','LEASED','RETRY','SENT','FAILED','UNKNOWN')),
            ):
                allowed = ','.join(f"'{status}'" for status in statuses)
                for operation in ('INSERT', 'UPDATE'):
                    c.execute(f"CREATE TRIGGER IF NOT EXISTS v4_{table}_{operation} BEFORE {operation} ON {table} "
                              f"WHEN json_extract(NEW.data,'$.status') IS NULL "
                              f"OR json_extract(NEW.data,'$.status') NOT IN ({allowed}) "
                              "OR (json_type(NEW.data,'$.lease_generation') IS NOT NULL "
                              "AND (json_type(NEW.data,'$.lease_generation')!='integer' "
                              "OR json_extract(NEW.data,'$.lease_generation')<0)) "
                              "BEGIN SELECT RAISE(ABORT, 'invalid recovery state'); END")
            for operation in ('INSERT', 'UPDATE'):
                c.execute(f"CREATE TRIGGER IF NOT EXISTS v4_worker_assignment_scope_{operation} "
                          f"BEFORE {operation} ON worker_assignments "
                          "WHEN (SELECT task_id FROM artifacts WHERE id=json_extract(NEW.data,'$.approved_plan_artifact_id')) "
                          "IS NOT json_extract(NEW.data,'$.task_id') "
                          "OR (json_extract(NEW.data,'$.completion_artifact_id') IS NOT NULL AND "
                          "(SELECT task_id FROM artifacts WHERE id=json_extract(NEW.data,'$.completion_artifact_id')) "
                          "IS NOT json_extract(NEW.data,'$.task_id')) "
                          "BEGIN SELECT RAISE(ABORT, 'assignment artifact outside task scope'); END")
            c.execute('PRAGMA user_version=4')
        c.close()

    @staticmethod
    def _migrate_tasks_v4(c, schema):
        """Rebuild only the state CHECK; copy opaque JSON bytes without interpretation."""
        definition = re.search(r'^CREATE TABLE IF NOT EXISTS tasks .*?;\s*$', schema, re.M | re.S)
        if definition is None:
            raise RuntimeError('Task schema definition is missing')
        replacement = definition.group().replace('CREATE TABLE IF NOT EXISTS tasks ',
                                                 'CREATE TABLE tasks_v4 ', 1)
        c.execute('PRAGMA foreign_keys=OFF')
        try:
            c.execute('BEGIN IMMEDIATE')
            c.execute(replacement)
            c.execute('INSERT INTO tasks_v4(id,data) SELECT id,data FROM tasks')
            c.execute('DROP TABLE tasks')
            c.execute('ALTER TABLE tasks_v4 RENAME TO tasks')
            # DROP TABLE also removes the two Step 6.1 partial indexes.
            c.execute("CREATE UNIQUE INDEX one_active_conversation_task ON tasks(json_extract(data,'$.conversation_id')) "
                      "WHERE json_extract(data,'$.conversation_id') IS NOT NULL "
                      "AND json_extract(data,'$.state') NOT IN ('DONE','CANCELLED','FAILED')")
            c.execute("CREATE UNIQUE INDEX one_trigger_message_per_conversation ON tasks(" 
                      "json_extract(data,'$.conversation_id'),json_extract(data,'$.trigger_message_id')) "
                      "WHERE json_extract(data,'$.conversation_id') IS NOT NULL "
                      "AND json_extract(data,'$.trigger_message_id') IS NOT NULL")
            if c.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('Foreign-key check failed during v4 Task migration')
            c.execute('COMMIT')
        except BaseException:
            c.execute('ROLLBACK')
            raise
        finally:
            c.execute('PRAGMA foreign_keys=ON')

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield SQLiteRepository(conn)
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise Conflict('Persistence constraint rejected operation') from exc
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def backup_to(self, target):
        """Consistent DB snapshot; artifact contents must be backed up with their manifest."""
        destination = Path(target)
        if destination.exists():
            raise Conflict('Backup destination already exists')
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self.connect()
        dest = sqlite3.connect(destination)
        try:
            source.backup(dest)
        finally:
            source.close()
            dest.close()
