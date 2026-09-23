"""Ingress-created v2 Tasks are driven by the configured Hub Builder, without owner transfer."""

from uuid import uuid4

import pytest
from mcp import Client

from conftest import CONTRACTS
from grokbuddy.application.trigger import PHRASE, issue_trigger_evidence
from grokbuddy.domain.model import HubError, PermissionDenied, Role
from grokbuddy.infrastructure.clock import ManualClock
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.interfaces.gateway import ClientGateway
from grokbuddy.interfaces.mcp import create_mcp_server


TRIGGER_KEY = b'phase6-ingress-builder-drive-key-32-bytes'


def key():
    return str(uuid4())


def add_builder(runtime, actor_id):
    with runtime.db.transaction() as repo:
        repo.add('actors', {
            'id': actor_id,
            'name': actor_id,
            'role': Role.BUILDER.value,
            'provider_id': 'local:' + actor_id,
            'enabled': True,
            'reviewer_type': None,
        })


def create_ingress_task(runtime):
    message = {
        'principal_id': 'workbuddy-ingress',
        'conversation_id': 'phase6-ingress-builder-drive-' + key(),
        'message_id': key(),
        'turn_id': key(),
        'message_role': 'user',
        'issued_at': runtime.clock.now(),
        'segments': [{
            'source': 'user_body',
            'text': PHRASE + '，请按流水线完成这个隔离任务。',
        }],
    }
    body, evidence = issue_trigger_evidence(message, TRIGGER_KEY, runtime.clock.now())
    return ClientGateway(runtime, 'workbuddy-ingress').invoke('create_task', {
        'description': body,
        'idempotency_key': key(),
        'trigger_evidence': evidence,
    })


def upload(gateway, task_id, artifact_type, content):
    return gateway.invoke('submit_artifact', {
        'task_id': task_id,
        'artifact_type': artifact_type,
        'content_text': content,
        'idempotency_key': key(),
    })


def rows(runtime, table, **filters):
    with runtime.db.transaction() as repo:
        return repo.find(table, **filters)


def mcp_error_text(result):
    return '\n'.join(
        block.text for block in result.content
        if getattr(block, 'type', None) == 'text'
    )


@pytest.mark.anyio
async def test_hub_mcp_submit_plan_schema_and_scope_validation_for_ingress_v2(tmp_path):
    runtime = LocalRuntime(
        tmp_path / 'mcp-plan-scope-validation', CONTRACTS, clock=ManualClock(),
        trigger_source_key=TRIGGER_KEY)
    created = create_ingress_task(runtime)
    builder = ClientGateway(runtime, 'builder')
    plan = upload(builder, created['id'], 'PLAN', 'MCP scope validation plan')
    command_key = key()
    base = {
        'task_id': created['id'],
        'plan_artifact_id': plan['id'],
        'expected_version': created['version'],
        'idempotency_key': command_key,
    }

    async with Client(create_mcp_server(runtime), mode='legacy',
                      raise_exceptions=False) as client:
        tools = await client.list_tools()
        schema = next(tool.input_schema for tool in tools.tools
                      if tool.name == 'submit_plan')
        assert schema['required'] == [
            'task_id', 'plan_artifact_id', 'approved_scope',
            'expected_version', 'idempotency_key',
        ]
        assert schema['additionalProperties'] is False
        scope_schema = schema['$defs']['ApprovedPlanScope']
        assert scope_schema['minProperties'] == 1
        assert scope_schema['additionalProperties'] is False
        assert set(scope_schema['properties']) == {'summary', 'files', 'components'}

        missing = await client.call_tool('submit_plan', base)
        assert missing.is_error
        assert 'approved_scope' in mcp_error_text(missing)

        empty = await client.call_tool('submit_plan', {
            **base, 'approved_scope': {},
        })
        assert empty.is_error
        assert 'Plan scope must be a non-empty structured object' in mcp_error_text(empty)

        nested_extra = await client.call_tool('submit_plan', {
            **base, 'approved_scope': {'summary': 'bounded', 'unknown': True},
        })
        assert nested_extra.is_error
        assert 'Extra inputs are not permitted' in mcp_error_text(nested_extra)

        top_level_extra = await client.call_tool('submit_plan', {
            **base,
            'approved_scope': {'summary': 'bounded'},
            'unknown': True,
        })
        assert top_level_extra.is_error
        assert 'Extra inputs are not permitted' in mcp_error_text(top_level_extra)

    unchanged = runtime.hub.get_task(created['id'])
    assert unchanged['state'] == 'NEW'
    assert unchanged['current_plan_id'] is None


@pytest.mark.anyio
async def test_hub_mcp_submit_plan_recovers_same_key_after_legacy_scope_failure(tmp_path):
    runtime = LocalRuntime(
        tmp_path / 'mcp-plan-scope-retry', CONTRACTS, clock=ManualClock(),
        trigger_source_key=TRIGGER_KEY)
    created = create_ingress_task(runtime)
    builder = ClientGateway(runtime, 'builder')
    plan = upload(builder, created['id'], 'PLAN', 'MCP same-key retry plan')
    command_key = key()
    base = {
        'task_id': created['id'],
        'plan_artifact_id': plan['id'],
        'expected_version': created['version'],
        'idempotency_key': command_key,
    }

    # Reproduce the pre-hotfix path: Gateway begins planning, then the v2 Hub
    # rejects the missing scope.  No submit-plan receipt is committed.
    with pytest.raises(HubError, match='Plan scope must be a non-empty structured object'):
        builder.invoke('submit_plan', base)
    assert runtime.hub.get_task(created['id'])['state'] == 'PLANNING'

    payload = {
        **base,
        'approved_scope': {
            'summary': 'Ingress-owned v2 plan through Hub MCP',
            'files': ['local.txt'],
        },
    }
    async with Client(create_mcp_server(runtime), mode='legacy',
                      raise_exceptions=True) as client:
        submitted = await client.call_tool('submit_plan', payload)
        replay = await client.call_tool('submit_plan', payload)

    assert not submitted.is_error
    assert replay.structured_content == submitted.structured_content
    planned = submitted.structured_content
    assert planned['state'] == 'PLANNING'
    assert planned['owner_id'] == 'workbuddy-ingress'
    assert planned['current_plan_id'] == plan['id']
    assert planned['current_plan_scope'] == payload['approved_scope']
    assert len(rows(runtime, 'audit_logs', task_id=created['id'], action='PLAN_SUBMITTED')) == 1


def test_ingress_owner_is_preserved_while_configured_builder_drives_plan_to_done(tmp_path):
    runtime = LocalRuntime(
        tmp_path / 'ingress-builder-flow', CONTRACTS, clock=ManualClock(),
        trigger_source_key=TRIGGER_KEY)
    builder = ClientGateway(runtime, 'builder')
    worker = ClientGateway(runtime, 'workbuddy-worker')
    created = create_ingress_task(runtime)
    task_id = created['id']

    assert created['owner_id'] == 'workbuddy-ingress'
    assert created['state'] == 'NEW'
    with pytest.raises(PermissionDenied, match='Legacy owner-transfer Worker path is test-only'):
        runtime.hub.claim_task('workbuddy-worker', task_id, created['version'], key())

    plan = upload(builder, task_id, 'PLAN', 'Bounded ingress-owned implementation plan')
    planned = builder.invoke('submit_plan', {
        'task_id': task_id,
        'plan_artifact_id': plan['id'],
        'approved_scope': {
            'summary': 'Ingress Builder drive isolation',
            'files': ['local.txt'],
        },
        'expected_version': created['version'],
        'idempotency_key': key(),
    })
    assert planned['state'] == 'PLANNING'
    assert planned['owner_id'] == 'workbuddy-ingress'

    plan_receipt = builder.invoke('request_plan_review', {
        'task_id': task_id,
        'expected_version': planned['version'],
        'idempotency_key': key(),
    })
    runtime.mock.configure(plan_receipt['review_request_id'], 'PASS')
    runtime.supervisor().run_until_idle()
    approved = runtime.hub.get_task(task_id)
    assert approved['state'] == 'PLAN_APPROVED'
    assert approved['owner_id'] == 'workbuddy-ingress'

    executing = runtime.hub.move('builder', task_id, 'execute', approved['version'], key())
    assignments = rows(runtime, 'worker_assignments', task_id=task_id)
    assert executing['owner_id'] == 'workbuddy-ingress'
    assert len(assignments) == 1
    assert assignments[0]['status'] == 'OFFERED'

    claimed = runtime.hub.claim_task(
        'workbuddy-worker', task_id, assignments[0]['version'], key())
    evidence = upload(worker, task_id, 'EVIDENCE', 'Worker completion evidence')
    progress = runtime.hub.report_worker_progress(
        'workbuddy-worker', task_id, 'Bounded implementation completed', key())
    completed = runtime.hub.complete_worker_task(
        'workbuddy-worker', task_id, evidence['id'], progress['version'], key())
    assert claimed['worker_principal_id'] == 'workbuddy-worker'
    assert completed['task_state'] == 'EXECUTING'
    assert completed['task_owner_id'] == 'workbuddy-ingress'

    test_artifact = upload(builder, task_id, 'TEST_RESULT', 'Focused tests passed')
    diff_artifact = upload(builder, task_id, 'DIFF', 'Bounded local diff')
    final_receipt = builder.invoke('request_final_review', {
        'task_id': task_id,
        'test_artifact_id': test_artifact['id'],
        'diff_artifact_id': diff_artifact['id'],
        'expected_version': runtime.hub.get_task(task_id)['version'],
        'idempotency_key': key(),
        'begin_execution': False,
        'change_scope': 'Ingress Builder drive isolation',
        'changed_files': ['local.txt'],
        'self_test_summary': 'Focused tests passed',
        'known_risks': [],
        'unverified_items': ['Real WorkBuddy 6.20 Human retest remains pending'],
    })
    runtime.mock.configure(final_receipt['review_request_id'], 'PASS')
    runtime.supervisor().run_until_idle()

    done = runtime.hub.get_task(task_id)
    assert done['state'] == 'DONE'
    assert done['owner_id'] == 'workbuddy-ingress'
    assert done['completion_basis'] == 'FINAL_REVIEW_PASS'
    assert len(rows(runtime, 'tasks')) == 1
    assert {request['task_id'] for request in rows(runtime, 'review_requests')} == {task_id}


def test_unconfigured_builders_and_wrong_actor_still_cannot_drive_ingress_task(tmp_path):
    runtime = LocalRuntime(
        tmp_path / 'ingress-builder-negative', CONTRACTS, clock=ManualClock(),
        trigger_source_key=TRIGGER_KEY)
    add_builder(runtime, 'other-builder')
    created = create_ingress_task(runtime)

    with pytest.raises(PermissionDenied, match='Task belongs to another Builder'):
        upload(ClientGateway(runtime, 'other-builder'), created['id'], 'PLAN', 'not allowed')
    with pytest.raises(PermissionDenied, match='Principal not authorized'):
        runtime.hub.submit_artifact(
            'mock-reviewer', created['id'], 'PLAN', b'not a Builder', key())
    with pytest.raises(PermissionDenied, match='Claim a v2 Worker assignment'):
        upload(ClientGateway(runtime, 'workbuddy-worker'), created['id'], 'PLAN', 'not claimed')

    assert runtime.hub.get_task(created['id'])['state'] == 'NEW'
    assert runtime.hub.get_task(created['id'])['owner_id'] == 'workbuddy-ingress'
    assert not rows(runtime, 'worker_assignments', task_id=created['id'])


def test_non_ingress_tasks_keep_original_builder_owner_check(tmp_path):
    runtime = LocalRuntime(
        tmp_path / 'legacy-owner-check', CONTRACTS, clock=ManualClock(),
        legacy_create_test_mode=True)
    add_builder(runtime, 'other-builder')
    task = runtime.hub.create_task('builder', 'Legacy isolated owner check', key())

    with pytest.raises(PermissionDenied, match='Task belongs to another Builder'):
        runtime.hub.move('other-builder', task['id'], 'begin_plan', task['version'], key())

    planning = runtime.hub.move('builder', task['id'], 'begin_plan', task['version'], key())
    assert planning['state'] == 'PLANNING'
    assert planning['owner_id'] == 'builder'
