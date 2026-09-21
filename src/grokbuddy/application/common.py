from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from grokbuddy.domain.model import (HubError, Conflict, PermissionDenied, Role,
                                    TERMINAL, ACTIVE_REQUEST, TaskState)
from grokbuddy.domain.rules import transition

NO_VERSION = object()


def uid(prefix):
    return f'{prefix}-{uuid4()}'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def iso(micros):
    return datetime.fromtimestamp(micros / 1_000_000, timezone.utc).isoformat().replace('+00:00', 'Z')


def audit(repo, clock, actor, action, task_id=None, old=None, new=None, request_id=None, event_id=None, **metadata):
    repo.add('audit_logs', dict(id=uid('AUD'), task_id=task_id, actor_type=actor['role'],
             actor_id=actor['id'], actor_name=actor['name'], action=action, old_state=old,
             new_state=new, request_id=request_id, event_id=event_id,
             correlation_id=request_id or task_id, payload_summary=metadata, timestamp=iso(clock.now())))


class Services:
    def __init__(self, db, store, contracts, clock, settings):
        self.db, self.store, self.contracts = db, store, contracts
        self.clock, self.settings = clock, settings

    def actor(self, repo, actor_id, *roles):
        actor = repo.get('actors', actor_id)
        if not actor.get('enabled') or (roles and actor['role'] not in roles):
            raise PermissionDenied('Principal not authorized')
        return actor

    def task_for(self, repo, task_id, actor, expected_version=NO_VERSION, live=True):
        task = repo.get('tasks', task_id)
        if actor['role'] == Role.BUILDER and task['owner_id'] != actor['id']:
            raise PermissionDenied('Task belongs to another Builder')
        if expected_version is not NO_VERSION:
            if type(expected_version) is not int or expected_version < 0:
                raise HubError('An integer expected_version is required')
            if task['version'] != expected_version:
                raise Conflict('Stale task version')
        if live and (task['state'] in TERMINAL or task['state'] == TaskState.ESCALATED
                     or self.clock.now() >= task['deadline_at']):
            raise HubError('Task is terminal, escalated or expired')
        return task

    @contextmanager
    def command(self, actor_id, operation, key, params, *roles, audit_rejection=True):
        if not isinstance(key, str) or not key or len(key) > 200:
            raise HubError('A bounded idempotency key is required')
        try:
            with self.db.transaction() as repo:
                actor = self.actor(repo, actor_id, *roles)
                receipt_id = digest([actor_id, operation, key])
                found = repo.find('command_receipts', id=receipt_id)
                if found:
                    if found[0]['input_digest'] != digest(params):
                        raise Conflict('Idempotency key reused with different input')
                    yield repo, actor, {'replay': found[0]['response']}
                    return
                box = {}
                yield repo, actor, box
                repo.add('command_receipts', dict(id=receipt_id, input_digest=digest(params),
                         operation=operation, actor_id=actor_id, response=box['response'],
                         created_at=self.clock.now()))
        except HubError as exc:
            if audit_rejection:
                with self.db.transaction() as repo:
                    known = repo.find('actors', id=actor_id)
                    actor = known[0] if known else {'id': 'unrecognized', 'role': 'UNAUTHENTICATED', 'name': 'unrecognized'}
                    audit(repo, self.clock, actor, 'COMMAND_REJECTED', operation=operation, code=exc.code)
            raise

    def change(self, repo, task, action, actor, request_id=None):
        old, version = task['state'], task['version']
        task['state'] = transition(old, action)
        task['version'] += 1
        repo.save('tasks', task, expected_version=version)
        repo.add('task_events', dict(id=uid('EVT'), task_id=task['id'], action=action,
                 old_state=old, new_state=task['state'], version=task['version'], actor_id=actor['id'], at=self.clock.now()))
        audit(repo, self.clock, actor, 'STATE_CHANGED', task['id'], old, task['state'], request_id, version=task['version'])

    def touch(self, repo, task):
        version = task['version']
        task['version'] += 1
        repo.save('tasks', task, expected_version=version)

    def artifact(self, repo, task_id, artifact_id, expected_hash=None, kinds=None):
        artifact = repo.get('artifacts', artifact_id)
        if artifact['task_id'] != task_id:
            raise PermissionDenied('Artifact is outside task scope')
        if expected_hash is not None and artifact['sha256'] != expected_hash:
            raise HubError('Artifact hash mismatch')
        if kinds and artifact['artifact_type'] not in kinds:
            raise HubError('Artifact type mismatch')
        content = self.store.read(artifact['storage_pointer'], artifact['sha256'], artifact['size_bytes'])
        return artifact, content

    def add_artifact(self, repo, task_id, actor, kind, content, mime='application/json'):
        pointer, sha = self.store.put(content)
        artifact = dict(id=uid('ART'), task_id=task_id, artifact_type=kind, mime_type=mime,
                        storage_type='FILESYSTEM', storage_pointer=pointer, sha256=sha,
                        size_bytes=len(content), created_by=actor['id'], created_at=self.clock.now())
        repo.add('artifacts', artifact)
        audit(repo, self.clock, actor, 'ARTIFACT_CREATED', task_id, artifact_id=artifact['id'], sha256=sha)
        return artifact

    def stop_request(self, repo, task, status, reason):
        if task.get('active_rr_id'):
            rr = repo.get('review_requests', task['active_rr_id'])
            if rr['status'] in ACTIVE_REQUEST:
                rr.update(status=status, failure_code=reason, completed_at=self.clock.now())
                repo.save('review_requests', rr)
                round_row = repo.get('review_rounds', rr['id'])
                round_row['evaluation_status'] = status
                repo.save('review_rounds', round_row)
                system = self.actor(repo, 'system', Role.SYSTEM)
                audit(repo, self.clock, system, 'REVIEW_' + status, task['id'], request_id=rr['id'], code=reason)
            for event in repo.find('outbox_events', review_request_id=rr['id']):
                if event['status'] not in ('SENT', 'CANCELLED'):
                    event.update(status='CANCELLED', lease_token=None)
                    repo.save('outbox_events', event)
        task['active_rr_id'] = None

    def escalate(self, repo, task, reason, rr_status='ESCALATED'):
        self.stop_request(repo, task, rr_status, reason)
        task['escalation_reason'] = reason
        if task['state'] not in TERMINAL and task['state'] != TaskState.ESCALATED:
            self.change(repo, task, 'escalate', self.actor(repo, 'system', Role.SYSTEM))

    def ensure_actions_closed(self, repo, task):
        unresolved = [a for a in repo.find('human_approvals', task_id=task['id'], kind='HIGH_RISK_ACTION')
                      if a['status'] != 'CONSUMED' and not (a['status'] == 'REJECTED' and a.get('withdrawn'))]
        if unresolved:
            raise HubError('High-risk actions remain unauthorized or unconsumed')
