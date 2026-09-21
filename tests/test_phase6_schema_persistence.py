"""Step 6.2 persistence probes against disposable SQLite databases only."""

import json
import sqlite3
from uuid import uuid4

import pytest

from conftest import CONTRACTS, Flow
from grokbuddy.adapters.sqlite import SQLiteDatabase
from grokbuddy.domain.model import Conflict, PermissionDenied, TaskState
from grokbuddy.infrastructure.clock import ManualClock
from grokbuddy.infrastructure.runtime import LocalRuntime


def _key():
    return str(uuid4())


def test_v4_task_states_rounds_and_trigger_uniqueness(runtime):
    task = runtime.hub.create_task('builder', 'isolated v2 persistence', _key())
    assert task['revision_round'] == 0
    assert TaskState.PLAN_HUMAN_REVIEW.value == 'PLAN_HUMAN_REVIEW'
    assert TaskState.FINAL_HUMAN_REVIEW.value == 'FINAL_HUMAN_REVIEW'
    with runtime.db.transaction() as repo:
        current = repo.get('tasks', task['id'])
        current.update(state='PLAN_HUMAN_REVIEW', version=1,
                       revision_round=1,
                       gate_reason='LOCAL_PROBE', automation_frozen=True)
        repo.compare_and_swap('tasks', current, {'version': 0, 'state': 'NEW'})
    with runtime.db.transaction() as repo:
        assert repo.get('tasks', task['id']) == current
        current['state'] = 'FINAL_HUMAN_REVIEW'
        current['version'] = 2
        repo.compare_and_swap('tasks', current, {'version': 1, 'state': 'PLAN_HUMAN_REVIEW'})
    with pytest.raises(Conflict):
        with runtime.db.transaction() as repo:
            invalid = {**current, 'revision_round': -1}
            repo.save('tasks', invalid)


def test_existing_v3_json_rows_upgrade_without_rewriting(tmp_path):
    path = tmp_path / 'legacy' / 'hub.db'
    path.parent.mkdir()
    old = {'id': 'TASK-old', 'state': 'NEW', 'version': 0, 'owner_id': 'builder',
           'conversation_id': 'historical-conversation', 'trigger_message_id': 'message-1',
           'grokbuddy_enabled': True, 'opaque_v1_field': {'kept': ['exactly']}}
    raw = json.dumps(old, separators=(',', ':'))
    with sqlite3.connect(path) as c:
        c.executescript("""
            CREATE TABLE actors(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE tasks(id TEXT PRIMARY KEY,data TEXT NOT NULL CHECK(json_valid(data)),
              state TEXT GENERATED ALWAYS AS (json_extract(data,'$.state')) STORED NOT NULL
                CHECK(state IN ('NEW','DONE','CANCELLED','FAILED')),
              version INTEGER GENERATED ALWAYS AS (json_extract(data,'$.version')) STORED NOT NULL,
              owner_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.owner_id')) STORED NOT NULL REFERENCES actors(id));
            CREATE TABLE artifacts(id TEXT PRIMARY KEY,data TEXT NOT NULL CHECK(json_valid(data)),
              task_id TEXT GENERATED ALWAYS AS (json_extract(data,'$.task_id')) STORED NOT NULL REFERENCES tasks(id));
            CREATE UNIQUE INDEX one_active_conversation_task ON tasks(json_extract(data,'$.conversation_id'))
              WHERE json_extract(data,'$.conversation_id') IS NOT NULL
                AND json_extract(data,'$.state') NOT IN ('DONE','CANCELLED','FAILED');
            CREATE UNIQUE INDEX one_trigger_message_per_conversation ON tasks(
              json_extract(data,'$.conversation_id'),json_extract(data,'$.trigger_message_id'))
              WHERE json_extract(data,'$.conversation_id') IS NOT NULL
                AND json_extract(data,'$.trigger_message_id') IS NOT NULL;
            PRAGMA user_version=3;
        """)
        c.execute('INSERT INTO actors(id,data) VALUES (?,?)', ('builder', '{}'))
        c.execute('INSERT INTO tasks(id,data) VALUES (?,?)', (old['id'], raw))
        c.execute('INSERT INTO artifacts(id,data) VALUES (?,?)',
                  ('ART-old', json.dumps({'id': 'ART-old', 'task_id': old['id']})))
    db = SQLiteDatabase(path)
    with db.connect() as c:
        assert c.execute('PRAGMA user_version').fetchone()[0] == 4
        assert c.execute('SELECT data FROM tasks WHERE id=?', (old['id'],)).fetchone()[0] == raw
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []
    with db.transaction() as repo:
        assert repo.get('tasks', old['id']) == old
        assert repo.get('artifacts', 'ART-old')['task_id'] == old['id']
        updated = {**old, 'state': 'PLAN_HUMAN_REVIEW', 'version': 1,
                   'revision_round': 0}
        repo.compare_and_swap('tasks', updated, {'state': 'NEW', 'version': 0})
    SQLiteDatabase(path)  # Repeat initialization must retain data and indexes.
    with pytest.raises(Conflict):
        with db.transaction() as repo:
            repo.add('tasks', {**updated, 'id': 'TASK-duplicate',
                               'trigger_message_id': 'message-2'})


def test_assignment_generation_lease_cas_and_owner_is_unchanged(runtime):
    task = runtime.hub.create_task('builder', 'assignment anchor', _key())
    plan = runtime.hub.submit_artifact('builder', task['id'], 'PLAN', b'approved scope', _key())
    assignment = dict(id='WA-1', task_id=task['id'], generation=1, status='OFFERED',
                      version=0, worker_principal_id=None, lease_token=None,
                      lease_until=0, lease_generation=0, attempts=0,
                      approved_plan_artifact_id=plan['id'], approved_plan_hash=plan['sha256'],
                      approved_scope={'files': ['src/example.py']}, approved_scope_hash='a' * 64,
                      completion_artifact_id=None, completion_hash=None)
    with runtime.db.transaction() as repo:
        repo.add('worker_assignments', assignment)
        claimed = {**assignment, 'status': 'CLAIMED', 'version': 1,
                   'worker_principal_id': 'workbuddy-worker', 'lease_token': 'lease-1',
                   'lease_until': 100, 'lease_generation': 1, 'attempts': 1}
        repo.compare_and_swap('worker_assignments', claimed,
                              {'version': 0, 'status': 'OFFERED', 'lease_generation': 0})
    with pytest.raises(Conflict):
        with runtime.db.transaction() as repo:
            repo.compare_and_swap('worker_assignments',
                                  {**claimed, 'version': 2, 'lease_generation': 2},
                                  {'status': 'CLAIMED', 'lease_generation': 0})
    with pytest.raises(Conflict):
        with runtime.db.transaction() as repo:
            repo.add('worker_assignments', {**assignment, 'id': 'WA-2', 'generation': 2})
    with runtime.db.transaction() as repo:
        assert repo.get('tasks', task['id'])['owner_id'] == 'builder'
        assert repo.get('worker_assignments', 'WA-1') == claimed
    with pytest.raises(Conflict):
        with runtime.db.transaction() as repo:
            repo.add('worker_assignments', {**assignment, 'id': 'WA-bad', 'generation': 2,
                                            'approved_scope': None})
    other = runtime.hub.create_task('builder', 'other assignment task', _key())
    foreign_plan = runtime.hub.submit_artifact('builder', other['id'], 'PLAN', b'other', _key())
    with pytest.raises(Conflict):
        with runtime.db.transaction() as repo:
            repo.add('worker_assignments', {**assignment, 'id': 'WA-cross-task', 'generation': 2,
                                            'status': 'CANCELLED',
                                            'approved_plan_artifact_id': foreign_plan['id'],
                                            'approved_plan_hash': foreign_plan['sha256']})


def test_intake_receipt_outbox_and_projection_recovery_rows(flow):
    flow.plan()
    request_id = flow.request()
    outbox = flow.rows('outbox_events', review_request_id=request_id)[0]
    assert outbox['lease_generation'] == 0 and outbox['delivery_key'] == request_id
    assert len(outbox['request_hash']) == len(outbox['input_hash']) == len(outbox['profile_hash']) == 64
    rr = flow.rows('review_requests', id=request_id)[0]
    receipt = dict(id='INT-1', review_request_id=request_id, source='reviewer-poll',
                   deduplication_key=request_id, reviewer_actor_id='mock-reviewer',
                   input_hash=rr['envelope']['input_sha256'],
                   profile_hash=rr['envelope']['profile_sha256'], status='READY',
                   lease_token=None, lease_until=0, lease_generation=0, attempts=0)
    with flow.r.db.transaction() as repo:
        repo.add('intake_receipts', receipt)
        leased = {**receipt, 'status': 'LEASED', 'lease_token': 'intake-lease',
                  'lease_until': 100, 'lease_generation': 1, 'attempts': 1}
        repo.compare_and_swap('intake_receipts', leased,
                              {'status': 'READY', 'lease_generation': 0})
    with pytest.raises(Conflict):
        with flow.r.db.transaction() as repo:
            repo.add('intake_receipts', {**receipt, 'id': 'INT-duplicate'})
    with flow.r.db.transaction() as repo:
        assert repo.get('intake_receipts', receipt['id']) == leased
    projection = dict(id='GHP-isolated', review_id=rr['review_id'], task_id=flow.id,
                      binding_id='binding-isolated', status='UNKNOWN', lease_generation=1,
                      lease_token=None, lease_until=0, next_attempt_at=0)
    # A Review row is required by the existing projection FK; it is only a
    # disposable persistence fixture, not a v2 Review APPLY operation.
    with flow.r.db.transaction() as repo:
        repo.add('reviews', {'id': rr['review_id'], 'review_request_id': request_id})
        repo.add('github_comment_projections', projection)
        assert repo.get('github_comment_projections', projection['id']) == projection
    with pytest.raises(Conflict):
        with flow.r.db.transaction() as repo:
            repo.add('github_comment_projections', {**projection, 'id': 'GHP-bad',
                                                    'status': 'NOT_A_STATE'})


def test_owner_transfer_worker_path_requires_explicit_legacy_test_mode(tmp_path):
    runtime = LocalRuntime(tmp_path / 'no-legacy-worker', CONTRACTS,
                           clock=ManualClock(), legacy_create_test_mode=True)
    task = runtime.hub.create_task('builder', 'old worker offer', _key())
    with pytest.raises(PermissionDenied, match='test-only'):
        runtime.hub.offer_task('builder', task['id'], task['version'], _key())
    assert runtime.hub.get_task(task['id'])['owner_id'] == 'builder'
