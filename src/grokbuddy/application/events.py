from dataclasses import asdict
from copy import deepcopy
import json

from grokbuddy.domain.model import (HubError, Role, ACTIVE_REQUEST, TERMINAL, Conflict)
from grokbuddy.domain.rules import aggregate_verdict, finding_transition
from .common import Services, canonical, digest, uid, audit


def persist_event(repo, services, event):
    """Deduplicate a normalized ingress before creating Artifact or inbox metadata."""
    actor = services.actor(repo, event.actor_id, Role.REVIEWER)
    task = repo.get('tasks', event.task_id)
    envelope = asdict(event)
    envelope.pop('payload')
    normalized_hash = digest([event.event_type, event.task_id, event.review_request_id,
                              event.review_id, event.correlation_id, actor['id'],
                              event.execution_identity, event.payload])
    receipt_key = digest([event.source, event.deduplication_key])
    prior = repo.find('inbox_events', receipt_key=receipt_key)
    if prior:
        if prior[0].get('normalized_hash') != normalized_hash:
            raise Conflict('Deduplication key reused with different content')
        return prior[0]['id']
    # The same normalized result may arrive through callback and poll.  Keep a
    # receipt per ingress key, but reuse the immutable payload Artifact metadata.
    semantic_prior = [row for row in repo.find(
        'inbox_events', review_request_id=event.review_request_id)
        if row.get('review_id') == event.review_id
        and row.get('normalized_hash') == normalized_hash]
    if semantic_prior:
        payload_artifact_id = semantic_prior[0]['payload_artifact_id']
        payload_sha256 = semantic_prior[0]['payload_sha256']
        duplicate_of = semantic_prior[0]['id']
    else:
        # Record raw structured content separately; Audit never contains it.
        payload_artifact = services.add_artifact(
            repo, task['id'], actor, 'REVIEW_RESULT', canonical(event.payload))
        payload_artifact_id = payload_artifact['id']
        payload_sha256 = payload_artifact['sha256']
        duplicate_of = None
    row = dict(id=uid('IN'), **envelope, payload_artifact_id=payload_artifact_id,
               payload_sha256=payload_sha256, received_at=services.clock.now(),
               receipt_key=receipt_key, normalized_hash=normalized_hash,
               status='READY', lease_generation=0, lease_token=None, lease_until=0, attempts=0,
               duplicate_of_ingress_id=duplicate_of)
    repo.add('inbox_events', row)
    audit(repo, services.clock, actor, 'EVENT_RECEIVED', task['id'], request_id=event.review_request_id,
          event_id=event.event_id, ingress_id=row['id'], source=event.source,
          execution_identity=event.execution_identity, duplicate_of_ingress_id=duplicate_of)
    return row['id']


class EventService(Services):
    def ingest(self, event):
        try:
            with self.db.transaction() as repo:
                return persist_event(repo, self, event)
        except HubError as exc:
            with self.db.transaction() as repo:
                audit(repo, self.clock, self.actor(repo, 'system', Role.SYSTEM), 'INGRESS_REJECTED', code=exc.code)
            raise

    def handle_one(self):
        # Claim and processing use the same short serialized transaction: rollback keeps READY.
        with self.db.transaction() as repo:
            events = repo.find('inbox_events', status='READY')
            if not events:
                return None
            incoming_id = events[0]['id']
        try:
            with self.db.transaction() as repo:
                incoming = repo.get('inbox_events', incoming_id)
                if incoming['status'] != 'READY':
                    return None
                actor = self.actor(repo, incoming['actor_id'], Role.REVIEWER)
                rr = repo.get('review_requests', incoming['review_request_id'])
                task = repo.get('tasks', rr['task_id'])
                expected = rr['envelope']
                if (incoming['task_id'], incoming['review_id'], incoming['actor_id'], incoming['correlation_id']) != (
                        rr['task_id'], rr['review_id'], expected['expected_reviewer_actor_id'], rr['id']):
                    raise HubError('Event identity or request binding mismatch')
                if actor['provider_id'] == repo.get('actors', task['owner_id'])['provider_id']:
                    raise HubError('Self-review is forbidden')
                _, content = self.artifact(repo, task['id'], incoming['payload_artifact_id'], incoming['payload_sha256'])
                payload = json.loads(content)
                event_hash = incoming.get('normalized_hash') or digest([
                    incoming['event_type'], task['id'], rr['id'], rr['review_id'],
                    incoming['correlation_id'], actor['id'],
                    incoming.get('execution_identity'), payload])
                semantic_key = incoming.get('receipt_key') or digest([
                    incoming['source'], incoming['deduplication_key']])
                prior = repo.find('processed_events', id=semantic_key)
                if prior:
                    if prior[0]['normalized_hash'] != event_hash:
                        raise Conflict('Deduplication key reused with different content')
                    return self._finish(repo, incoming, actor, 'DUPLICATE', event_hash, semantic_key, insert=False)
                completed = repo.find('reviews', review_request_id=rr['id'])
                if completed and incoming['event_type'] == 'ReviewCompleted':
                    if (completed[0]['result_hash'] != incoming['payload_sha256']
                            or completed[0].get('execution_identity') != incoming.get('execution_identity')):
                        raise Conflict('Completed review cannot be overwritten')
                    return self._finish(repo, incoming, actor, 'DUPLICATE', event_hash, semantic_key)
                if (rr['status'] not in ACTIVE_REQUEST or task['state'] in TERMINAL
                        or task['state'] in ('ESCALATED', 'BLOCKED', 'PLAN_HUMAN_REVIEW', 'FINAL_HUMAN_REVIEW')
                        or task.get('automation_frozen')):
                    return self._finish(repo, incoming, actor, 'LATE_EVENT', event_hash, semantic_key)
                if incoming['event_type'] == 'ReviewCompleted':
                    self.contracts.validate('result', payload)
                    for key in ('protocol_version', 'task_id', 'review_request_id', 'review_id', 'review_type',
                                'review_round', 'content_revision', 'review_profile', 'review_profile_version',
                                'profile_sha256', 'input_sha256'):
                        if payload[key] != expected[key]:
                            raise HubError('Result does not match frozen request')
                    if payload['reviewer']['id'] != actor['id'] or payload['reviewer']['type'] != actor['reviewer_type']:
                        raise HubError('Result reviewer declaration mismatch')
                    if (payload['protocol_version'] == 'v2'
                            and payload['expected_task_version'] != task['version']):
                        raise Conflict('Review result used a stale Task version')
                elif incoming['event_type'] not in ('ReviewStarted', 'ReviewFailed'):
                    raise HubError('Unknown normalized event type')
                elif payload != {'protocol_version': expected['protocol_version']}:
                    raise HubError('Invalid lifecycle event payload')
                if self.clock.now() >= task['deadline_at']:
                    self.review_failure_gate(repo, task, 'TASK_TIMEOUT', 'TIMED_OUT')
                    return self._finish(repo, incoming, actor, 'LATE_EVENT', event_hash, semantic_key)
                if self.clock.now() >= rr['deadline_at']:
                    self.review_failure_gate(repo, task, 'REVIEW_TIMEOUT', 'TIMED_OUT')
                    return self._finish(repo, incoming, actor, 'LATE_EVENT', event_hash, semantic_key)
                if task['active_rr_id'] != rr['id'] or task['content_revision'] != expected['content_revision']:
                    raise HubError('Review is not current')
                if incoming['event_type'] == 'ReviewStarted':
                    if rr['status'] == 'PENDING':
                        rr.update(status='IN_PROGRESS', started_at=self.clock.now())
                        repo.save('review_requests', rr)
                        round_row = repo.get('review_rounds', rr['id'])
                        round_row['evaluation_status'] = 'IN_PROGRESS'
                        repo.save('review_rounds', round_row)
                        self.change(repo, task, 'plan_started' if rr['review_type'] == 'PLAN_REVIEW' else 'final_started', actor, rr['id'])
                elif incoming['event_type'] == 'ReviewFailed':
                    self.review_failure_gate(repo, task, 'REVIEWER_FAILED', 'FAILED')
                else:
                    self._complete(repo, task, rr, incoming, payload, actor)
                return self._finish(repo, incoming, actor, 'APPLIED', event_hash, semantic_key)
        except HubError as exc:
            # The business UoW was rolled back; only the rejection and its Audit now commit.
            with self.db.transaction() as repo:
                incoming = repo.get('inbox_events', incoming_id)
                if incoming['status'] == 'READY':
                    incoming.update(status='REJECTED', error_code=exc.code)
                    repo.save('inbox_events', incoming)
                    actor = self.actor(repo, 'system', Role.SYSTEM)
                    audit(repo, self.clock, actor, 'VALIDATION_FAILURE', incoming['task_id'],
                          request_id=incoming['review_request_id'], event_id=incoming['event_id'], code=exc.code)
            return 'REJECTED'

    def _finish(self, repo, incoming, actor, outcome, event_hash, key, insert=True):
        incoming['status'] = outcome
        repo.save('inbox_events', incoming)
        if insert:
            repo.add('processed_events', dict(id=key, normalized_hash=event_hash, outcome=outcome,
                     review_request_id=incoming['review_request_id'], event_id=incoming['event_id'], at=self.clock.now()))
        audit(repo, self.clock, actor, outcome, incoming['task_id'], request_id=incoming['review_request_id'],
              event_id=incoming['event_id'], ingress_id=incoming['id'])
        return outcome

    def _complete(self, repo, task, rr, incoming, result, actor):
        frozen = rr['envelope']
        self.artifact(repo, task['id'], frozen['input_artifact_id'], frozen['input_sha256'])
        self.artifact(repo, task['id'], frozen['profile_artifact_id'], frozen['profile_sha256'])
        plan = rr['review_type'] == 'PLAN_REVIEW'
        protocol_v2 = result['protocol_version'] == 'v2'
        if plan and result['verdict'] == 'PASS' and any(r['blocking'] for r in result['risks']):
            raise HubError('PLAN PASS conflicts with blocking risks')
        if not plan:
            self.ensure_actions_closed(repo, task)
            if not task.get('self_test_passed') or task['current_final_id'] != rr['input_artifact_id']:
                raise HubError('Final package/self-test no longer current')
        prepared = []
        actionable_ids = []
        projected = repo.find('review_findings', task_id=task['id'])
        if protocol_v2:
            prepared, actionable_ids, projected = self._prepare_v2_findings(
                repo, task, rr, result)
        elif not plan:
            self._validate_findings(repo, task, rr, result)
        review = dict(id=rr['review_id'], task_id=task['id'], review_request_id=rr['id'],
                      reported_verdict=result['verdict'], effective_verdict=result['verdict'],
                      result_artifact_id=incoming['payload_artifact_id'], result_hash=incoming['payload_sha256'],
                      reviewer_actor_id=actor['id'], review_round=rr['review_round'], created_at=self.clock.now(),
                      execution_identity=incoming.get('execution_identity'))
        if protocol_v2:
            relevant = projected if not plan else [
                finding for finding in projected if finding.get('review_type') == 'PLAN_REVIEW']
            unresolved = [finding for finding in relevant
                          if finding['status'] not in ('VERIFIED', 'WAIVED_BY_HUMAN')]
            if result['verdict'] == 'PASS' and unresolved:
                raise HubError('PASS cannot leave actionable findings unresolved')
            actionable_after = {finding['id'] for finding in unresolved}
            if result['verdict'] == 'NEEDS_CHANGES' and not set(actionable_ids).intersection(actionable_after):
                raise HubError('NEEDS_CHANGES requires an actionable finding')
            review['effective_verdict'] = aggregate_verdict(relevant, result['verdict'])
            snapshot = deepcopy(result)
            for item, finding_id, _ in prepared:
                item_index = result['findings'].index(item)
                snapshot['findings'][item_index]['finding_id'] = finding_id
            review.update(protocol_version='v2', expected_task_version=result['expected_task_version'],
                          actionable_finding_ids=actionable_ids, result_snapshot=snapshot)
        elif not plan:
            status_by_id = {v['finding_id']: ('VERIFIED' if v['outcome'] == 'VERIFIED' else 'OPEN') for v in result['verifications']}
            projected = [{**f, 'status': status_by_id.get(f['id'], f['status'])} for f in projected]
            projected += [{**f, 'status': 'OPEN'} for f in result['findings']]
            review['effective_verdict'] = aggregate_verdict(projected, result['verdict'])
        repo.add('reviews', review)
        if protocol_v2:
            self._apply_v2_findings(repo, task, rr, result, prepared, actor)
        elif not plan:
            self._apply_findings(repo, task, rr, result, actor)
        verdict = review['effective_verdict']
        if verdict != result['verdict']:
            audit(repo, self.clock, actor, 'VERDICT_MISMATCH', task['id'], request_id=rr['id'])
        rr.update(status='COMPLETED', completed_at=self.clock.now())
        repo.save('review_requests', rr)
        round_row = repo.get('review_rounds', rr['id'])
        round_row['evaluation_status'] = 'COMPLETED'
        repo.save('review_rounds', round_row)
        task['active_rr_id'] = None
        if verdict == 'PASS':
            if plan:
                task['approved_plan_id'] = rr['input_artifact_id']
                if protocol_v2:
                    task['approved_scope'] = task['current_plan_scope']
                    task['approved_scope_hash'] = task['current_plan_scope_hash']
                    task['scope_change_request'] = None
            elif protocol_v2:
                task['completion_basis'] = 'FINAL_REVIEW_PASS'
            if protocol_v2:
                task.update(automation_frozen=False, gate_reason=None, pending_revision_kind=None)
            action = 'plan_pass' if plan else 'final_pass'
        elif protocol_v2 and (verdict == 'BLOCK' or rr['review_round'] >= rr['round_limit']):
            task['gate_reason'] = 'ROUND_LIMIT' if rr['review_round'] >= rr['round_limit'] else 'REVIEW_BLOCK'
            task['automation_frozen'] = True
            action = 'plan_human_review' if plan else 'final_human_review'
        elif rr['review_round'] >= rr['round_limit']:
            task['escalation_reason'] = 'ROUND_LIMIT'
            action = 'escalate'
        else:
            if protocol_v2:
                task['pending_revision_kind'] = rr['review_type']
                if not plan:
                    task['final_fix_finding_ids'] = [finding['id'] for finding in projected
                                                     if finding['status'] not in ('VERIFIED', 'WAIVED_BY_HUMAN')]
                action = 'plan_changes' if plan else 'final_changes'
            else:
                action = ('plan_' if plan else 'final_') + ('block' if verdict == 'BLOCK' else 'changes')
        self.change(repo, task, action, actor, rr['id'])
        if protocol_v2 and not plan:
            self._ensure_projection_intent(repo, task, rr, review)
        audit(repo, self.clock, actor, 'REVIEW_COMPLETED', task['id'], request_id=rr['id'], verdict=verdict)

    def _prepare_v2_findings(self, repo, task, rr, result):
        if len(result['findings']) > self.settings.max_findings_per_review:
            raise HubError('Per-review finding limit exceeded')
        for evidence in result['evidence']:
            self.artifact(repo, task['id'], evidence['artifact_id'])
        for collection, key in ((result['findings'], 'external_finding_key'),
                                (result['verifications'], 'finding_id')):
            if len({item[key] for item in collection}) != len(collection):
                raise HubError('Duplicate finding operation')
        _, content = self.artifact(repo, task['id'], rr['context_artifact_id'])
        frozen = {finding['id']: finding for finding in json.loads(content)['findings']}
        verification_ids = {item['finding_id'] for item in result['verifications']}
        prepared = []
        actionable_ids = []
        for item in result['findings']:
            self.artifact(repo, task['id'], item['evidence']['artifact_id'])
            finding_id = item.get('finding_id')
            is_new = finding_id is None
            if is_new:
                finding_id = uid('FND')
            else:
                finding = repo.get('review_findings', finding_id)
                if (finding['task_id'] != task['id'] or finding_id not in frozen
                        or finding['version'] != frozen[finding_id]['version']):
                    raise Conflict('Referenced finding is outside the frozen Review scope')
                if finding['status'] in ('VERIFIED', 'WAIVED_BY_HUMAN'):
                    raise HubError('Closed finding is not actionable')
                if finding['external_finding_key'] != item['external_finding_key']:
                    raise HubError('Finding reference identity mismatch')
            if finding_id in verification_ids:
                raise HubError('Finding cannot be actionable and verified in one result')
            for field in ('supersedes', 'parent_finding_id'):
                if field in item:
                    related = repo.get('review_findings', item[field])
                    if related['task_id'] != task['id']:
                        raise HubError('Finding relationship crosses tasks')
            prepared.append((item, finding_id, is_new))
            actionable_ids.append(finding_id)
        projected = repo.find('review_findings', task_id=task['id'])
        status_by_id = {item['finding_id']: ('VERIFIED' if item['outcome'] == 'VERIFIED' else 'OPEN')
                        for item in result['verifications']}
        for item in result['verifications']:
            self.artifact(repo, task['id'], item['evidence']['artifact_id'])
            finding = repo.get('review_findings', item['finding_id'])
            if (finding['task_id'] != task['id'] or item['finding_id'] not in frozen
                    or finding['version'] != frozen[item['finding_id']]['version']):
                raise Conflict('Finding changed during evaluation')
            finding_transition(finding['status'], 'verify' if item['outcome'] == 'VERIFIED' else 'reopen', Role.REVIEWER)
        projected = [{**finding, 'status': status_by_id.get(finding['id'], finding['status'])}
                     for finding in projected]
        for item, finding_id, is_new in prepared:
            if is_new:
                projected.append({**item, 'id': finding_id, 'status': 'OPEN',
                                  'review_type': rr['review_type']})
        return prepared, actionable_ids, projected

    def _apply_v2_findings(self, repo, task, rr, result, prepared, actor):
        for item, finding_id, is_new in prepared:
            if not is_new:
                audit(repo, self.clock, actor, 'FINDING_REFERENCED', task['id'],
                      request_id=rr['id'], finding_id=finding_id)
                continue
            finding = {**item, 'id': finding_id, 'task_id': task['id'],
                       'review_id': rr['review_id'], 'review_request_id': rr['id'],
                       'review_type': rr['review_type'], 'review_round': rr['review_round'],
                       'status': 'OPEN', 'version': 0,
                       'created_at': self.clock.now(), 'updated_at': self.clock.now()}
            repo.add('review_findings', finding)
            task['total_findings_created'] += 1
            repo.add('finding_events', dict(id=uid('EVT'), finding_id=finding_id, task_id=task['id'],
                     old_status=None, new_status='OPEN', review_id=rr['review_id'], actor_id=actor['id'],
                     at=self.clock.now()))
            audit(repo, self.clock, actor, 'FINDING_CREATED', task['id'],
                  request_id=rr['id'], finding_id=finding_id)
        for item in result['verifications']:
            finding = repo.get('review_findings', item['finding_id'])
            old = finding['status']
            finding['status'] = 'VERIFIED' if item['outcome'] == 'VERIFIED' else 'OPEN'
            finding['version'] += 1
            finding['updated_at'] = self.clock.now()
            repo.save('review_findings', finding)
            repo.add('finding_events', dict(id=uid('EVT'), finding_id=finding['id'], task_id=task['id'],
                     old_status=old, new_status=finding['status'], review_id=rr['review_id'],
                     actor_id=actor['id'], evidence=item['evidence'], reason=item['reason'],
                     at=self.clock.now()))
            audit(repo, self.clock, actor, 'FINDING_' + finding['status'], task['id'],
                  request_id=rr['id'], finding_id=finding['id'])

    def _ensure_projection_intent(self, repo, task, rr, review):
        existing = repo.find('github_comment_projections', review_id=review['id'])
        if existing:
            return existing[0]
        row = dict(id='GHP-' + digest([review['id'], 'FINAL_REVIEW_INTENT']),
                   task_id=task['id'], review_request_id=rr['id'], review_id=review['id'],
                   binding_id=None, marker=f"<!-- grokbuddy-final-review:{review['id']} -->",
                   desired_body=None, desired_hash=None, applied_hash=None,
                   comment_id=None, comment_url=None, status='UNKNOWN', attempts=0,
                   next_attempt_at=self.clock.now(), lease_until=0, lease_token=None,
                   lease_generation=0, intent_kind='FINAL_REVIEW_COMMENT',
                   frozen_review_hash=review['result_hash'], frozen_task_version=task['version'],
                   recovery_reason='BINDING_OR_PROJECTION_WORKER_REQUIRED', created_at=self.clock.now())
        repo.add('github_comment_projections', row)
        audit(repo, self.clock, self.actor(repo, 'system', Role.SYSTEM),
              'GITHUB_COMMENT_PROJECTION_INTENT_CREATED', task['id'], request_id=rr['id'],
              review_id=review['id'], status='UNKNOWN')
        return row

    def _validate_findings(self, repo, task, rr, result):
        if len(result['findings']) > self.settings.max_findings_per_review:
            raise HubError('Per-review finding limit exceeded')
        for collection, key in ((result['findings'], 'external_finding_key'), (result['verifications'], 'finding_id')):
            if len({r[key] for r in collection}) != len(collection):
                raise HubError('Duplicate finding operation')
        _, content = self.artifact(repo, task['id'], rr['context_artifact_id'])
        frozen = {f['id']: f for f in json.loads(content)['findings']}
        for item in result['findings'] + result['verifications']:
            self.artifact(repo, task['id'], item['evidence']['artifact_id'])
        for item in result['findings']:
            for field in ('supersedes', 'parent_finding_id'):
                if field in item:
                    old = repo.get('review_findings', item[field])
                    if old['task_id'] != task['id']:
                        raise HubError('Finding relationship crosses tasks')
                    # New IDs are generated after validation; edges only to existing nodes => no cycles.
        for item in result['verifications']:
            finding = repo.get('review_findings', item['finding_id'])
            if finding['task_id'] != task['id'] or item['finding_id'] not in frozen:
                raise HubError('Finding is outside frozen review scope')
            if finding['version'] != frozen[item['finding_id']]['version']:
                raise Conflict('Finding changed during evaluation')
            finding_transition(finding['status'], 'verify' if item['outcome'] == 'VERIFIED' else 'reopen', Role.REVIEWER)

    def _apply_findings(self, repo, task, rr, result, actor):
        for item in result['findings']:
            finding = dict(item, id=uid('FND'), task_id=task['id'], review_id=rr['review_id'],
                           review_round=rr['review_round'], status='OPEN', version=0,
                           created_at=self.clock.now(), updated_at=self.clock.now())
            repo.add('review_findings', finding)
            task['total_findings_created'] += 1
            repo.add('finding_events', dict(id=uid('EVT'), finding_id=finding['id'], task_id=task['id'],
                     old_status=None, new_status='OPEN', review_id=rr['review_id'], actor_id=actor['id'], at=self.clock.now()))
            audit(repo, self.clock, actor, 'FINDING_CREATED', task['id'], request_id=rr['id'], finding_id=finding['id'])
        for item in result['verifications']:
            finding = repo.get('review_findings', item['finding_id'])
            old = finding['status']
            finding['status'] = 'VERIFIED' if item['outcome'] == 'VERIFIED' else 'OPEN'
            finding['version'] += 1
            finding['updated_at'] = self.clock.now()
            repo.save('review_findings', finding)
            repo.add('finding_events', dict(id=uid('EVT'), finding_id=finding['id'], task_id=task['id'],
                     old_status=old, new_status=finding['status'], review_id=rr['review_id'], actor_id=actor['id'],
                     evidence=item['evidence'], reason=item['reason'], at=self.clock.now()))
            audit(repo, self.clock, actor, 'FINDING_' + finding['status'], task['id'], request_id=rr['id'], finding_id=finding['id'])
