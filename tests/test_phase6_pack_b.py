"""Phase 6 Pack B probes.  Every test uses a disposable local Hub and no network."""

from copy import deepcopy
import hashlib
import hmac
from uuid import uuid4

import pytest
from mcp import Client

from conftest import CONTRACTS
from grokbuddy.application.common import canonical, uid
from grokbuddy.application.trigger import PHRASE
from grokbuddy.domain.model import Conflict, NormalizedEvent
from grokbuddy.infrastructure.clock import ManualClock
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.interfaces.gateway import ClientGateway
from grokbuddy.interfaces.worker_mcp import create_worker_mcp_server


TRIGGER_KEY = b'phase6-pack-b-isolated-trigger-key-32-bytes'


def key():
    return str(uuid4())


class V2Flow:
    def __init__(self, tmp_path):
        self.r = LocalRuntime(tmp_path, CONTRACTS, clock=ManualClock(),
                              trigger_source_key=TRIGGER_KEY)
        message = {
            'principal_id': 'workbuddy-ingress',
            'conversation_id': key(),
            'message_id': key(),
            'turn_id': key(),
            'message_role': 'user',
            'issued_at': self.r.clock.now(),
            'segments': [{'source': 'user_body', 'text': PHRASE + '，执行 Pack B 隔离测试'}],
        }
        body = ''.join(item['text'] for item in message['segments'])
        raw = body.encode('utf-8')
        start = raw.index(PHRASE.encode('utf-8'))
        evidence = {
            'message': message,
            'signature': hmac.new(TRIGGER_KEY, canonical(message), hashlib.sha256).hexdigest(),
            'body_sha256': hashlib.sha256(raw).hexdigest(),
            'phrase': PHRASE,
            'start_byte': start,
            'end_byte': start + len(PHRASE.encode('utf-8')),
        }
        self.owner = 'workbuddy-ingress'
        self.task_id = self.r.hub.create_task(self.owner, body, key(), trigger_evidence=evidence)['id']

    @property
    def task(self):
        return self.r.hub.get_task(self.task_id)

    @property
    def version(self):
        return self.task['version']

    def rows(self, table, **filters):
        with self.r.db.transaction() as repo:
            return repo.find(table, **filters)

    def artifact(self, kind='EVIDENCE', text='phase6 evidence', actor=None):
        return self.r.hub.submit_artifact(actor or self.owner, self.task_id, kind,
                                          text.encode('utf-8'), key())

    def plan(self, text='Approved Pack B plan', scope=None):
        if self.task['state'] in ('NEW', 'PLAN_CHANGES_REQUIRED'):
            self.r.hub.move(self.owner, self.task_id, 'begin_plan', self.version, key())
        artifact = self.artifact('PLAN', text + ' ' + key())
        return self.r.hub.submit_plan(
            self.owner, self.task_id, artifact['id'], self.version, key(),
            approved_scope=scope or {'summary': 'Pack B bounded scope', 'files': ['local.txt']})

    def request(self, kind='PLAN_REVIEW', scenario='PASS', **configuration):
        receipt = self.r.hub.request_review(
            self.owner, self.task_id, kind, 'mock-reviewer', self.version, key())
        self.r.mock.configure(receipt['review_request_id'], scenario, **configuration)
        return receipt['review_request_id']

    def drive(self):
        result = self.r.tick()
        while self.r.events.handle_one() is not None:
            pass
        return result

    def approve_plan(self):
        self.plan()
        rr = self.request()
        self.drive()
        assert self.task['state'] == 'PLAN_APPROVED'
        return rr

    def begin_execution(self):
        self.r.hub.move(self.owner, self.task_id, 'execute', self.version, key())
        assignment = self.rows('worker_assignments', task_id=self.task_id)[-1]
        assert assignment['status'] == 'OFFERED'
        return assignment

    def complete_worker(self):
        available = self.r.hub.list_available_worker_tasks('workbuddy-worker')
        offered = [item for item in available if item['task_id'] == self.task_id][0]
        claimed = self.r.hub.claim_task('workbuddy-worker', self.task_id,
                                        offered['version'], key())
        uploaded = ClientGateway(self.r, 'workbuddy-worker').invoke('submit_artifact', {
            'task_id': self.task_id,
            'artifact_type': 'EVIDENCE',
            'content_text': 'Worker completion evidence ' + key(),
            'idempotency_key': key(),
        })
        progress = self.r.hub.report_worker_progress(
            'workbuddy-worker', self.task_id, 'Bounded implementation completed', key())
        completed = self.r.hub.complete_worker_task(
            'workbuddy-worker', self.task_id, uploaded['id'], progress['version'], key())
        return completed

    def package(self):
        test = self.artifact('TEST_RESULT', 'Pack B tests passed ' + key())
        self.r.hub.self_test(self.owner, self.task_id, test['id'], True, self.version, key())
        profile = self.r.hub.profile_snapshot(self.owner, self.task_id, key())
        diff = self.artifact('DIFF', 'bounded diff ' + key())
        task = self.task

        def ref(artifact_id):
            artifact = self.r.hub.get_artifact(artifact_id)
            return {'artifact_id': artifact_id, 'sha256': artifact['sha256']}

        package = {
            'protocol_version': 'v1',
            'task_id': self.task_id,
            'content_revision': task['content_revision'],
            'original_task': ref(task['original_task_id']),
            'approved_plan': ref(task['approved_plan_id']),
            'change_scope': 'Approved Pack B scope',
            'changed_files': ['local.txt'],
            'diff_artifact': ref(diff['id']),
            'test_results': [ref(test['id'])],
            'self_test': {'status': 'PASS', 'summary': 'Pack B isolated tests passed'},
            'known_risks': [],
            'unverified_items': ['External providers are outside Pack B'],
            'review_profile': task['profile'],
            'review_profile_version': task['profile_version'],
            'profile_sha256': profile['sha256'],
            'profile_artifact_id': profile['id'],
        }
        if task.get('decision_policy_version') == 'grokbuddy-v1-dual-round':
            generated = self.artifact('SOURCE_FILE', 'generated local file ' + key())
            package['operation_method'] = 'Run the bounded local change.'
            package['generated_files'] = [
                {'path': 'local.txt', **ref(generated['id'])}
            ]
        return self.r.hub.submit_final_package(
            self.owner, self.task_id, package, self.version, key())

    def to_final_review(self, scenario='PASS', **configuration):
        self.approve_plan()
        self.begin_execution()
        self.complete_worker()
        self.package()
        rr = self.request('FINAL_REVIEW', scenario, **configuration)
        self.drive()
        return rr

    def fix_current_open_finding(self):
        finding = [item for item in self.r.hub.list_actionable_findings(self.task_id)
                   if item['status'] == 'OPEN'][-1]
        self.r.hub.respond_finding(self.owner, finding['id'], 'accept', None,
                                   self.version, key())
        response = self.r.hub.begin_final_fix(
            self.owner, self.task_id, [finding['id']], {'files': ['local.txt']},
            self.version, key())
        assert response['status'] == 'EXECUTING'
        completed = self.complete_worker()
        self.r.hub.respond_finding(
            self.owner, finding['id'], 'fix', completed['completion_artifact_id'],
            self.version, key())
        return finding['id']


def event_for(flow, rr, payload, dedup='stable-result', kind='ReviewCompleted'):
    request = flow.r.hub.get_review(rr)['request']['envelope']
    return NormalizedEvent(
        uid('EVT'), kind, 'pack-b-test', 'mock-reviewer', flow.task_id, rr,
        request['review_id'], rr, dedup, payload)


def test_v2_plan_apply_persists_immutable_snapshot_and_actionable_query(tmp_path):
    flow = V2Flow(tmp_path / 'plan-apply')
    flow.plan()
    rr = flow.request(scenario='NEEDS_CHANGES')
    flow.drive()

    assert flow.task['state'] == 'PLAN_CHANGES_REQUIRED'
    review = flow.r.hub.get_review(rr)
    assert review['review']['protocol_version'] == 'v2'
    assert review['result']['verdict'] == 'NEEDS_CHANGES'
    assert review['result']['evidence'] and review['result']['risks']
    assert review['result']['recommendations'] and review['result']['proposed_changes']
    findings = flow.r.hub.list_actionable_findings(flow.task_id, rr)
    assert len(findings) == 1
    assert findings[0]['id'] == review['result']['findings'][0]['finding_id']
    assert findings[0]['review_type'] == 'PLAN_REVIEW'


@pytest.mark.parametrize('mutation', ['empty-findings', 'missing-field'])
def test_v2_result_fail_closed_without_task_rr_finding_side_effects(tmp_path, mutation):
    flow = V2Flow(tmp_path / mutation)
    flow.plan()
    rr = flow.request()
    request = flow.r.hub.get_review(rr)['request']['envelope']
    payload = flow.r.mock._result(request, {'scenario': 'NEEDS_CHANGES'})
    if mutation == 'empty-findings':
        payload['findings'] = []
    else:
        del payload['recommendations']
    before = deepcopy(flow.task)
    flow.r.events.ingest(event_for(flow, rr, payload, dedup=mutation))
    assert flow.r.events.handle_one() == 'REJECTED'
    assert flow.task == before
    assert flow.r.hub.get_review(rr)['request']['status'] == 'PENDING'
    assert not flow.rows('reviews') and not flow.rows('review_findings')


def test_ingress_deduplicates_before_artifact_and_rejects_hash_conflict(tmp_path):
    flow = V2Flow(tmp_path / 'ingress-dedup')
    flow.plan()
    rr = flow.request()
    request = flow.r.hub.get_review(rr)['request']['envelope']
    payload = flow.r.mock._result(request, {'scenario': 'PASS'})
    event = event_for(flow, rr, payload)
    before = len(flow.rows('artifacts'))
    first = flow.r.events.ingest(event)
    assert flow.r.events.ingest(event) == first
    assert len(flow.rows('artifacts')) == before + 1
    assert len(flow.rows('inbox_events')) == 1
    changed = deepcopy(payload)
    changed['summary'] = 'conflicting payload under one ingress key'
    with pytest.raises(Conflict, match='Deduplication key reused'):
        flow.r.events.ingest(event_for(flow, rr, changed))
    assert len(flow.rows('artifacts')) == before + 1
    assert flow.r.events.handle_one() == 'APPLIED'
    assert flow.task['state'] == 'PLAN_APPROVED'


def test_wrong_request_and_stale_task_version_callbacks_do_not_mutate_business_state(tmp_path):
    flow = V2Flow(tmp_path / 'invalid-callbacks')
    flow.plan()
    rr = flow.request()
    request = flow.r.hub.get_review(rr)['request']['envelope']
    payload = flow.r.mock._result(request, {'scenario': 'PASS'})
    before = deepcopy(flow.task)
    wrong_rr = 'RR-' + str(uuid4())
    invalid = NormalizedEvent(uid('EVT'), 'ReviewCompleted', 'pack-b-test', 'mock-reviewer',
                              flow.task_id, wrong_rr, request['review_id'], wrong_rr,
                              'wrong-review-request', payload)
    flow.r.events.ingest(invalid)
    assert flow.r.events.handle_one() == 'REJECTED'
    assert flow.task == before
    assert flow.r.hub.get_review(rr)['request']['status'] == 'PENDING'
    assert not flow.rows('reviews') and not flow.rows('review_findings')

    stale = deepcopy(payload)
    stale['expected_task_version'] -= 1
    flow.r.events.ingest(event_for(flow, rr, stale, dedup='stale-task-version'))
    assert flow.r.events.handle_one() == 'REJECTED'
    assert flow.task == before
    assert not flow.rows('reviews') and not flow.rows('review_findings')


def test_plan_round_guard_revision_counter_and_gate_late_event(tmp_path):
    flow = V2Flow(tmp_path / 'plan-rounds')
    flow.plan()
    first = flow.request(scenario='NEEDS_CHANGES')
    flow.drive()
    finding = flow.r.hub.list_actionable_findings(flow.task_id, first)[0]
    flow.r.hub.respond_finding(flow.owner, finding['id'], 'accept', None, flow.version, key())
    flow.plan('Revised approved plan')
    fix = flow.artifact('DIFF', 'plan finding correction')
    flow.r.hub.respond_finding(flow.owner, finding['id'], 'fix', fix['id'], flow.version, key())
    assert flow.task['revision_round'] == 1
    second = flow.request(scenario='BLOCK')
    flow.drive()
    assert flow.task['state'] == 'PLAN_HUMAN_REVIEW'
    assert flow.task['automation_frozen'] is True
    assert flow.task['gate_reason'] == 'ROUND_LIMIT'
    assert len(flow.rows('review_requests', review_type='PLAN_REVIEW')) == 2

    request = flow.r.hub.get_review(second)['request']['envelope']
    late = event_for(flow, second, {'protocol_version': 'v2'},
                     dedup='late-after-plan-gate', kind='ReviewStarted')
    before = deepcopy(flow.task)
    flow.r.events.ingest(late)
    assert flow.r.events.handle_one() == 'LATE_EVENT'
    assert flow.task == before
    assert request['protocol_version'] == 'v2'


def test_plan_changes_revision_second_review_passes_only_after_verification(tmp_path):
    flow = V2Flow(tmp_path / 'plan-revision-pass')
    flow.plan()
    first = flow.request(scenario='NEEDS_CHANGES')
    flow.drive()
    finding = flow.r.hub.list_actionable_findings(flow.task_id, first)[0]
    flow.r.hub.respond_finding(flow.owner, finding['id'], 'accept', None, flow.version, key())
    flow.plan('Verified revised plan')
    evidence = flow.artifact('DIFF', 'plan revision evidence')
    flow.r.hub.respond_finding(flow.owner, finding['id'], 'fix', evidence['id'], flow.version, key())
    verification = {
        'finding_id': finding['id'], 'outcome': 'VERIFIED',
        'evidence': {'artifact_id': evidence['id'], 'locator': 'plan',
                     'description': 'Revised Plan closes the finding'},
        'reason': 'Revised Plan was re-evaluated',
    }
    second = flow.request(scenario='PASS', findings=[], verifications=[verification])
    flow.drive()
    assert flow.task['state'] == 'PLAN_APPROVED'
    assert flow.task['revision_round'] == 1
    assert flow.r.hub.get_review(second)['request']['review_round'] == 2
    assert flow.r.hub.list_actionable_findings(flow.task_id) == []


def test_same_task_worker_completion_is_not_done_and_final_pass_owns_completion(tmp_path):
    flow = V2Flow(tmp_path / 'same-task')
    flow.approve_plan()
    owner = flow.task['owner_id']
    assignment = flow.begin_execution()
    assert assignment['approved_plan_artifact_id'] == flow.task['approved_plan_id']
    assert assignment['approved_scope_hash'] == flow.task['approved_scope_hash']
    completed = flow.complete_worker()
    assert completed['status'] == 'COMPLETED'
    assert completed['task_state'] == 'EXECUTING'
    assert flow.task['state'] == 'EXECUTING'
    assert flow.task['owner_id'] == owner == flow.owner

    flow.package()
    rr = flow.request('FINAL_REVIEW', 'PASS')
    flow.drive()
    assert flow.task['state'] == 'DONE'
    assert flow.task['completion_basis'] == 'FINAL_REVIEW_PASS'
    intents = flow.rows('github_comment_projections', review_id=flow.r.hub.get_review(rr)['review']['id'])
    assert len(intents) == 1 and intents[0]['status'] == 'UNKNOWN'
    assert intents[0]['frozen_review_hash'] == flow.r.hub.get_review(rr)['review']['result_hash']


@pytest.mark.anyio
async def test_worker_mcp_uses_v2_assignment_without_owner_transfer(tmp_path):
    flow = V2Flow(tmp_path / 'worker-mcp-assignment')
    flow.approve_plan()
    flow.begin_execution()
    async with Client(create_worker_mcp_server(flow.r), mode='legacy', raise_exceptions=True) as client:
        available = (await client.call_tool('list_available_tasks', {})).structured_content['result']
        offered = [item for item in available if item['task_id'] == flow.task_id][0]
        claimed = (await client.call_tool('claim_task', {
            'task_id': flow.task_id, 'expected_version': offered['version'],
            'idempotency_key': key()})).structured_content
        uploaded = (await client.call_tool('submit_artifact', {
            'task_id': flow.task_id, 'artifact_type': 'EVIDENCE',
            'content_text': 'formal assignment evidence',
            'idempotency_key': key()})).structured_content
        progress = (await client.call_tool('report_progress', {
            'task_id': flow.task_id, 'summary': 'formal assignment complete',
            'idempotency_key': key()})).structured_content
        completed = (await client.call_tool('complete_task', {
            'task_id': flow.task_id, 'artifact_id': uploaded['id'],
            'expected_version': progress['version'],
            'idempotency_key': key()})).structured_content
    assert claimed['worker_principal_id'] == 'workbuddy-worker'
    assert completed['status'] == 'COMPLETED'
    assert completed['task_state'] == 'EXECUTING'
    assert flow.task['owner_id'] == flow.owner


def test_final_fix_scope_escape_returns_to_planning(tmp_path):
    flow = V2Flow(tmp_path / 'scope-escape')
    flow.to_final_review('NEEDS_CHANGES')
    finding = flow.r.hub.list_actionable_findings(flow.task_id)[0]
    before_assignments = len(flow.rows('worker_assignments', task_id=flow.task_id))
    response = flow.r.hub.begin_final_fix(
        flow.owner, flow.task_id, [finding['id']], {'files': ['outside-approved-scope.py']},
        flow.version, key())
    assert response['status'] == 'PLAN_CHANGE_REQUIRED'
    assert flow.task['state'] == 'PLANNING'
    assert flow.task['approved_plan_id'] is None
    assert len(flow.rows('worker_assignments', task_id=flow.task_id)) == before_assignments


def test_final_changes_fix_and_re_review_pass_on_same_task(tmp_path):
    flow = V2Flow(tmp_path / 'final-fix-pass')
    flow.to_final_review('NEEDS_CHANGES')
    finding_id = flow.fix_current_open_finding()
    fixed = [item for item in flow.r.hub.list_actionable_findings(flow.task_id)
             if item['id'] == finding_id][0]
    completion = flow.r.hub.get_artifact(
        flow.rows('worker_assignments', task_id=flow.task_id)[-1]['completion_artifact_id'])
    flow.package()
    verification = {
        'finding_id': finding_id, 'outcome': 'VERIFIED',
        'evidence': {'artifact_id': completion['id'], 'locator': 'worker-completion',
                     'description': 'Worker completion evidence was rechecked'},
        'reason': 'The bounded Final fix passed re-review',
    }
    rr = flow.request('FINAL_REVIEW', 'PASS', findings=[], verifications=[verification])
    flow.drive()
    assert fixed['status'] == 'FIXED'
    assert flow.task['state'] == 'DONE'
    assert flow.task['completion_basis'] == 'FINAL_REVIEW_PASS'
    assert flow.r.hub.get_review(rr)['request']['review_round'] == 2
    assert flow.r.hub.list_actionable_findings(flow.task_id) == []


def test_final_round_guard_uses_same_task_assignments_and_revision_semantics(tmp_path):
    flow = V2Flow(tmp_path / 'final-rounds')
    flow.to_final_review('NEEDS_CHANGES')
    flow.fix_current_open_finding()
    assert flow.task['state'] == 'EXECUTING'
    flow.package()
    assert flow.task['revision_round'] == 1
    flow.request('FINAL_REVIEW', 'BLOCK')
    flow.drive()
    assert flow.task['state'] == 'FINAL_HUMAN_REVIEW'
    assert flow.task['automation_frozen'] is True
    assert len(flow.rows('review_requests', review_type='FINAL_REVIEW')) == 2
    assignments = flow.rows('worker_assignments', task_id=flow.task_id)
    assert [item['generation'] for item in assignments] == [1, 2]
    assert flow.task['completion_basis'] is None
