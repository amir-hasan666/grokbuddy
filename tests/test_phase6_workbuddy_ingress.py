"""Focused local tests for the dedicated WorkBuddy trigger ingress."""

import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from conftest import CONTRACTS
from grokbuddy.application.trigger import PHRASE
from grokbuddy.infrastructure.clock import ManualClock
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.interfaces.ingress_mcp import (
    INGRESS_TOOL_NAMES,
    create_ingress_mcp_server,
)


KEY_TEXT = 'test-only-placeholder-key_text-22'
KEY = KEY_TEXT.encode('utf-8')


def counts(runtime):
    with runtime.db.transaction() as repo:
        return tuple(len(repo.find(table)) for table in
                     ('tasks', 'artifacts', 'command_receipts', 'audit_logs'))


@pytest.fixture
def ingress_runtime(tmp_path):
    return LocalRuntime(
        tmp_path / 'ingress', CONTRACTS, clock=ManualClock(), trigger_source_key=KEY)


@pytest.mark.anyio
async def test_ingress_exposes_one_tool_and_creates_a_signed_ingress_task(ingress_runtime):
    server = create_ingress_mcp_server(ingress_runtime)
    payload = {
        'segments': [
            {'source': 'user_body', 'text': PHRASE},
            {'source': 'user_body', 'text': '，帮我列一个三步的今日待办提纲。'},
        ],
        'conversation_id': 'workbuddy-conversation-case-b',
        'idempotency_key': 'phase6-step6.17-case-b-message-1',
    }
    async with Client(server, mode='legacy', raise_exceptions=True) as client:
        listed = await client.list_tools()
        assert tuple(tool.name for tool in listed.tools) == INGRESS_TOOL_NAMES
        first = (await client.call_tool('create_triggered_task', payload)).structured_content
        ingress_runtime.clock.advance(1)
        replay = (await client.call_tool('create_triggered_task', payload)).structured_content

    assert replay == first
    assert first['state'] == 'NEW'
    assert first['owner_id'] == 'workbuddy-ingress'
    assert first['conversation_id'] == 'workbuddy-conversation-case-b'
    assert first['grokbuddy_enabled'] is True
    assert first['trigger_evidence']['principal_id'] == 'workbuddy-ingress'
    assert first['trigger_evidence']['phrase'] == PHRASE
    assert first['trigger_evidence']['message_id'].startswith('workbuddy-message-')
    assert len([row for row in ingress_runtime.hub.audit_log(first['id'])
                if row['action'] == 'TASK_CREATED'
                and row['actor_id'] == 'workbuddy-ingress']) == 1


@pytest.mark.anyio
@pytest.mark.parametrize('segments', [
    [{'source': 'user_body', 'text': '普通消息，不启动特殊流程。'}],
    [{'source': 'user_body', 'text': f'```text\n{PHRASE}\n```'}],
    [{'source': 'quote', 'text': PHRASE}],
    [{'source': 'pasted_document', 'text': PHRASE}],
])
async def test_ingress_nontrigger_and_excluded_text_make_no_hub_mutation(
        ingress_runtime, segments):
    before = counts(ingress_runtime)
    server = create_ingress_mcp_server(ingress_runtime)
    async with Client(server, mode='legacy', raise_exceptions=False) as client:
        result = await client.call_tool('create_triggered_task', {
            'segments': segments,
            'conversation_id': 'workbuddy-conversation-negative',
            'idempotency_key': str(uuid4()),
        })
    assert result.is_error is True
    assert 'TRIGGER_NOT_FOUND' in ''.join(
        getattr(item, 'text', '') for item in result.content)
    assert counts(ingress_runtime) == before


@pytest.mark.anyio
async def test_ingress_without_source_key_fails_closed_before_mutation(tmp_path):
    runtime = LocalRuntime(
        tmp_path / 'missing-key', CONTRACTS, clock=ManualClock(), trigger_source_key=b'')
    before = counts(runtime)
    server = create_ingress_mcp_server(runtime)
    async with Client(server, mode='legacy', raise_exceptions=False) as client:
        result = await client.call_tool('create_triggered_task', {
            'segments': [{'source': 'user_body', 'text': PHRASE}],
            'conversation_id': 'missing-key-conversation',
            'idempotency_key': str(uuid4()),
        })
    assert result.is_error is True
    assert 'TRIGGER_SOURCE_UNAVAILABLE' in ''.join(
        getattr(item, 'text', '') for item in result.content)
    assert counts(runtime) == before


@pytest.mark.anyio
async def test_ingress_rejects_changed_input_for_a_reused_idempotency_key(
        ingress_runtime):
    server = create_ingress_mcp_server(ingress_runtime)
    key = 'test-only-placeholder-key-114'
    async with Client(server, mode='legacy', raise_exceptions=False) as client:
        first = await client.call_tool('create_triggered_task', {
            'segments': [{'source': 'user_body', 'text': PHRASE + '，原始请求。'}],
            'conversation_id': 'workbuddy-conversation-reuse',
            'idempotency_key': key,
        })
        after_first = counts(ingress_runtime)
        changed = await client.call_tool('create_triggered_task', {
            'segments': [{'source': 'user_body', 'text': PHRASE + '，已变化请求。'}],
            'conversation_id': 'workbuddy-conversation-reuse',
            'idempotency_key': key,
        })
    after_changed = counts(ingress_runtime)

    assert first.is_error is False
    assert changed.is_error is True
    assert 'CONFLICT: Idempotency key reused with different input' in ''.join(
        getattr(item, 'text', '') for item in changed.content)
    assert after_changed == after_first


@pytest.mark.anyio
async def test_ingress_rejects_an_unexpanded_session_placeholder_without_mutation(
        ingress_runtime):
    before = counts(ingress_runtime)
    server = create_ingress_mcp_server(ingress_runtime)
    async with Client(server, mode='legacy', raise_exceptions=False) as client:
        result = await client.call_tool('create_triggered_task', {
            'segments': [{'source': 'user_body', 'text': PHRASE}],
            'conversation_id': '${CODEBUDDY_SESSION_ID}',
            'idempotency_key': str(uuid4()),
        })
    assert result.is_error is True
    assert 'session placeholder was not expanded' in ''.join(
        getattr(item, 'text', '') for item in result.content)
    assert counts(ingress_runtime) == before


@pytest.mark.anyio
async def test_ingress_stdio_subprocess_lists_only_ingress_and_creates(tmp_path):
    root = Path(__file__).resolve().parents[1]
    runtime_dir = tmp_path / 'workbuddy ingress stdio'
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(root / 'scripts' / 'grokbuddy_ingress_mcp.py'),
            '--runtime-dir', str(runtime_dir),
            '--contracts-dir', str(CONTRACTS),
        ],
        cwd=str(root),
        env={**os.environ, 'GROKBUDDY_TRIGGER_SOURCE_KEY': KEY_TEXT},
    )
    async with Client(params, mode='legacy', raise_exceptions=True,
                      read_timeout_seconds=10) as client:
        listed = await client.list_tools()
        assert tuple(tool.name for tool in listed.tools) == INGRESS_TOOL_NAMES
        created = (await client.call_tool('create_triggered_task', {
            'segments': [{'source': 'user_body', 'text': PHRASE + '，执行本地接线测试。'}],
            'conversation_id': 'workbuddy-stdio-session-smoke',
            'idempotency_key': 'phase6-workbuddy-ingress-stdio-smoke',
        })).structured_content
    async with Client(params, mode='legacy', raise_exceptions=True,
                      read_timeout_seconds=10) as client:
        replay = (await client.call_tool('create_triggered_task', {
            'segments': [{'source': 'user_body', 'text': PHRASE + '，执行本地接线测试。'}],
            'conversation_id': 'workbuddy-stdio-session-smoke',
            'idempotency_key': 'phase6-workbuddy-ingress-stdio-smoke',
        })).structured_content
        assert replay['id'] == created['id']
    reopened = LocalRuntime(runtime_dir, CONTRACTS, trigger_source_key=KEY)
    stored = reopened.hub.get_task(created['id'])
    assert stored['owner_id'] == 'workbuddy-ingress'
    assert stored['trigger_evidence']['principal_id'] == 'workbuddy-ingress'
