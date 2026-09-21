"""Step 6.1 local, isolated-DB contract probes; no external WorkBuddy calls."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
from uuid import uuid4

import pytest

from conftest import CONTRACTS
from grokbuddy.application.common import canonical
from grokbuddy.application.trigger import PHRASE
from grokbuddy.domain.model import (ActiveConversationTask, Conflict, PermissionDenied,
                                    TriggerEvidenceInvalid, TriggerEvidenceRequired,
                                    TriggerNotFound, TriggerSourceUnavailable)
from grokbuddy.infrastructure.clock import ManualClock
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.interfaces.gateway import ClientGateway


KEY = b'local-isolated-trigger-source-key-32-bytes-minimum'


@pytest.fixture
def signed_runtime(tmp_path):
    return LocalRuntime(tmp_path / 'trigger-gate', CONTRACTS, clock=ManualClock(),
                        trigger_source_key=KEY)


def signed_evidence(runtime, segments, *, conversation_id='conversation-1',
                    message_id=None, turn_id=None, issued_at=None, key=KEY):
    message = {
        'principal_id': 'workbuddy-ingress',
        'conversation_id': conversation_id,
        'message_id': message_id or str(uuid4()),
        'turn_id': turn_id or str(uuid4()),
        'message_role': 'user',
        'issued_at': runtime.clock.now() if issued_at is None else issued_at,
        'segments': segments,
    }
    body = ''.join(segment['text'] for segment in segments)
    raw = body.encode('utf-8')
    start = raw.find(PHRASE.encode('utf-8'))
    return body, {
        'message': message,
        'signature': hmac.new(key, canonical(message), hashlib.sha256).hexdigest(),
        'body_sha256': hashlib.sha256(raw).hexdigest(),
        'phrase': PHRASE,
        'start_byte': start,
        'end_byte': start + len(PHRASE.encode('utf-8')),
    }


def create(runtime, body, evidence, key=None):
    return ClientGateway(runtime, 'workbuddy-ingress').invoke('create_task', {
        'description': body,
        'idempotency_key': key or str(uuid4()),
        'trigger_evidence': evidence,
    })


def counts(runtime):
    with runtime.db.transaction() as repo:
        return tuple(len(repo.find(table)) for table in
                     ('tasks', 'artifacts', 'command_receipts', 'audit_logs'))


def test_a_missing_or_nontrigger_message_makes_no_hub_mutation(signed_runtime):
    before = counts(signed_runtime)
    with pytest.raises(TriggerEvidenceRequired):
        ClientGateway(signed_runtime).invoke('create_task', {
            'description': '普通请求', 'idempotency_key': str(uuid4()),
        })
    assert counts(signed_runtime) == before
    body, evidence = signed_evidence(signed_runtime, [{'source': 'user_body', 'text': '普通请求'}])
    with pytest.raises(TriggerNotFound):
        create(signed_runtime, body, evidence)
    assert counts(signed_runtime) == before


def test_b_exact_trigger_creates_one_auditable_task_and_replays(signed_runtime):
    body, evidence = signed_evidence(signed_runtime, [
        {'source': 'user_body', 'text': '请处理这个请求，启用'},
        {'source': 'user_body', 'text': 'grokbuddy流程。'}])
    key = str(uuid4())
    created = create(signed_runtime, body, evidence, key)
    assert created['state'] == 'NEW' and created['grokbuddy_enabled'] is True
    assert created['conversation_id'] == 'conversation-1'
    assert created['trigger_evidence']['start_byte'] == evidence['start_byte']
    assert created['trigger_evidence']['message_id'] == evidence['message']['message_id']
    assert create(signed_runtime, body, evidence, key) == created
    assert signed_runtime.hub.get_conversation_context('conversation-1') == {
        'grokbuddy_enabled': True, 'task_id': created['id']}
    source = signed_runtime.hub.get_artifact(created['trigger_evidence']['source_artifact_id'])
    assert source['sha256'] == created['trigger_evidence']['source_artifact_sha256']
    assert signed_runtime.store.read(source['storage_pointer'], source['sha256'],
                                     source['size_bytes']) == canonical(evidence['message'])
    reopened = LocalRuntime(signed_runtime.directory, CONTRACTS, clock=signed_runtime.clock,
                            trigger_source_key=KEY)
    assert reopened.hub.get_task(created['id'])['trigger_evidence'] == created['trigger_evidence']
    assert counts(reopened)[0] == 1


@pytest.mark.parametrize('terminal', ['DONE', 'CANCELLED', 'FAILED'])
def test_c_terminal_context_expires_and_ordinary_message_cannot_inherit(signed_runtime, terminal):
    body, evidence = signed_evidence(signed_runtime, [
        {'source': 'user_body', 'text': PHRASE + '，处理任务'}])
    created = create(signed_runtime, body, evidence)
    # Isolated fixture places the Task in each terminal state; D7/D8 transitions
    # belong to later steps and are not exercised by this trigger probe.
    with signed_runtime.db.transaction() as repo:
        task = repo.get('tasks', created['id'])
        task['state'] = terminal
        task['version'] += 1
        repo.save('tasks', task, expected_version=0)
    assert signed_runtime.hub.get_conversation_context('conversation-1') == {
        'grokbuddy_enabled': False, 'task_id': None}
    before = counts(signed_runtime)
    ordinary, no_trigger = signed_evidence(signed_runtime, [
        {'source': 'user_body', 'text': '继续处理一个普通问题'}])
    with pytest.raises(TriggerNotFound):
        create(signed_runtime, ordinary, no_trigger)
    assert counts(signed_runtime) == before
    with pytest.raises(TriggerEvidenceInvalid):
        create(signed_runtime, body, evidence, str(uuid4()))
    fresh, fresh_evidence = signed_evidence(signed_runtime, [
        {'source': 'user_body', 'text': '新任务：' + PHRASE}])
    second = create(signed_runtime, fresh, fresh_evidence)
    assert second['id'] != created['id']


def test_d_one_active_task_per_conversation_at_application_and_sqlite(signed_runtime):
    first_body, first_evidence = signed_evidence(signed_runtime, [
        {'source': 'user_body', 'text': PHRASE + ' 第一项'}])
    first = create(signed_runtime, first_body, first_evidence)
    before = counts(signed_runtime)
    second_body, second_evidence = signed_evidence(signed_runtime, [
        {'source': 'user_body', 'text': PHRASE + ' 第二项'}])
    with pytest.raises(ActiveConversationTask):
        create(signed_runtime, second_body, second_evidence)
    assert counts(signed_runtime) == before
    duplicate = {**first, 'id': 'TASK-direct-index-probe',
                 'trigger_message_id': 'another-message'}
    with pytest.raises(Conflict):
        with signed_runtime.db.transaction() as repo:
            repo.add('tasks', duplicate)
    assert counts(signed_runtime) == before


@pytest.mark.parametrize('segments', [
    [{'source': 'user_body', 'text': '```\n' + PHRASE + '\n```\n'}],
    [{'source': 'user_body', 'text': '> ' + PHRASE + '\n'}],
    [{'source': 'user_body', 'text': '`' + PHRASE + '`'}],
    [{'source': 'pasted_document', 'text': PHRASE}],
    [{'source': 'tool_output', 'text': PHRASE}],
])
def test_e_non_natural_language_occurrences_do_not_trigger(signed_runtime, segments):
    before = counts(signed_runtime)
    body, evidence = signed_evidence(signed_runtime, segments)
    with pytest.raises(TriggerNotFound):
        create(signed_runtime, body, evidence)
    assert counts(signed_runtime) == before


def test_f_orgery_stale_offset_and_wrong_principal_fail_closed(signed_runtime):
    body, evidence = signed_evidence(signed_runtime, [
        {'source': 'user_body', 'text': '你好，' + PHRASE}])
    before = counts(signed_runtime)
    tampered = {**evidence, 'start_byte': 0, 'end_byte': len(PHRASE.encode('utf-8'))}
    with pytest.raises(TriggerEvidenceInvalid):
        create(signed_runtime, body, tampered)
    tampered = {**evidence, 'signature': '0' * 64}
    with pytest.raises(TriggerEvidenceInvalid):
        create(signed_runtime, body, tampered)
    with pytest.raises(PermissionDenied):
        ClientGateway(signed_runtime, 'builder').invoke('create_task', {
            'description': body, 'idempotency_key': str(uuid4()),
            'trigger_evidence': evidence})
    stale_body, stale = signed_evidence(signed_runtime, [
        {'source': 'user_body', 'text': PHRASE}],
        issued_at=signed_runtime.clock.now() - 301_000_000)
    with pytest.raises(TriggerEvidenceInvalid):
        create(signed_runtime, stale_body, stale)
    assert counts(signed_runtime) == before


def test_unconfigured_source_is_closed(tmp_path):
    runtime = LocalRuntime(tmp_path / 'unconfigured', CONTRACTS, clock=ManualClock())
    body, evidence = signed_evidence(runtime, [{'source': 'user_body', 'text': PHRASE}])
    before = counts(runtime)
    with pytest.raises(TriggerSourceUnavailable):
        create(runtime, body, evidence)
    assert counts(runtime) == before


def test_concurrent_creates_choose_one_task(signed_runtime):
    attempts = [signed_evidence(signed_runtime, [
        {'source': 'user_body', 'text': PHRASE + str(i)}]) for i in range(2)]
    def attempt(pair):
        try:
            return create(signed_runtime, *pair)['id']
        except ActiveConversationTask:
            return 'REJECTED'
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, attempts))
    assert len([result for result in results if result != 'REJECTED']) == 1
    assert results.count('REJECTED') == 1
    assert counts(signed_runtime)[0] == 1
