import random
import time
from grokbuddy.domain.model import (HubError, Role, TERMINAL, ACTIVE_REQUEST, RetryableDelivery, DeliveryUnknown)
from .common import Services, uid, audit, digest


class TimeoutService(Services):
    def sweep(self):
        count = 0
        with self.db.transaction() as repo:
            for task in repo.find('tasks'):
                if task['state'] in TERMINAL or task['state'] == 'ESCALATED':
                    continue
                if (task.get('automation_frozen')
                        or task['state'] in ('PLAN_HUMAN_REVIEW', 'FINAL_HUMAN_REVIEW')):
                    continue
                if self.clock.now() >= task['deadline_at']:
                    self.review_failure_gate(repo, task, 'TASK_TIMEOUT', 'TIMED_OUT')
                    count += 1
                    continue
                if task['active_rr_id']:
                    rr = repo.get('review_requests', task['active_rr_id'])
                    if rr['status'] in ACTIVE_REQUEST and self.clock.now() >= rr['deadline_at']:
                        self.review_failure_gate(repo, task, 'REVIEW_TIMEOUT', 'TIMED_OUT')
                        count += 1
                        continue
                for approval in repo.find('human_approvals', task_id=task['id'], kind='HIGH_RISK_ACTION'):
                    if approval['status'] in ('PENDING', 'APPROVED') and self.clock.now() >= approval['expires_at']:
                        approval['status'] = 'EXPIRED'
                        repo.save('human_approvals', approval)
                        repo.add('approval_events', dict(id=uid('EVT'), approval_id=approval['id'],
                                 action='EXPIRED', actor_id='system', at=self.clock.now()))
                        audit(repo, self.clock, self.actor(repo, 'system', Role.SYSTEM), 'APPROVAL_EXPIRED', task['id'], approval_id=approval['id'])
                        self.escalate(repo, task, 'APPROVAL_EXPIRED')
                        count += 1
                        break
        return count

    def recover_assignments(self):
        """Fence expired assignment leases and offer a new generation when safe."""
        recovered = 0
        with self.db.transaction() as repo:
            for assignment in repo.find('worker_assignments', status='CLAIMED'):
                if assignment['lease_until'] > self.clock.now():
                    continue
                task = repo.get('tasks', assignment['task_id'])
                system = self.actor(repo, 'system', Role.SYSTEM)
                stale = {**assignment, 'status': 'FROZEN', 'version': assignment['version'] + 1,
                         'lease_token': None, 'lease_until': 0, 'frozen_at': self.clock.now(),
                         'freeze_reason': 'LEASE_EXPIRED'}
                repo.compare_and_swap('worker_assignments', stale,
                                      {'version': assignment['version'], 'status': 'CLAIMED',
                                       'lease_generation': assignment['lease_generation']})
                audit(repo, self.clock, system, 'WORKER_ASSIGNMENT_LEASE_EXPIRED', task['id'],
                      assignment_id=assignment['id'], generation=assignment['generation'],
                      lease_generation=assignment['lease_generation'])
                if (task['state'] == 'EXECUTING' and not task.get('automation_frozen')
                        and self.clock.now() < task['deadline_at']):
                    replacement = {
                        **{key: value for key, value in assignment.items()
                           if key not in ('id', 'generation', 'status', 'version',
                                          'worker_principal_id', 'lease_token', 'lease_until',
                                          'lease_generation', 'attempts', 'claimed_at',
                                          'progress_summary', 'progress_at')},
                        'id': uid('WA'), 'generation': assignment['generation'] + 1,
                        'status': 'OFFERED', 'version': 0, 'worker_principal_id': None,
                        'lease_token': None, 'lease_until': 0, 'lease_generation': 0,
                        'attempts': 0, 'offered_by': system['id'], 'offered_at': self.clock.now(),
                    }
                    repo.add('worker_assignments', replacement)
                    audit(repo, self.clock, system, 'WORKER_ASSIGNMENT_RECOVERED', task['id'],
                          assignment_id=replacement['id'], generation=replacement['generation'],
                          replaces_assignment_id=assignment['id'])
                recovered += 1
        return recovered

    def run_once(self):
        return {'timeouts': self.sweep(), 'assignments': self.recover_assignments()}


class Dispatcher(Services):
    def __init__(self, *args, adapter, jitter=None, reviewer_actor_ids=None):
        super().__init__(*args)
        self.adapter = adapter
        self.jitter = jitter or (lambda maximum: random.uniform(0, maximum))
        self.reviewer_actor_ids = set(reviewer_actor_ids) if reviewer_actor_ids is not None else None

    def _claim(self):
        with self.db.transaction() as repo:
            for row in repo.find('outbox_events'):
                expired_lease = row['status'] == 'LEASED' and row['lease_until'] <= self.clock.now()
                ready = row['status'] in ('READY', 'RETRY', 'UNKNOWN') and row['next_attempt_at'] <= self.clock.now()
                if not (expired_lease or ready):
                    continue
                rr = repo.get('review_requests', row['review_request_id'])
                if (self.reviewer_actor_ids is not None
                        and rr['envelope']['expected_reviewer_actor_id'] not in self.reviewer_actor_ids):
                    continue
                task = repo.get('tasks', rr['task_id'])
                if (task['state'] in TERMINAL or task['state'] == 'ESCALATED'
                        or task.get('automation_frozen')
                        or task['state'] in ('PLAN_HUMAN_REVIEW', 'FINAL_HUMAN_REVIEW')
                        or rr['status'] not in ACTIVE_REQUEST):
                    row.update(status='CANCELLED', lease_token=None)
                    repo.save('outbox_events', row)
                    continue
                if self.clock.now() >= task['deadline_at'] or self.clock.now() >= rr['deadline_at']:
                    reason = 'TASK_TIMEOUT' if self.clock.now() >= task['deadline_at'] else 'REVIEW_TIMEOUT'
                    self.review_failure_gate(repo, task, reason, 'TIMED_OUT')
                    continue
                claimed_from_status = 'UNKNOWN' if expired_lease else row['status']
                row.update(status='LEASED', lease_until=self.clock.now() + self.settings.lease_seconds * 1_000_000,
                           lease_token=uid('LEASE'), lease_generation=row.get('lease_generation', 0) + 1,
                           attempts=row['attempts'] + 1,
                           claimed_from_status=claimed_from_status)
                repo.save('outbox_events', row)
                audit(repo, self.clock, self.actor(repo, 'system', Role.SYSTEM), 'DELIVERY_CLAIMED', task['id'], request_id=rr['id'], attempt=row['attempts'])
                return row, rr
        return None

    def dispatch_one(self):
        claimed = self._claim()
        if not claimed:
            return None
        row, rr = claimed
        outcome, code = 'SENT', None
        try:
            # No DB transaction held while querying/submitting an adapter.
            status = self.adapter.get_delivery_status(row['delivery_key'])
            if status.status == 'UNKNOWN':
                raise DeliveryUnknown()
            if status.status == 'NOT_FOUND':
                if (row.get('claimed_from_status') == 'UNKNOWN'
                        and row.get('reconcile_misses', 0) < 1):
                    outcome, code = 'UNKNOWN', 'DELIVERY_RECONCILE_PENDING'
                elif row['attempts'] > self.settings.delivery_max_attempts:
                    outcome, code = 'FAILED', 'DELIVERY_EXHAUSTED'
                else:
                    receipt = self.adapter.submit_review_request(rr['envelope'], row['delivery_key'])
                    if receipt.status != 'ACCEPTED':
                        raise DeliveryUnknown()
            elif status.status != 'ACCEPTED':
                raise DeliveryUnknown()
        except RetryableDelivery:
            outcome, code = ('FAILED' if row['attempts'] >= self.settings.delivery_max_attempts else 'RETRY'), 'RETRYABLE'
        except DeliveryUnknown:
            exhausted = row['attempts'] >= self.settings.delivery_max_attempts
            outcome, code = ('FAILED', 'DELIVERY_UNKNOWN_EXHAUSTED') if exhausted else ('UNKNOWN', 'DELIVERY_UNKNOWN')
        except HubError as exc:
            outcome, code = 'FAILED', exc.code
        except Exception:
            # Unexpected exception may occur after remote acceptance: never blindly resend.
            outcome, code = 'UNKNOWN', 'DELIVERY_UNKNOWN'
        with self.db.transaction() as repo:
            current = repo.get('outbox_events', row['id'])
            if (current['status'] != 'LEASED' or current['lease_token'] != row['lease_token']
                    or current.get('lease_generation', 0) != row['lease_generation']):
                return 'LEASE_LOST'
            task = repo.get('tasks', rr['task_id'])
            latest = repo.get('review_requests', rr['id'])
            if (latest['status'] not in ACTIVE_REQUEST or task['state'] in TERMINAL
                    or task['state'] == 'ESCALATED' or task.get('automation_frozen')
                    or task['state'] in ('PLAN_HUMAN_REVIEW', 'FINAL_HUMAN_REVIEW')):
                current.update(status='CANCELLED', lease_token=None)
                repo.save('outbox_events', current)
                return 'CANCELLED'
            current.update(status=outcome, last_error_code=code, lease_token=None)
            if code == 'DELIVERY_RECONCILE_PENDING':
                current['reconcile_misses'] = current.get('reconcile_misses', 0) + 1
            elif outcome == 'SENT':
                current['reconcile_misses'] = 0
            if outcome in ('RETRY', 'UNKNOWN'):
                delay = max(0.001, self.jitter(min(60, 2 ** min(row['attempts'], 6))))
                current['next_attempt_at'] = min(rr['deadline_at'], self.clock.now() + int(delay * 1_000_000))
            repo.save('outbox_events', current)
            audit(repo, self.clock, self.actor(repo, 'system', Role.SYSTEM), 'DELIVERY_' + outcome,
                  task['id'], request_id=rr['id'], attempt=current['attempts'], code=code)
            if outcome == 'FAILED':
                self.review_failure_gate(repo, task, code, 'FAILED')
            elif outcome == 'UNKNOWN' and rr.get('protocol_version', 'v1') != 'v2':
                self.escalate(repo, task, code, 'ESCALATED')
        return outcome


class ReviewerIntakeWorker(Services):
    """Durable Reviewer-side polling driver; it never owns the Hub outbox lease."""

    def __init__(self, *args, reviewer_actor_id, consumer, reconciler=None,
                 source='supervisor-poll'):
        super().__init__(*args)
        self.reviewer_actor_id = reviewer_actor_id
        self.consumer = consumer
        self.reconciler = reconciler
        self.source = source

    def _claim(self):
        with self.db.transaction() as repo:
            actor = self.actor(repo, self.reviewer_actor_id, Role.REVIEWER)
            for outbox in repo.find('outbox_events', status='SENT'):
                rr = repo.get('review_requests', outbox['review_request_id'])
                if rr['envelope']['expected_reviewer_actor_id'] != actor['id']:
                    continue
                task = repo.get('tasks', rr['task_id'])
                deduplication_key = digest([
                    rr['id'], rr['envelope']['input_sha256'],
                    rr['envelope']['profile_sha256'], actor['id'],
                ])
                rows = repo.find('intake_receipts', source=self.source,
                                 deduplication_key=deduplication_key)
                inactive = (rr['status'] not in ACTIVE_REQUEST
                            or task['active_rr_id'] != rr['id']
                            or task['state'] in TERMINAL or task.get('automation_frozen')
                            or task['state'] in ('PLAN_HUMAN_REVIEW', 'FINAL_HUMAN_REVIEW')
                            or self.clock.now() >= rr['deadline_at']
                            or self.clock.now() >= task['deadline_at'])
                if inactive:
                    if rows and rows[0]['status'] in ('READY', 'LEASED', 'UNKNOWN'):
                        receipt = rows[0]
                        receipt.update(status='FAILED', lease_token=None, lease_until=0,
                                       last_error_code='INTAKE_NO_LONGER_CURRENT',
                                       completed_at=self.clock.now())
                        repo.save('intake_receipts', receipt)
                        audit(repo, self.clock, actor, 'REVIEWER_INTAKE_FAILED', task['id'],
                              request_id=rr['id'], intake_id=receipt['id'],
                              code='INTAKE_NO_LONGER_CURRENT')
                    continue
                if actor.get('reviewer_type') == 'grok_bot':
                    routes = repo.find('grok_reviewer_routes', task_id=task['id'])
                    if not routes or routes[0]['reviewer_actor_id'] != actor['id']:
                        continue
                if not rows:
                    receipt = dict(
                        id='INT-' + deduplication_key, review_request_id=rr['id'],
                        source=self.source, deduplication_key=deduplication_key,
                        reviewer_actor_id=actor['id'],
                        input_hash=rr['envelope']['input_sha256'],
                        profile_hash=rr['envelope']['profile_sha256'], status='READY',
                        lease_token=None, lease_until=0, lease_generation=0,
                        attempts=0, created_at=self.clock.now())
                    repo.add('intake_receipts', receipt)
                    rows = [receipt]
                    audit(repo, self.clock, actor, 'REVIEWER_INTAKE_DISCOVERED', task['id'],
                          request_id=rr['id'], intake_id=receipt['id'])
                receipt = rows[0]
                ready = receipt['status'] == 'READY'
                expired = (receipt['status'] in ('LEASED', 'UNKNOWN')
                           and receipt['lease_until'] <= self.clock.now())
                if not (ready or expired):
                    continue
                claimed = {**receipt, 'status': 'LEASED', 'lease_token': uid('LEASE'),
                           'lease_until': self.clock.now() + self.settings.lease_seconds * 1_000_000,
                           'lease_generation': receipt['lease_generation'] + 1,
                           'attempts': receipt['attempts'] + 1}
                repo.compare_and_swap('intake_receipts', claimed,
                                      {'status': receipt['status'],
                                       'lease_generation': receipt['lease_generation']})
                return claimed, rr
        return None

    def run_one(self):
        claimed = self._claim()
        if claimed is None:
            return None
        receipt, rr = claimed
        try:
            result = True if self.reconciler and self.reconciler(rr) else self.consumer(rr)
            outcome, code = 'ACKED', None
            if result in (None, False):
                outcome, code = 'UNKNOWN', 'INTAKE_UNKNOWN'
        except RetryableDelivery:
            outcome, code = 'UNKNOWN', 'INTAKE_RETRYABLE'
        except HubError as exc:
            outcome, code = 'FAILED', exc.code
        except Exception:
            outcome, code = 'UNKNOWN', 'INTAKE_UNKNOWN'
        with self.db.transaction() as repo:
            current = repo.get('intake_receipts', receipt['id'])
            if (current['status'] != 'LEASED' or current['lease_token'] != receipt['lease_token']
                    or current['lease_generation'] != receipt['lease_generation']):
                return 'LEASE_LOST'
            task = repo.get('tasks', rr['task_id'])
            if (task.get('automation_frozen') or task['state'] in TERMINAL
                    or task['state'] in ('PLAN_HUMAN_REVIEW', 'FINAL_HUMAN_REVIEW')):
                outcome, code = 'FAILED', 'AUTOMATION_FROZEN'
            if outcome == 'UNKNOWN' and current['attempts'] >= self.settings.delivery_max_attempts:
                outcome, code = 'FAILED', 'INTAKE_EXHAUSTED'
            retry_at = (self.clock.now() + self.settings.lease_seconds * 1_000_000
                        if outcome == 'UNKNOWN' else 0)
            current.update(status=outcome, lease_token=None, lease_until=retry_at,
                           last_error_code=code, completed_at=self.clock.now())
            repo.save('intake_receipts', current)
            audit(repo, self.clock, self.actor(repo, self.reviewer_actor_id, Role.REVIEWER),
                  'REVIEWER_INTAKE_' + outcome, task['id'], request_id=rr['id'],
                  intake_id=current['id'], code=code)
        return outcome


class BindingRouteWorker:
    """Apply deterministic service configuration before external dispatch/projection."""

    def __init__(self, runtime, policy):
        self.runtime, self.policy = runtime, policy

    def run_one(self):
        if self.policy is None:
            return None
        with self.runtime.db.transaction() as repo:
            tasks = [task for task in repo.find('tasks')
                     if task['state'] not in TERMINAL
                     and task['state'] not in ('ESCALATED', 'BLOCKED',
                                                'PLAN_HUMAN_REVIEW', 'FINAL_HUMAN_REVIEW',
                                                'AWAITING_HUMAN_APPROVAL')
                     and not task.get('automation_frozen')]
        for task in tasks:
            config = self.policy(task)
            if not config:
                continue
            with self.runtime.db.transaction() as repo:
                binding = repo.find('github_bindings', task_id=task['id'])
                route = repo.find('grok_reviewer_routes', task_id=task['id'])
            changed = False
            reviewer_actor_id = config['reviewer_actor_id']
            if not binding:
                self.runtime.github_bindings.bind_pull_request(
                    repository_id=config['repository_id'],
                    repository_full_name=config['repository_full_name'],
                    pull_request_number=config['pull_request_number'], task_id=task['id'],
                    builder_actor_id=task['owner_id'], reviewer_actor_id=reviewer_actor_id,
                    hub_pointer_base=config.get('hub_pointer_base', 'hub://local'))
                changed = True
            with self.runtime.db.transaction() as repo:
                reviewer = repo.get('actors', reviewer_actor_id)
            if reviewer.get('reviewer_type') == 'grok_bot' and not route:
                self.runtime.hub.route_future_reviews(
                    task['owner_id'], task['id'], reviewer_actor_id, task['version'],
                    'supervisor-route:' + task['id'])
                changed = True
            if changed:
                return 'ENSURED'
        return None


class ProjectionWorker:
    def __init__(self, service, transport):
        self.service, self.transport = service, transport

    def run_one(self):
        with self.service.db.transaction() as repo:
            unknown = list(repo.find('github_comment_projections', status='UNKNOWN'))
        for row in unknown:
            if row.get('binding_id') is None or row.get('desired_body') is None:
                try:
                    self.service.enqueue_final_review(row['review_request_id'])
                except HubError:
                    continue
                return self.service.project_one(self.transport)
        return self.service.project_one(self.transport)


class Supervisor:
    """One bounded multi-worker scheduler with independent failure domains."""

    def __init__(self, *, binding_routes=None, recovery, dispatcher, intake, events,
                 projections=None, sleeper=time.sleep):
        self.workers = [
            ('binding_route', binding_routes and binding_routes.run_one),
            ('recovery', recovery.run_once),
            ('dispatch', dispatcher.dispatch_one),
            ('intake', intake.run_one),
            ('event_apply', events.handle_one),
            ('projection', projections and projections.run_one),
        ]
        self.sleeper = sleeper
        self.metrics = {name: {'runs': 0, 'successes': 0, 'last_result': None,
                               'last_error_code': None}
                        for name, worker in self.workers if worker is not None}

    def tick(self):
        results = {}
        for name, worker in self.workers:
            if worker is None:
                continue
            metric = self.metrics[name]
            metric['runs'] += 1
            try:
                value = worker()
                metric.update(successes=metric['successes'] + 1, last_result=value,
                              last_error_code=None)
                results[name] = value
            except Exception as exc:
                code = getattr(exc, 'code', type(exc).__name__)
                metric['last_error_code'] = code
                results[name] = {'error': code}
        return results

    @staticmethod
    def _made_progress(result):
        if isinstance(result, dict):
            if 'error' in result:
                return False
            return any(bool(value) for value in result.values())
        return result is not None

    def run_until_idle(self, max_cycles=100):
        if type(max_cycles) is not int or max_cycles < 1:
            raise ValueError('max_cycles must be a positive integer')
        history = []
        for _ in range(max_cycles):
            result = self.tick()
            history.append(result)
            if not any(self._made_progress(value) for value in result.values()):
                return history
        raise RuntimeError('Supervisor did not become idle within the bounded cycle limit')

    def run_forever(self, stop, interval_seconds=5):
        if not 0 < interval_seconds <= 5:
            raise ValueError('interval_seconds must be between 0 and 5')
        while not stop.is_set():
            self.tick()
            stop.wait(interval_seconds) if hasattr(stop, 'wait') else self.sleeper(interval_seconds)
