import random
from grokbuddy.domain.model import (HubError, Role, TERMINAL, ACTIVE_REQUEST, RetryableDelivery, DeliveryUnknown)
from .common import Services, uid, audit


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
                    self.escalate(repo, task, 'TASK_TIMEOUT')
                    count += 1
                    continue
                if task['active_rr_id']:
                    rr = repo.get('review_requests', task['active_rr_id'])
                    if rr['status'] in ACTIVE_REQUEST and self.clock.now() >= rr['deadline_at']:
                        self.escalate(repo, task, 'REVIEW_TIMEOUT', 'TIMED_OUT')
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
                ready = row['status'] in ('READY', 'RETRY') and row['next_attempt_at'] <= self.clock.now()
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
                    self.escalate(repo, task, reason, 'ESCALATED' if reason == 'TASK_TIMEOUT' else 'TIMED_OUT')
                    continue
                row.update(status='LEASED', lease_until=self.clock.now() + self.settings.lease_seconds * 1_000_000,
                           lease_token=uid('LEASE'), lease_generation=row.get('lease_generation', 0) + 1,
                           attempts=row['attempts'] + 1)
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
                if row['attempts'] > self.settings.delivery_max_attempts:
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
            outcome, code = 'UNKNOWN', 'DELIVERY_UNKNOWN'
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
            if outcome == 'RETRY':
                delay = max(0.001, self.jitter(min(60, 2 ** min(row['attempts'], 6))))
                current['next_attempt_at'] = min(rr['deadline_at'], self.clock.now() + int(delay * 1_000_000))
            repo.save('outbox_events', current)
            audit(repo, self.clock, self.actor(repo, 'system', Role.SYSTEM), 'DELIVERY_' + outcome,
                  task['id'], request_id=rr['id'], attempt=current['attempts'], code=code)
            if outcome in ('FAILED', 'UNKNOWN'):
                self.escalate(repo, task, code, 'FAILED' if outcome == 'FAILED' else 'ESCALATED')
        return outcome
