from pathlib import Path
import sys
from uuid import uuid4

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from conftest import CONTRACTS
from grokbuddy.domain.model import Conflict, HubError, PermissionDenied
from grokbuddy.interfaces.gateway import ClientGateway
from grokbuddy.interfaces.worker_mcp import WORKER_TOOL_NAMES, create_worker_mcp_server


def key():
    return str(uuid4())


def test_worker_offer_claim_upload_and_progress_are_separate_from_review(runtime):
    hub = runtime.hub
    task = hub.create_task('builder', 'Upload PHASE5_UPLOAD_PROBE.md', key())
    worker = ClientGateway(runtime, 'workbuddy-worker')
    assert hub.list_available_worker_tasks('workbuddy-worker') == []
    with pytest.raises(PermissionDenied):
        hub.get_worker_task('workbuddy-worker', task['id'])

    offered = hub.offer_task('builder', task['id'], task['version'], key())
    assert offered['state'] == 'NEW'
    assert offered['worker_status'] == 'OFFERED'
    assert hub.list_available_worker_tasks('workbuddy-worker')[0]['task_id'] == task['id']
    assert hub.get_worker_task('workbuddy-worker', task['id'])['instruction'] == 'Upload PHASE5_UPLOAD_PROBE.md'
    with pytest.raises(PermissionDenied):
        worker.invoke('submit_artifact', {'task_id': task['id'], 'artifact_type': 'EVIDENCE',
                                          'content_text': 'probe', 'idempotency_key': key()})
    self_created = worker.invoke('create_task', {'description': 'Worker cannot skip claim',
                                                 'idempotency_key': key()})
    with pytest.raises(PermissionDenied, match='Claim task before uploading'):
        worker.invoke('submit_artifact', {'task_id': self_created['id'], 'artifact_type': 'EVIDENCE',
                                          'content_text': 'probe', 'idempotency_key': key()})

    claim_key = key()
    claimed = hub.claim_task('workbuddy-worker', task['id'], offered['version'], claim_key)
    assert claimed['state'] == 'NEW'
    assert claimed['owner_id'] == claimed['worker_claimed_by'] == 'workbuddy-worker'
    assert hub.claim_task('workbuddy-worker', task['id'], offered['version'], claim_key) == claimed
    with pytest.raises(Conflict):
        hub.claim_task('workbuddy-worker', task['id'], offered['version'], key())
    assert hub.list_available_worker_tasks('workbuddy-worker') == []

    content = 'Phase 5 WorkBuddy upload probe.\n'
    artifact = worker.invoke('submit_artifact', {'task_id': task['id'], 'artifact_type': 'EVIDENCE',
                                                 'content_text': content, 'idempotency_key': key()})
    assert artifact['created_by'] == 'workbuddy-worker'
    assert runtime.store.read(artifact['storage_pointer'], artifact['sha256'], artifact['size_bytes']) == content.encode()
    progress = hub.report_worker_progress('workbuddy-worker', task['id'], 'Probe file uploaded', key())
    assert progress['worker_progress'] == 'Probe file uploaded'
    assert progress['state'] == 'NEW'
    with runtime.db.transaction() as repo:
        assert repo.find('review_requests', task_id=task['id']) == []
    assert [row['action'] for row in hub.audit_log(task['id']) if row['action'] in
            ('TASK_OFFERED', 'TASK_CLAIMED', 'WORKER_PROGRESS')] == [
                'TASK_OFFERED', 'TASK_CLAIMED', 'WORKER_PROGRESS']


@pytest.mark.anyio
async def test_dedicated_worker_mcp_discovery_and_claim_order(runtime):
    task = runtime.hub.create_task('builder', 'Small upload probe', key())
    offered = runtime.hub.offer_task('builder', task['id'], task['version'], key())
    async with Client(create_worker_mcp_server(runtime), mode='legacy', raise_exceptions=True) as client:
        listed = await client.list_tools()
        assert tuple(tool.name for tool in listed.tools) == WORKER_TOOL_NAMES
        assert 'request_final_review' not in WORKER_TOOL_NAMES
        pending = await client.call_tool('list_available_tasks', {})
        assert pending.structured_content['result'][0]['task_id'] == task['id']
        context = await client.call_tool('get_task', {'task_id': task['id']})
        assert context.structured_content['instruction'] == 'Small upload probe'
        claimed = await client.call_tool('claim_task', {
            'task_id': task['id'], 'expected_version': offered['version'], 'idempotency_key': key()})
        assert claimed.structured_content['worker_status'] == 'CLAIMED'
        uploaded = await client.call_tool('submit_artifact', {
            'task_id': task['id'], 'artifact_type': 'EVIDENCE',
            'content_text': 'Phase 5 WorkBuddy upload probe.\n', 'idempotency_key': key()})
        assert uploaded.structured_content['sha256']


@pytest.mark.anyio
async def test_worker_completion_requires_own_evidence_and_progress_and_replays_once(runtime):
    hub = runtime.hub
    task = hub.create_task('builder', 'Complete uploaded probe', key())
    offered = hub.offer_task('builder', task['id'], task['version'], key())
    with pytest.raises(PermissionDenied):
        hub.complete_worker_task('builder', task['id'], task['original_task_id'],
                                 offered['version'], key())
    async with Client(create_worker_mcp_server(runtime), mode='legacy', raise_exceptions=True) as client:
        claimed = await client.call_tool('claim_task', {
            'task_id': task['id'], 'expected_version': offered['version'], 'idempotency_key': key()})
        uploaded = await client.call_tool('submit_artifact', {
            'task_id': task['id'], 'artifact_type': 'EVIDENCE',
            'content_text': 'Phase 5 WorkBuddy upload probe.\n', 'idempotency_key': key()})
        aid = uploaded.structured_content['id']
        version = claimed.structured_content['version']
        with pytest.raises(HubError, match='subsequent progress'):
            hub.complete_worker_task('workbuddy-worker', task['id'], aid, version, key())
        hub.report_worker_progress('workbuddy-worker', task['id'], 'Uploaded evidence', key())
        version = hub.get_task(task['id'])['version']
        with pytest.raises(Conflict, match='Stale task version'):
            hub.complete_worker_task('workbuddy-worker', task['id'], aid, version - 1, key())
        with pytest.raises(HubError, match='Artifact type mismatch'):
            hub.complete_worker_task('workbuddy-worker', task['id'], task['original_task_id'], version, key())
        completion_key = key()
        payload = {'task_id': task['id'], 'artifact_id': aid,
                   'expected_version': version, 'idempotency_key': completion_key}
        completed = (await client.call_tool('complete_task', payload)).structured_content
        assert completed['worker_status'] == 'COMPLETED'
        assert completed['worker_completed_by'] == 'workbuddy-worker'
        assert completed['worker_completion_artifact_id'] == aid
        assert completed['worker_completion_sha256'] == uploaded.structured_content['sha256']
        assert completed['version'] == version + 1
        assert completed['state'] == 'NEW'
        assert (await client.call_tool('complete_task', payload)).structured_content == completed
        with pytest.raises(Conflict, match='not a claimed Worker task'):
            hub.complete_worker_task('workbuddy-worker', task['id'], aid,
                                     completed['version'], key())
    assert hub.get_task(task['id'])['version'] == completed['version']
    assert len([row for row in hub.audit_log(task['id']) if row['action'] == 'WORKER_COMPLETED']) == 1
    with runtime.db.transaction() as repo:
        assert repo.find('review_requests', task_id=task['id']) == []
        assert repo.find('outbox_events', task_id=task['id']) == []


@pytest.mark.anyio
async def test_worker_stdio_subprocess_lists_formal_tools(tmp_path):
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(root / 'scripts' / 'grokbuddy_worker_mcp.py'),
              '--runtime-dir', str(tmp_path / 'worker runtime'),
              '--contracts-dir', str(CONTRACTS)],
        cwd=str(root),
    )
    async with Client(params, mode='legacy', raise_exceptions=True, read_timeout_seconds=10) as client:
        listed = await client.list_tools()
        assert tuple(tool.name for tool in listed.tools) == WORKER_TOOL_NAMES
        assert str(client.protocol_version) == '2025-11-25'
