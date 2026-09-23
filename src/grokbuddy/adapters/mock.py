"""Reviewer simulation. Only queue operations and event generation; no Hub/Task access."""
from copy import deepcopy
import json
from uuid import uuid4

from grokbuddy.domain.model import DeliveryReceipt, NormalizedEvent, HubError
from grokbuddy.ports import ReviewQueue, Clock


class MockReviewerAdapter:
    SCENARIOS = {'PASS', 'NEEDS_CHANGES', 'BLOCK', 'TIMEOUT', 'INVALID_PAYLOAD', 'DUPLICATE_EVENT', 'FAILED'}

    def __init__(self, queue: ReviewQueue, clock: Clock, timestamp):
        self.queue, self.clock, self.timestamp = queue, clock, timestamp
        self.plans = {}

    def configure(self, request_id, scenario='PASS', *, findings=None, verifications=None, result=None):
        if scenario not in self.SCENARIOS:
            raise ValueError('Unsupported Mock scenario')
        self.plans[request_id] = dict(scenario=scenario, findings=findings, verifications=verifications, result=result)

    def submit_review_request(self, envelope, delivery_key):
        # Persist the evaluation job; no computation or completion is performed here.
        spec = deepcopy(self.plans.get(envelope['review_request_id'], {'scenario': 'PASS'}))
        self.queue.enqueue(delivery_key, {'request': deepcopy(envelope), 'spec': spec})
        return DeliveryReceipt('ACCEPTED')

    def get_delivery_status(self, delivery_key):
        return DeliveryReceipt('ACCEPTED' if self.queue.contains(delivery_key) else 'NOT_FOUND')

    def normalize_review_event(self, raw, verified_actor_id):
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError) as exc:
                raise HubError('Invalid event JSON') from exc
        required = {'event_id', 'event_type', 'source', 'task_id', 'review_request_id', 'review_id',
                    'correlation_id', 'deduplication_key', 'payload'}
        if not isinstance(raw, dict) or set(raw) != required:
            raise HubError('Invalid event envelope')
        if not all(isinstance(raw[k], str) and raw[k] for k in required - {'payload'}) or not isinstance(raw['payload'], dict):
            raise HubError('Invalid event fields')
        if raw['event_type'] not in ('ReviewStarted', 'ReviewCompleted', 'ReviewFailed'):
            raise HubError('Unknown event type')
        return NormalizedEvent(**deepcopy(raw), actor_id=verified_actor_id)

    def run_one(self, request_id=None):
        """Independent worker turn; a request call never invokes this method."""
        job = self.queue.take(request_id)
        if job is None:
            return None
        request, spec = job['envelope']['request'], job['envelope']['spec']
        scenario = spec['scenario']
        events = []
        if scenario != 'TIMEOUT':
            event_type = 'ReviewFailed' if scenario == 'FAILED' else 'ReviewCompleted'
            result = {'protocol_version': request['protocol_version']} if scenario == 'FAILED' else self._result(request, spec)
            raw = dict(event_id='EVT-' + str(uuid4()), event_type=event_type, source='mock',
                       task_id=request['task_id'], review_request_id=request['review_request_id'],
                       review_id=request['review_id'], correlation_id=request['review_request_id'],
                       deduplication_key=job['id'] + ':completed', payload=result)
            event = self.normalize_review_event(raw, request['expected_reviewer_actor_id'])
            events.append(event)
            if scenario == 'DUPLICATE_EVENT':
                events.append(event)
        self.queue.complete(job, events)
        return scenario

    def _result(self, request, spec):
        if spec.get('result') is not None:
            return deepcopy(spec['result'])
        fields = ('protocol_version', 'task_id', 'review_request_id', 'review_id', 'review_type',
                  'review_round', 'content_revision', 'review_profile', 'review_profile_version',
                  'profile_sha256', 'input_sha256')
        scenario = spec['scenario']
        verdict = scenario if scenario in ('PASS', 'NEEDS_CHANGES', 'BLOCK') else 'PASS'
        result = {k: request[k] for k in fields}
        if request['protocol_version'] == 'v2':
            result['expected_task_version'] = request['expected_task_version']
            if 'decision_policy_version' in request:
                result['decision_policy_version'] = request['decision_policy_version']
        result.update(verdict=verdict, summary='Local Mock evaluation: ' + scenario,
                      reviewer={'type': 'mock', 'id': request['expected_reviewer_actor_id']},
                      timestamp=self.timestamp(self.clock.now()))
        if request['protocol_version'] == 'v2':
            findings = spec.get('findings')
            if findings is None:
                findings = [] if verdict == 'PASS' else [dict(
                    external_finding_key='mock-risk', severity='HIGH', blocking=True,
                    category='MOCK_TEST', title='Mock finding',
                    description='Synthetic review risk',
                    evidence={'artifact_id': request['input_artifact_id'], 'locator': 'input',
                              'description': 'Synthetic evidence'},
                    impact='Requires remediation in the local test',
                    recommendation='Submit remediation evidence',
                    proposed_changes=['Apply the bounded mock remediation'],
                    scope={'files': ['local.txt']}, status='OPEN', actionable=True)]
            result.update(
                evidence=[{'artifact_id': request['input_artifact_id'], 'locator': 'input',
                           'description': 'Frozen review input'}],
                risks=[] if verdict == 'PASS' else [
                    {'code': 'MOCK_RISK', 'description': 'Mock requests bounded remediation',
                     'blocking': verdict == 'BLOCK', 'mitigation': 'Apply and verify the proposed change'}],
                recommendations=[] if verdict == 'PASS' else ['Address actionable findings'],
                proposed_changes=[] if verdict == 'PASS' else [
                    {'description': 'Apply the bounded mock remediation',
                     'scope': {'files': ['local.txt']}, 'rationale': 'Resolve the mock finding'}],
                findings=deepcopy(findings),
                verifications=deepcopy(spec.get('verifications') or []))
            if (request.get('decision_policy_version') == 'grokbuddy-v1-dual-round'
                    and request['review_round'] == 2 and verdict == 'BLOCK'):
                result['blocker_category'] = 'CORE_REQUIREMENT'
        elif request['review_type'] == 'PLAN_REVIEW':
            result.update(comments=[], suggestions=[], risks=[] if verdict == 'PASS' else [
                {'code': 'EVIDENCE_INSUFFICIENT', 'description': 'Mock requests more evidence', 'blocking': True}])
        else:
            findings = spec.get('findings')
            if findings is None:
                findings = [] if verdict == 'PASS' else [dict(external_finding_key='mock-risk',
                    severity='CRITICAL' if verdict == 'BLOCK' else 'HIGH', blocking=True,
                    category='MOCK_TEST', title='Mock finding', finding='Synthetic review risk',
                    evidence={'artifact_id': request['input_artifact_id'], 'locator': 'package', 'description': 'Synthetic evidence'},
                    impact='Requires remediation in the local test', recommendation='Submit remediation evidence')]
            result.update(findings=deepcopy(findings), verifications=deepcopy(spec.get('verifications') or []))
        if scenario == 'INVALID_PAYLOAD':
            result['protocol_version'] = 'unrecognized'
        return result
