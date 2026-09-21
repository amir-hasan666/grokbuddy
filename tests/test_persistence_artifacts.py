from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import sqlite3
import pytest

from conftest import Flow, CONTRACTS
from grokbuddy.domain.model import HubError, Conflict, Settings
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.infrastructure.clock import ManualClock
from grokbuddy.adapters.artifact import FileArtifactStore
from test_events import event_for


def test_command_replay_different_body_and_stale_version(flow):
    key = flow.key()
    first = flow.h.create_task('builder', 'Idempotent task', key)
    assert flow.h.create_task('builder', 'Idempotent task', key) == first
    with pytest.raises(Conflict):
        flow.h.create_task('builder', 'Different task', key)
    version = flow.version
    flow.move('begin_plan')
    with pytest.raises(Conflict):
        flow.h.move('builder', flow.id, 'execute', version, flow.key())
    with pytest.raises(HubError):
        flow.h.move('builder', flow.id, 'execute', None, flow.key())


def test_request_receipt_replay_remains_pending_after_completion(flow):
    flow.plan(); version, key = flow.version, flow.key()
    receipt = flow.h.request_review('builder', flow.id, 'PLAN_REVIEW', 'mock-reviewer', version, key)
    flow.drive()
    assert flow.task['state'] == 'PLAN_APPROVED'
    assert flow.h.request_review('builder', flow.id, 'PLAN_REVIEW', 'mock-reviewer', version, key) == receipt
    assert receipt['status'] == 'PENDING' and len(flow.rows('review_rounds')) == 1


def test_concurrent_idempotent_requests_reserve_one_round(flow):
    flow.plan(); version = flow.version
    def request(_):
        return flow.h.request_review('builder', flow.id, 'PLAN_REVIEW', 'mock-reviewer', version, 'same-command')
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(request, range(4)))
    assert all(x == receipts[0] for x in receipts)
    assert len(flow.rows('review_requests')) == len(flow.rows('outbox_events')) == 1


def test_request_audit_outbox_are_atomic_on_storage_failure(flow):
    flow.plan(); before = flow.task
    conn = flow.r.db.connect()
    conn.execute("CREATE TRIGGER reject_outbox BEFORE INSERT ON outbox_events BEGIN SELECT RAISE(ABORT,'injected'); END")
    conn.close()
    with pytest.raises(Conflict):
        flow.request()
    assert flow.task == before
    assert not flow.rows('review_requests') and not flow.rows('review_rounds') and not flow.rows('outbox_events')
    assert not any(a['action'] == 'REVIEW_REQUEST_CREATED' for a in flow.h.audit_log(flow.id))


def test_audit_reviews_and_finding_history_append_only(flow):
    flow.executing(); flow.package(); flow.request('FINAL_REVIEW','NEEDS_CHANGES'); flow.drive()
    conn = flow.r.db.connect()
    try:
        for table in ('audit_logs','reviews','finding_events','task_events','artifacts','review_profiles'):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(f'UPDATE {table} SET data=data')
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(f'DELETE FROM {table}')
    finally:
        conn.close()


def test_actor_identity_unique_and_builder_cannot_review(flow):
    with pytest.raises(Conflict):
        with flow.r.db.transaction() as repo:
            repo.add('actors', dict(id='same-account-reviewer', role='REVIEWER', name='other token', provider_id='local:builder', enabled=True))
    flow.plan()
    with pytest.raises(HubError):
        flow.h.request_review('builder', flow.id, 'PLAN_REVIEW', 'builder', flow.version, flow.key())


def test_evidence_and_package_cross_task_rejected(flow):
    other = Flow(flow.r)
    other_evidence = other.artifact()
    flow.executing(); flow.package(); rr = flow.request('FINAL_REVIEW', 'NEEDS_CHANGES')
    result = flow.r.mock._result(flow.h.get_review(rr)['request']['envelope'], {'scenario':'NEEDS_CHANGES'})
    result['findings'][0]['evidence']['artifact_id'] = other_evidence['id']
    flow.r.events.ingest(event_for(flow, rr, result))
    assert flow.r.events.handle_one() == 'REJECTED'
    assert not flow.h.list_findings(flow.id)


@pytest.mark.parametrize('tamper', ['missing','content'])
def test_artifact_integrity_failure_rejects_review(flow, tamper):
    flow.plan(); rr = flow.request()
    event = event_for(flow, rr)
    row = flow.rows('artifacts', id=flow.task['current_plan_id'])[0]
    path = flow.r.store.root / row['storage_pointer']
    if tamper == 'missing':
        path.unlink()
    else:
        path.write_bytes(b'changed')
    flow.r.events.ingest(event)
    assert flow.r.events.handle_one() == 'REJECTED'
    assert not flow.rows('reviews')


@pytest.mark.parametrize('pointer', ['../secrets', r'C:\secret', r'\\server\share', 'https://attacker.invalid', 'sha256/aa/'+'b'*64])
def test_artifact_pointer_cannot_escape_or_fetch_url(flow, pointer):
    with pytest.raises(HubError):
        flow.r.store.read(pointer, 'a'*64, 1)


def test_artifact_size_limit_and_content_addressing(tmp_path):
    store = FileArtifactStore(tmp_path / '中文 路径', max_bytes=4)
    pointer, sha = store.put(b'data')
    assert store.put(b'data') == (pointer, sha)
    assert store.read(pointer, sha, 4) == b'data'
    with pytest.raises(HubError):
        store.put(b'12345')


def test_backup_restores_state_and_artifacts(flow, tmp_path):
    flow.plan(); rr = flow.request(); flow.drive()
    restored_dir = tmp_path / 'restored'
    flow.r.db.backup_to(restored_dir / 'hub.db')
    shutil.copytree(flow.r.store.root, restored_dir / 'artifacts')
    restored = LocalRuntime(restored_dir, CONTRACTS, clock=flow.r.clock)
    assert restored.hub.get_task(flow.id) == flow.task
    assert restored.hub.get_review(rr) == flow.h.get_review(rr)
    for artifact in flow.rows('artifacts'):
        assert restored.store.read(artifact['storage_pointer'], artifact['sha256'], artifact['size_bytes'])


def test_audit_has_metadata_not_large_payload(flow):
    marker = 'PRIVATE-CONTENT-NOT-LOGGED-' + 'x'*50000
    artifact = flow.artifact('LOG', marker)
    for row in flow.rows('audit_logs'):
        assert marker not in str(row)
        assert len(str(row)) < 3000
    assert any(a.get('payload_summary',{}).get('artifact_id') == artifact['id'] for a in flow.rows('audit_logs'))


def test_per_review_limit_not_task_total(tmp_path):
    r = LocalRuntime(tmp_path, CONTRACTS, clock=ManualClock(),
                     settings=Settings(max_findings_per_review=1), legacy_create_test_mode=True)
    flow = Flow(r); flow.executing(); flow.package(); rr = flow.request('FINAL_REVIEW')
    result = r.mock._result(flow.h.get_review(rr)['request']['envelope'], {'scenario':'NEEDS_CHANGES'})
    result['findings'].append({**result['findings'][0], 'external_finding_key':'second'})
    r.events.ingest(event_for(flow, rr, result))
    assert r.events.handle_one() == 'REJECTED'
    assert flow.task['total_findings_created'] == 0


def test_supersedes_does_not_close_original_and_new_id_is_unique(flow):
    flow.executing(); flow.package(); flow.request('FINAL_REVIEW','NEEDS_CHANGES'); flow.drive()
    first = flow.h.list_findings(flow.id)[0]
    flow.package(); rr = flow.request('FINAL_REVIEW')
    result = flow.r.mock._result(flow.h.get_review(rr)['request']['envelope'], {'scenario':'NEEDS_CHANGES'})
    result['findings'][0].update(supersedes=first['id'], parent_finding_id=first['id'])
    flow.r.events.ingest(event_for(flow, rr, result)); assert flow.r.events.handle_one() == 'APPLIED'
    findings = flow.h.list_findings(flow.id)
    assert len(findings) == 2 and len({f['id'] for f in findings}) == 2
    assert findings[0]['status'] == 'OPEN'
    assert flow.task['total_findings_created'] == 2
