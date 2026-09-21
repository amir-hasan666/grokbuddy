import json
from grokbuddy.domain.model import HubError
import pytest
from conftest import Flow, CONTRACTS
from grokbuddy.infrastructure.runtime import LocalRuntime


def test_asynchronous_path_has_observable_boundaries(flow):
    flow.plan()
    rr = flow.request()
    assert flow.task['state'] == 'PLAN_REVIEW_PENDING'
    assert flow.rows('review_requests', id=rr)[0]['status'] == 'PENDING'
    assert flow.rows('outbox_events')[0]['status'] == 'READY'
    assert not flow.rows('mock_jobs') and not flow.rows('reviews')
    assert flow.r.dispatcher.dispatch_one() == 'SENT'
    assert flow.rows('mock_jobs')[0]['status'] == 'READY'
    assert not flow.rows('inbox_events') and flow.task['state'] == 'PLAN_REVIEW_PENDING'
    assert flow.r.mock.run_one() == 'PASS'
    assert flow.rows('inbox_events')[0]['status'] == 'READY'
    assert not flow.rows('reviews') and flow.task['state'] == 'PLAN_REVIEW_PENDING'
    assert flow.r.events.handle_one() == 'APPLIED'
    assert flow.task['state'] == 'PLAN_APPROVED'
    assert flow.h.get_review(rr)['request']['status'] == 'COMPLETED'


def test_plan_changes_second_round_pass(flow):
    flow.plan()
    first = flow.request(scenario='NEEDS_CHANGES')
    flow.drive()
    assert flow.task['state'] == 'PLAN_CHANGES_REQUIRED'
    flow.plan()
    second = flow.request()
    flow.drive()
    assert flow.task['state'] == 'PLAN_APPROVED'
    assert flow.h.get_review(second)['request']['review_round'] == 2
    assert flow.h.get_review(first)['review']['effective_verdict'] == 'NEEDS_CHANGES'


def test_final_finding_stable_id_fix_verify(flow):
    flow.executing()
    flow.package()
    first = flow.request('FINAL_REVIEW', 'NEEDS_CHANGES')
    flow.drive()
    assert flow.task['state'] == 'FINAL_CHANGES_REQUIRED'
    finding = flow.h.list_findings(flow.id)[0]
    fid = finding['id']
    old_review = flow.h.get_review(first)['review']
    flow.h.respond_finding('builder', fid, 'accept', None, flow.version, flow.key())
    flow.move('execute')
    evidence = flow.artifact('DIFF', 'Actual remediation evidence')
    flow.h.respond_finding('builder', fid, 'fix', evidence['id'], flow.version, flow.key())
    assert len(flow.rows('review_rounds', task_id=flow.id)) == 2  # plan + first final, not accept/fix
    flow.package()
    verification = {'finding_id': fid, 'outcome': 'VERIFIED', 'reason': 'Retested corrected behavior',
                    'evidence': {'artifact_id': evidence['id'], 'locator': 'fix', 'description': 'Local verification'}}
    flow.request('FINAL_REVIEW', verifications=[verification])
    flow.drive()
    assert flow.task['state'] == 'DONE'
    assert flow.h.list_findings(flow.id)[0]['id'] == fid
    assert flow.h.list_findings(flow.id)[0]['status'] == 'VERIFIED'
    assert flow.h.get_review(first)['review'] == old_review
    assert len(flow.rows('finding_events', finding_id=fid)) == 4


def test_unresolved_prior_finding_prevents_empty_pass(flow):
    flow.executing()
    flow.package()
    flow.request('FINAL_REVIEW', 'NEEDS_CHANGES')
    flow.drive()
    flow.package()
    rr = flow.request('FINAL_REVIEW', 'PASS')
    flow.drive()
    assert flow.h.get_review(rr)['review']['effective_verdict'] == 'NEEDS_CHANGES'
    assert flow.task['state'] == 'FINAL_CHANGES_REQUIRED'
    assert any(a['action'] == 'VERDICT_MISMATCH' for a in flow.h.audit_log(flow.id))


def test_critical_block_waive_and_resume(flow):
    flow.executing()
    flow.package()
    rr = flow.request('FINAL_REVIEW', 'BLOCK')
    flow.drive()
    assert flow.task['state'] == 'BLOCKED'
    assert flow.h.get_review(rr)['review']['effective_verdict'] == 'BLOCK'
    fid = flow.h.list_findings(flow.id)[0]['id']
    flow.h.waive_finding('human', fid, 'Risk accepted for this test scope', flow.version, flow.key())
    flow.h.resume('human', flow.id, 'FINAL_REVIEW', 3, flow.r.clock.now() + 60_000_000,
                  'Resume after explicit waiver', flow.version, flow.key())
    flow.package()
    flow.request('FINAL_REVIEW')
    flow.drive()
    assert flow.task['state'] == 'DONE'
    assert flow.h.list_findings(flow.id)[0]['status'] == 'WAIVED_BY_HUMAN'


@pytest.mark.parametrize('outcome,expected', [('VERIFIED', 'VERIFIED'), ('REOPENED', 'OPEN')])
def test_reject_with_evidence_requires_reviewer(flow, outcome, expected):
    flow.executing(); flow.package(); flow.request('FINAL_REVIEW', 'NEEDS_CHANGES'); flow.drive()
    finding = flow.h.list_findings(flow.id)[0]
    evidence = flow.artifact()
    rounds = len(flow.rows('review_rounds'))
    flow.h.respond_finding('builder', finding['id'], 'reject', evidence['id'], flow.version, flow.key())
    assert len(flow.rows('review_rounds')) == rounds
    flow.package()
    flow.request('FINAL_REVIEW', verifications=[{'finding_id': finding['id'], 'outcome': outcome,
                 'evidence': {'artifact_id': evidence['id'], 'locator': 'case', 'description': 'Counterexample'}, 'reason': 'Re-evaluated'}])
    flow.drive()
    assert flow.h.list_findings(flow.id)[0]['status'] == expected
    assert (flow.task['state'] == 'DONE') == (outcome == 'VERIFIED')


def test_restart_recovers_outbox_job_inbox_and_result(flow):
    flow.plan(); rr = flow.request()
    def restart():
        runtime = LocalRuntime(flow.r.directory, CONTRACTS, clock=flow.r.clock)
        flow.r, flow.h = runtime, runtime.hub
    restart()
    assert flow.r.dispatcher.dispatch_one() == 'SENT'
    restart()
    assert flow.r.mock.run_one() == 'PASS'
    restart()
    assert flow.r.events.handle_one() == 'APPLIED'
    restart()
    assert flow.task['state'] == 'PLAN_APPROVED'
    assert flow.h.get_review(rr)['review']['effective_verdict'] == 'PASS'


def test_failed_self_test_cannot_request_final(flow):
    flow.executing()
    result = flow.artifact('TEST_RESULT', 'Tests failed')
    flow.h.self_test('builder', flow.id, result['id'], False, flow.version, flow.key())
    assert flow.task['state'] == 'EXECUTING'
    with pytest.raises(HubError):
        flow.request('FINAL_REVIEW')


def test_profile_snapshot_is_stable(flow):
    flow.plan(); rr = flow.request()
    request = flow.h.get_review(rr)['request']
    snapshot = flow.rows('artifacts', id=request['envelope']['profile_artifact_id'])[0]
    assert snapshot['sha256'] == request['envelope']['profile_sha256']
    assert json.loads(flow.r.store.read(snapshot['storage_pointer'], snapshot['sha256'], snapshot['size_bytes']))
