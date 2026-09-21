"""Reproducible offline acceptance demo; not a client integration or production executor."""
from pathlib import Path
import json
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.infrastructure.clock import ManualClock


def main():
    directory = ROOT / 'var' / ('demo-' + str(uuid4()))
    runtime = LocalRuntime(directory, ROOT / 'docs/contracts', clock=ManualClock())
    hub = runtime.hub
    key = lambda: str(uuid4())
    task_id = hub.create_task('builder', 'Deliver an offline reviewed artifact', key())['id']
    task = lambda: hub.get_task(task_id)
    version = lambda: task()['version']
    trace = []

    def artifact(kind, text):
        return hub.submit_artifact('builder', task_id, kind, text.encode('utf-8'), key())

    def ref(identity):
        with runtime.db.transaction() as repo:
            row = repo.get('artifacts', identity)
        return {'artifact_id': identity, 'sha256': row['sha256']}

    def move(action):
        return hub.move('builder', task_id, action, version(), key())

    def review(kind, scenario, **options):
        receipt = hub.request_review('builder', task_id, kind, 'mock-reviewer', version(), key())
        assert receipt['status'] == 'PENDING'
        rr = receipt['review_request_id']
        trace.append({'step': 'request', 'receipt': receipt, 'task_state': task()['state']})
        runtime.mock.configure(rr, scenario, **options)
        trace.append({'step': 'dispatch', 'result': runtime.dispatcher.dispatch_one(), 'task_state': task()['state']})
        trace.append({'step': 'mock', 'result': runtime.mock.run_one(), 'task_state': task()['state']})
        trace.append({'step': 'event_handler', 'result': runtime.events.handle_one(), 'task_state': task()['state']})
        return rr

    def package():
        evidence = artifact('TEST_RESULT', 'Offline self-test passed for revision ' + str(task()['content_revision']))
        hub.self_test('builder', task_id, evidence['id'], True, version(), key())
        profile = hub.profile_snapshot('builder', task_id, key())
        diff = artifact('DIFF', 'Synthetic local diff only')
        manifest = dict(protocol_version='v1', task_id=task_id, content_revision=task()['content_revision'],
                        original_task=ref(task()['original_task_id']), approved_plan=ref(task()['approved_plan_id']),
                        change_scope='Offline demo', changed_files=['example.txt'], diff_artifact=ref(diff['id']),
                        test_results=[ref(evidence['id'])], self_test={'status':'PASS','summary':'Synthetic demo self-test'},
                        known_risks=[], unverified_items=['All external integrations'], review_profile='generic',
                        review_profile_version='1.0', profile_sha256=profile['sha256'], profile_artifact_id=profile['id'])
        hub.submit_final_package('builder', task_id, manifest, version(), key())

    for scenario in ('NEEDS_CHANGES', 'PASS'):
        move('begin_plan')
        plan = artifact('PLAN', 'Local plan ' + scenario)
        hub.submit_plan('builder', task_id, plan['id'], version(), key())
        review('PLAN_REVIEW', scenario)
    move('execute'); package(); review('FINAL_REVIEW', 'NEEDS_CHANGES')
    finding = hub.list_findings(task_id)[0]
    hub.respond_finding('builder', finding['id'], 'accept', None, version(), key())
    move('execute')
    evidence = artifact('DIFF', 'Corrected synthetic issue')
    hub.respond_finding('builder', finding['id'], 'fix', evidence['id'], version(), key())
    package()
    review('FINAL_REVIEW', 'PASS', verifications=[dict(finding_id=finding['id'], outcome='VERIFIED',
           evidence={'artifact_id':evidence['id'],'locator':'corrected diff','description':'Synthetic verification'},
           reason='Verified in the offline acceptance demo')])
    assert task()['state'] == 'DONE'
    assert hub.list_findings(task_id)[0]['id'] == finding['id']
    # Restart from disk: this reads actual committed state rather than in-memory objects.
    reopened = LocalRuntime(directory, ROOT / 'docs/contracts', clock=runtime.clock)
    assert reopened.hub.get_task(task_id)['state'] == 'DONE'
    output = {'scope':'LOCAL_MOCK_ONLY', 'external_integration_gate':'BLOCKED', 'task_id':task_id,
              'database':str(directory / 'hub.db'), 'task_state':task()['state'],
              'finding_id':finding['id'], 'finding_status':hub.list_findings(task_id)[0]['status'],
              'restart_verified':True, 'trace':trace, 'audit_count':len(hub.audit_log(task_id))}
    target = ROOT / 'docs/phase1-demo.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k != 'trace'}, ensure_ascii=False, indent=2))
    print('Evidence:', target)


if __name__ == '__main__':
    main()
