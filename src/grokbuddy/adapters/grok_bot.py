"""Grok Bot request carrier and strict normalization of authenticated returns.

GitHub Comment acceptance is transport acceptance, never a Grok verdict or run proof.
"""

from copy import deepcopy
import json
import re
from urllib.parse import urlsplit

from grokbuddy.adapters.github import GitHubCommentTransportError
from grokbuddy.domain.model import (ACTIVE_REQUEST, DeliveryReceipt, DeliveryUnknown, HubError,
                                   NormalizedEvent, RetryableDelivery)


_RUN = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")


class GrokBotReviewerAdapter:
    def __init__(self, db, transport, clock, *, reviewer_actor_id, agent_id, server_id,
                 public_base_url, http_intake=None):
        if not isinstance(public_base_url, str):
            raise HubError('Grok Reviewer public base must be an HTTPS origin')
        parsed = urlsplit(public_base_url)
        if (any(c in public_base_url for c in '\r\n\t')
                or parsed.scheme != 'https' or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise HubError('Grok Reviewer public base must be an HTTPS origin')
        self.db, self.transport, self.clock = db, transport, clock
        self.reviewer_actor_id = reviewer_actor_id
        self.agent_id, self.server_id = agent_id, server_id
        self.public_base_url = public_base_url.rstrip('/')
        self.http_intake = http_intake

    @staticmethod
    def _marker(request_id):
        if not isinstance(request_id, str) or not _RUN.fullmatch(request_id):
            raise HubError('Review request ID is invalid')
        return f'<!-- grokbuddy-grok-request:{request_id} -->'

    def _target(self, request_id):
        with self.db.transaction() as repo:
            rr = repo.get('review_requests', request_id)
            task = repo.get('tasks', rr['task_id'])
            actor = repo.get('actors', self.reviewer_actor_id)
            if (rr['envelope']['expected_reviewer_actor_id'] != self.reviewer_actor_id
                    or rr['status'] not in ACTIVE_REQUEST
                    or task['active_rr_id'] != rr['id']
                    or self.clock.now() >= rr['deadline_at']
                    or self.clock.now() >= task['deadline_at']
                    or actor['reviewer_type'] != 'grok_bot'
                    or actor.get('agent_id') != self.agent_id
                    or actor.get('server_id') != self.server_id):
                raise HubError('Review request is not routed to configured Grok Reviewer')
            route = repo.find('grok_reviewer_routes', task_id=rr['task_id'])
            binding = repo.find('github_bindings', task_id=rr['task_id'])
            channel = rr.get('delivery_channel')
            if channel == 'REVIEWER_HTTP':
                if rr.get('protocol_version') != 'v2':
                    raise HubError('Frozen HTTP Reviewer delivery contract is invalid')
                return None, rr
            if (channel not in (None, 'GITHUB_COMMENT')
                    or len(route) != 1 or route[0]['reviewer_actor_id'] != self.reviewer_actor_id
                    or len(binding) != 1 or route[0].get('binding_id') != binding[0]['id']):
                raise HubError('Grok Reviewer route or PR binding is missing')
            return binding[0], rr

    def _body(self, envelope, delivery_key):
        return '\n'.join((self._marker(delivery_key), '[AI-COLLAB v1] Grok Reviewer request',
                          f'review_request_id={delivery_key}',
                          f'review_id={envelope["review_id"]}',
                          f'reviewer_actor_id={self.reviewer_actor_id}',
                          f'request_pointer={self.public_base_url}/reviewer/requests/{delivery_key}'))

    def get_delivery_status(self, delivery_key):
        binding, rr = self._target(delivery_key)
        if binding is None:
            if self.http_intake is None:
                raise HubError('HTTP Reviewer delivery is not configured')
            return self.http_intake.delivery_status(delivery_key)
        try:
            comment = self.transport.find_comment(binding, self._marker(delivery_key))
        except GitHubCommentTransportError as exc:
            if exc.retryable:
                raise RetryableDelivery('Grok request carrier lookup failed') from exc
            raise HubError('Grok request carrier lookup was rejected') from exc
        if comment and comment.get('body') != self._body(rr['envelope'], delivery_key):
            raise DeliveryUnknown('Grok request carrier marker conflicts with frozen request')
        return DeliveryReceipt('ACCEPTED' if comment else 'NOT_FOUND')

    def submit_review_request(self, envelope, delivery_key):
        if envelope.get('review_request_id') != delivery_key:
            raise HubError('Delivery key does not match frozen request')
        binding, rr = self._target(delivery_key)
        if envelope != rr['envelope']:
            raise HubError('Submitted envelope differs from frozen request')
        if binding is None:
            if self.http_intake is None:
                raise HubError('HTTP Reviewer delivery is not configured')
            self.http_intake.publish(delivery_key)
            return DeliveryReceipt('ACCEPTED')
        marker = self._marker(delivery_key)
        body = self._body(envelope, delivery_key)
        if len(body.encode('utf-8')) > 4096:
            raise HubError('Grok request Comment exceeds control-message limit')
        try:
            comment = self.transport.create_comment(binding, body)
        except GitHubCommentTransportError as exc:
            # POST may have succeeded before its receipt was lost. Stop and reconcile.
            raise DeliveryUnknown('Grok request carrier delivery is uncertain') from exc
        if comment.get('body') != body:
            raise DeliveryUnknown('Grok request carrier receipt is invalid')
        return DeliveryReceipt('ACCEPTED')

    def normalize_review_event(self, raw, verified_actor_id):
        if verified_actor_id != self.reviewer_actor_id:
            raise HubError('Authenticated Reviewer does not match Grok route')
        if isinstance(raw, (str, bytes)):
            try:
                raw = json.loads(raw)
            except (UnicodeError, ValueError, TypeError) as exc:
                raise HubError('Invalid Grok event JSON') from exc
        required = {'event_id', 'event_type', 'source', 'task_id', 'review_request_id',
                    'review_id', 'correlation_id', 'deduplication_key', 'payload', 'execution'}
        if not isinstance(raw, dict) or set(raw) != required:
            raise HubError('Invalid Grok event envelope')
        if (raw['source'] != 'grok_bot'
                or raw['event_type'] not in ('ReviewStarted', 'ReviewCompleted', 'ReviewFailed')
                or not all(isinstance(raw[k], str) and _RUN.fullmatch(raw[k]) for k in
                           required - {'payload', 'execution', 'source', 'event_type'})
                or not isinstance(raw['payload'], dict)):
            raise HubError('Invalid Grok event fields')
        execution = raw['execution']
        if (not isinstance(execution, dict)
                or set(execution) != {'agent_id', 'server_id', 'run_id'}
                or execution['agent_id'] != self.agent_id
                or execution['server_id'] != self.server_id
                or not isinstance(execution['run_id'], str)
                or not _RUN.fullmatch(execution['run_id'])):
            raise HubError('Grok execution identity does not match configured Reviewer')
        values = {k: deepcopy(raw[k]) for k in required - {'execution'}}
        return NormalizedEvent(**values, actor_id=verified_actor_id,
                               execution_identity=deepcopy(execution))
