"""Local-only proof that the formal Hub process owns the production Supervisor."""

import json
from pathlib import Path
import shutil
import subprocess
import time
from uuid import uuid4

import anyio
import httpx2
import pytest
import uvicorn

from conftest import CONTRACTS, Flow
from grokbuddy.adapters.github import FileGitHubCommentTransport
from grokbuddy.application.trigger import PHRASE, issue_trigger_evidence
from grokbuddy.domain.model import ReviewDeliveryUnavailable
from grokbuddy.infrastructure.clock import ManualClock
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.infrastructure.supervisor_service import SupervisorService
from grokbuddy.interfaces.composite import create_composite_application
from grokbuddy.interfaces.gateway import ClientGateway
from grokbuddy.interfaces.grok_reviewer import GrokReviewerApplication
from scripts import grokbuddy_composite
from scripts import grokbuddy_mcp


B_ACTOR = 'grok-reviewer-b'
AGENT_ID = '4335c388-584c-434e-b14e-13964b176b6e'
SERVER_ID = '3504754'
REVIEWER_TOKEN = 'local-production-wiring-reviewer-token'
TRIGGER_KEY = b'phase6-reviewer-delivery-gap-key-32-bytes'


def register_b(runtime):
    runtime.hub.register_reviewer(
        'system', B_ACTOR, 'workbuddy reviewer', AGENT_ID, SERVER_ID)


def planned_unbound_v2_task(runtime):
    unique = str(uuid4())
    message = {
        'principal_id': 'workbuddy-ingress',
        'conversation_id': 'phase6-review-delivery-' + unique,
        'message_id': str(uuid4()),
        'turn_id': str(uuid4()),
        'message_role': 'user',
        'issued_at': runtime.clock.now(),
        'segments': [{
            'source': 'user_body',
            'text': PHRASE + '，创建无 PR 的正式 Plan Review。',
        }],
    }
    body, evidence = issue_trigger_evidence(
        message, TRIGGER_KEY, runtime.clock.now())
    ingress = ClientGateway(runtime, 'workbuddy-ingress')
    builder = ClientGateway(runtime, 'builder')
    created = ingress.invoke('create_task', {
        'description': body,
        'idempotency_key': str(uuid4()),
        'trigger_evidence': evidence,
    })
    plan = builder.invoke('submit_artifact', {
        'task_id': created['id'],
        'artifact_type': 'PLAN',
        'content_text': 'No-PR formal Plan Review delivery fixture',
        'idempotency_key': str(uuid4()),
    })
    planned = builder.invoke('submit_plan', {
        'task_id': created['id'],
        'plan_artifact_id': plan['id'],
        'approved_scope': {
            'summary': 'Reviewer HTTP delivery only',
            'files': ['local.txt'],
        },
        'expected_version': created['version'],
        'idempotency_key': str(uuid4()),
    })
    return builder, planned


def routed_grok_request(flow, tmp_path):
    flow.executing()
    flow.package()
    flow.r.github_bindings.bind_pull_request(
        repository_id=1372874264,
        repository_full_name='example/grokbuddy',
        pull_request_number=6,
        task_id=flow.id,
        hub_pointer_base='https://grokbuddy.amirhasan.top',
    )
    old_rr = flow.request('FINAL_REVIEW')
    register_b(flow.r)
    flow.h.route_future_reviews('builder', flow.id, B_ACTOR, flow.version, flow.key())
    flow.r.clock.advance(flow.r.settings.final_review_timeout + 1)
    assert flow.r.timeouts.sweep() == 1
    receipt = flow.h.retry_final_with_grok(
        'human', 'builder', flow.id, old_rr, 3,
        flow.r.clock.now() + 80_000_000_000,
        'Local production Supervisor wiring fixture', flow.version, flow.key())
    transport = FileGitHubCommentTransport(tmp_path / 'production-comments.json')
    dispatcher = flow.r.grok_dispatcher(
        transport, B_ACTOR, 'https://grokbuddy.amirhasan.top')
    intake = flow.r.grok_intake(B_ACTOR)
    supervisor = flow.r.supervisor(
        projection_transport=transport,
        binding_policy=lambda _task: None,
        dispatcher=dispatcher,
        intake=intake,
    )
    return receipt['review_request_id'], transport, intake, supervisor, dispatcher


def test_formal_config_defaults_supervisor_on_and_stdio_reviews_to_b():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'config' / 'grokbuddy.service.json').read_text(
        encoding='utf-8'))
    formal_runtime = str((root / config['runtimeDir']).resolve())

    assert config['supervisorEnabled'] is True
    assert config['supervisorIntervalSeconds'] == 5
    assert config['reviewerActor'] == B_ACTOR
    assert config['githubCommentTokenEnv'] == 'GITHUB_COMMENT_TOKEN'
    debug_args = grokbuddy_composite._parser().parse_args([
        '--runtime-dir', formal_runtime,
        '--disable-supervisor',
    ])
    assert debug_args.disable_supervisor is True
    assert grokbuddy_mcp._service_reviewer_default([
        '--runtime-dir', formal_runtime,
    ]) == B_ACTOR
    assert grokbuddy_mcp._service_reviewer_default([
        '--runtime-dir', str(root / 'var' / 'isolated-test-runtime'),
    ]) == 'mock-reviewer'


def test_windows_launcher_redirects_info_stderr_outside_error_pipeline():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / 'scripts' / 'windows' / 'Start-GrokBuddyHub.ps1').read_text(
        encoding='utf-8-sig')
    restart = (root / 'scripts' / 'windows' / 'Restart-GrokBuddyHubTask.ps1').read_text(
        encoding='utf-8-sig')
    runtime_probe = (root / 'scripts' / 'windows' / 'Test-GrokBuddyRuntime.ps1').read_text(
        encoding='utf-8-sig')

    assert 'trap {' not in launcher
    assert '& $python @arguments' not in launcher
    assert '$hubProcess = Start-Process' in launcher
    assert "$stderrLog = Join-Path $logRoot 'hub.stderr.log'" in launcher
    assert '-RedirectStandardOutput $stdoutLog' in launcher
    assert '-RedirectStandardError $stderrLog' in launcher
    assert '-PassThru' in launcher
    assert '-Wait' in launcher
    assert '$hubProcess.ExitCode' in launcher
    assert launcher.index('catch {\n    Write-BootstrapFailure') < launcher.index(
        '$hubProcess = Start-Process')
    assert '[int]$ReadyTimeoutSeconds = 30' in restart
    assert "$supervisorCheck -eq 'ok'" in restart
    assert runtime_probe.count('"supervisor"\\s*:\\s*"ok"') == 2


def test_windows_launcher_reads_service_and_registry_as_utf8(tmp_path):
    root = Path(__file__).resolve().parents[1]
    launcher = (root / 'scripts' / 'windows' / 'Start-GrokBuddyHub.ps1').read_text(
        encoding='utf-8-sig')
    assert launcher.count('-Raw -Encoding utf8 | ConvertFrom-Json') == 2
    assert ('$config = Get-Content -LiteralPath $ConfigPath -Raw '
            '-Encoding utf8 | ConvertFrom-Json') in launcher
    assert ('$reviewerRegistry = Get-Content -LiteralPath $reviewerRegistryPath '
            '-Raw -Encoding utf8 | ConvertFrom-Json') in launcher

    fixture_root = tmp_path / 'utf8-launcher-fixture'
    config_dir = fixture_root / 'config'
    config_dir.mkdir(parents=True)
    service_path = config_dir / 'grokbuddy.service.json'
    registry_path = config_dir / 'reviewer-registry.json'
    service_path.write_text(json.dumps({
        'reviewerActor': B_ACTOR,
        'reviewerRegistryPath': 'config/reviewer-registry.json',
    }, ensure_ascii=False), encoding='utf-8')
    registry_path.write_text(json.dumps({
        'activeReviewer': B_ACTOR,
        'reviewers': {
            B_ACTOR: {
                'displayName': 'workbuddy审核员',
            },
        },
    }, ensure_ascii=False), encoding='utf-8')
    probe = tmp_path / 'parse-launcher-json.ps1'
    probe.write_text("""param([string]$RepoRoot)
$ErrorActionPreference = 'Stop'
$ConfigPath = Join-Path $RepoRoot 'config\\grokbuddy.service.json'
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding utf8 | ConvertFrom-Json
$reviewerRegistryPath = Join-Path $RepoRoot $config.reviewerRegistryPath
$reviewerRegistry = Get-Content -LiteralPath $reviewerRegistryPath -Raw -Encoding utf8 | ConvertFrom-Json
if ([string]$config.reviewerActor -ne [string]$reviewerRegistry.activeReviewer) {
    throw 'reviewer actor drift'
}
if ([string]$reviewerRegistry.reviewers.'grok-reviewer-b'.displayName -cne 'workbuddy审核员') {
    throw 'UTF-8 displayName mismatch'
}
'UTF8_PARSE_OK'
""", encoding='utf-8-sig')
    powershell = shutil.which('powershell.exe') or shutil.which('pwsh')
    assert powershell is not None, 'PowerShell is required for the Windows launcher regression'
    result = subprocess.run(
        [powershell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
         '-File', str(probe), '-RepoRoot', str(fixture_root)],
        check=True, capture_output=True, text=True)
    assert result.stdout.strip() == 'UTF8_PARSE_OK'


def test_production_default_reviewer_does_not_fall_back_to_mock(tmp_path):
    runtime = LocalRuntime(
        tmp_path / 'reviewer-default', CONTRACTS,
        clock=ManualClock(), trigger_source_key=TRIGGER_KEY,
        default_reviewer_actor_id=B_ACTOR,
    )
    register_b(runtime)
    builder, planned = planned_unbound_v2_task(runtime)

    receipt = builder.invoke('request_plan_review', {
        'task_id': planned['id'],
        'expected_version': planned['version'],
        'idempotency_key': str(uuid4()),
    })
    request = runtime.hub.get_review(receipt['review_request_id'])['request']

    assert request['status'] == 'PENDING'
    assert request['envelope']['expected_reviewer_actor_id'] == B_ACTOR
    assert request['delivery_channel'] == 'REVIEWER_HTTP'
    assert runtime.dispatcher.dispatch_one() is None
    assert not runtime.queue.completed(receipt['review_request_id'])
    assert runtime.hub.get_task(planned['id'])['owner_id'] == 'workbuddy-ingress'


def test_unbound_v2_plan_is_durably_delivered_on_reviewer_http_queue(
        tmp_path):
    runtime = LocalRuntime(
        tmp_path / 'unbound-http-review', CONTRACTS,
        clock=ManualClock(), trigger_source_key=TRIGGER_KEY,
        default_reviewer_actor_id=B_ACTOR,
    )
    register_b(runtime)
    builder, planned = planned_unbound_v2_task(runtime)
    receipt = builder.invoke('request_plan_review', {
        'task_id': planned['id'],
        'expected_version': planned['version'],
        'idempotency_key': str(uuid4()),
    })
    request_id = receipt['review_request_id']
    transport = FileGitHubCommentTransport(tmp_path / 'unused-comments.json')
    intake = runtime.grok_intake(B_ACTOR)
    dispatcher = runtime.grok_dispatcher(
        transport, B_ACTOR, 'https://grokbuddy.amirhasan.top', intake=intake)
    supervisor = runtime.supervisor(
        projection_transport=transport,
        binding_policy=lambda _task: None,
        dispatcher=dispatcher,
        intake=intake,
    )

    result = supervisor.tick()

    assert result['dispatch'] == 'SENT'
    assert runtime.hub.get_review(request_id)['request']['status'] == 'PENDING'
    assert runtime.hub.get_review(request_id)['request']['delivery_channel'] == 'REVIEWER_HTTP'
    with runtime.db.transaction() as repo:
        assert repo.find('github_bindings', task_id=planned['id']) == []
        assert repo.find('grok_reviewer_routes', task_id=planned['id']) == []
        assert repo.find('outbox_events', review_request_id=request_id)[0]['status'] == 'SENT'
        assert repo.find('intake_receipts', review_request_id=request_id)[0]['status'] == 'READY'
    assert transport._load()['comments'] == []
    assert runtime.queue.completed(request_id) is False

    app = GrokReviewerApplication(runtime, dispatcher.adapter, REVIEWER_TOKEN, intake=intake)

    async def reviewer_reads():
        async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url='https://grokbuddy.amirhasan.top') as client:
            headers = {'authorization': 'Bearer ' + REVIEWER_TOKEN}
            listing = await client.get('/reviewer/requests', headers=headers)
            request = await client.get(
                f'/reviewer/requests/{request_id}', headers=headers)
            retry_listing = await client.get('/reviewer/requests', headers=headers)
            return listing, request, retry_listing

    listing, request, retry_listing = anyio.run(reviewer_reads)
    assert listing.status_code == 200
    assert [row['review_request_id'] for row in listing.json()['requests']] == [request_id]
    assert request.status_code == 200
    assert retry_listing.json()['requests'][0]['intake_status'] == 'ACKED'
    assert runtime.hub.get_review(request_id)['request']['status'] == 'PENDING'


def test_http_delivery_reconciles_publish_before_outbox_sent(tmp_path):
    runtime = LocalRuntime(
        tmp_path / 'http-publish-recovery', CONTRACTS,
        clock=ManualClock(), trigger_source_key=TRIGGER_KEY,
        default_reviewer_actor_id=B_ACTOR,
    )
    register_b(runtime)
    builder, planned = planned_unbound_v2_task(runtime)
    request_id = builder.invoke('request_plan_review', {
        'task_id': planned['id'],
        'expected_version': planned['version'],
        'idempotency_key': str(uuid4()),
    })['review_request_id']
    intake = runtime.grok_intake(B_ACTOR)
    dispatcher = runtime.grok_dispatcher(
        FileGitHubCommentTransport(tmp_path / 'recovery-comments.json'),
        B_ACTOR, 'https://grokbuddy.amirhasan.top', intake=intake)

    claimed, _ = dispatcher._claim()
    assert claimed['status'] == 'LEASED'
    intake.publish(request_id)
    runtime.clock.advance(runtime.settings.lease_seconds + 1)

    assert dispatcher.dispatch_one() == 'SENT'
    with runtime.db.transaction() as repo:
        outbox = repo.find('outbox_events', review_request_id=request_id)
        receipts = repo.find('intake_receipts', review_request_id=request_id)
    assert len(outbox) == 1
    assert outbox[0]['status'] == 'SENT'
    assert outbox[0]['attempts'] == 2
    assert len(receipts) == 1
    assert receipts[0]['status'] == 'READY'


def test_later_binding_does_not_rewrite_frozen_http_request(tmp_path):
    runtime = LocalRuntime(
        tmp_path / 'frozen-http-channel', CONTRACTS,
        clock=ManualClock(), trigger_source_key=TRIGGER_KEY,
        default_reviewer_actor_id=B_ACTOR,
    )
    register_b(runtime)
    builder, planned = planned_unbound_v2_task(runtime)
    request_id = builder.invoke('request_plan_review', {
        'task_id': planned['id'],
        'expected_version': planned['version'],
        'idempotency_key': str(uuid4()),
    })['review_request_id']
    runtime.github_bindings.bind_pull_request(
        repository_id=1372874264,
        repository_full_name='example/grokbuddy',
        pull_request_number=703,
        task_id=planned['id'],
        builder_actor_id='workbuddy-ingress',
        reviewer_actor_id=B_ACTOR,
        hub_pointer_base='https://grokbuddy.amirhasan.top',
    )
    intake = runtime.grok_intake(B_ACTOR)
    transport = FileGitHubCommentTransport(tmp_path / 'frozen-http-comments.json')
    dispatcher = runtime.grok_dispatcher(
        transport, B_ACTOR, 'https://grokbuddy.amirhasan.top', intake=intake)

    assert dispatcher.dispatch_one() == 'SENT'
    assert runtime.hub.get_review(request_id)['request']['delivery_channel'] == 'REVIEWER_HTTP'
    assert transport._load()['comments'] == []
    with runtime.db.transaction() as repo:
        assert len(repo.find('intake_receipts', review_request_id=request_id)) == 1


def test_partial_grok_route_fails_before_rr_creation_with_clear_code(tmp_path):
    runtime = LocalRuntime(
        tmp_path / 'partial-route', CONTRACTS,
        clock=ManualClock(), trigger_source_key=TRIGGER_KEY,
        default_reviewer_actor_id=B_ACTOR,
    )
    register_b(runtime)
    builder, planned = planned_unbound_v2_task(runtime)
    runtime.github_bindings.bind_pull_request(
        repository_id=1372874264,
        repository_full_name='example/grokbuddy',
        pull_request_number=702,
        task_id=planned['id'],
        builder_actor_id='workbuddy-ingress',
        reviewer_actor_id=B_ACTOR,
        hub_pointer_base='https://grokbuddy.amirhasan.top',
    )
    with runtime.db.transaction() as repo:
        before = {
            table: len(repo.find(table))
            for table in ('review_requests', 'outbox_events', 'artifacts')
        }

    with pytest.raises(ReviewDeliveryUnavailable) as rejected:
        builder.invoke('request_plan_review', {
            'task_id': planned['id'],
            'expected_version': planned['version'],
            'idempotency_key': str(uuid4()),
        })

    assert rejected.value.code == 'REVIEW_DELIVERY_UNAVAILABLE'
    with runtime.db.transaction() as repo:
        after = {table: len(repo.find(table)) for table in before}
    assert after == before


def test_production_supervisor_dispatches_and_real_http_read_acks_intake(
        flow, tmp_path):
    request_id, transport, intake, supervisor, dispatcher = routed_grok_request(
        flow, tmp_path)

    result = supervisor.tick()

    assert set(supervisor.metrics) == {
        'binding_route', 'recovery', 'dispatch', 'intake', 'event_apply', 'projection'}
    assert dispatcher.adapter.reviewer_actor_id == B_ACTOR
    assert result['dispatch'] == 'SENT'
    assert result['intake'] == 'DISCOVERABLE'
    assert not flow.rows('mock_jobs', id=request_id)
    receipt = flow.rows('intake_receipts', review_request_id=request_id)[0]
    assert receipt['status'] == 'READY'

    app = GrokReviewerApplication(
        flow.r, dispatcher.adapter, REVIEWER_TOKEN, intake=intake)

    async def read_request():
        async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url='https://grokbuddy.amirhasan.top') as client:
            return await client.get(
                f'/reviewer/requests/{request_id}',
                headers={'authorization': 'Bearer ' + REVIEWER_TOKEN})

    response = anyio.run(read_request)
    assert response.status_code == 200
    assert flow.rows('intake_receipts', review_request_id=request_id)[0]['status'] == 'ACKED'
    assert len(transport._load()['comments']) == 1
    assert flow.h.get_review(request_id)['request']['status'] == 'PENDING'


def test_composite_main_starts_supervisor_and_stops_it_with_uvicorn(
        tmp_path, monkeypatch, capsys):
    runtime_dir = tmp_path / 'formal-runtime'
    seed = LocalRuntime(runtime_dir, CONTRACTS)
    register_b(seed)
    monkeypatch.setenv('GITHUB_WEBHOOK_SECRET', 'local-webhook-secret')
    monkeypatch.setenv('GROKBUDDY_MCP_TOKEN', 'local-mcp-token')
    monkeypatch.setenv('GROKBUDDY_GROK_REVIEWER_TOKEN', REVIEWER_TOKEN)
    monkeypatch.setenv('GITHUB_COMMENT_TOKEN', 'local-github-comment-token')
    captured = {}

    def fake_uvicorn_run(application, **kwargs):
        captured['application'] = application
        captured['kwargs'] = kwargs
        deadline = time.monotonic() + 2
        while not application.supervisor_service.is_ready() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert application.supervisor_service.is_ready()

        async def ready_probe():
            async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=application),
                    base_url='http://127.0.0.1:8788') as client:
                return await client.get('/ready')

        response = anyio.run(ready_probe)
        assert response.status_code == 200
        assert response.json() == {
            'checks': {'database': 'ok', 'supervisor': 'ok'},
            'status': 'ready',
        }

    monkeypatch.setattr(uvicorn, 'run', fake_uvicorn_run)
    result = grokbuddy_composite.main([
        '--runtime-dir', str(runtime_dir),
        '--contracts-dir', str(CONTRACTS),
        '--host', '127.0.0.1',
        '--port', '8788',
        '--public-base-url', 'https://grokbuddy.amirhasan.top',
        '--grok-reviewer-actor', B_ACTOR,
        '--supervisor-interval-seconds', '0.01',
    ])

    assert result == 0
    assert captured['application'].supervisor_service.status()['cycles'] >= 1
    assert captured['application'].supervisor_service.status()['running'] is False
    assert captured['kwargs']['port'] == 8788
    stderr = capsys.readouterr().err
    assert 'GROKBUDDY_SUPERVISOR_STARTED' in stderr
    assert 'GROKBUDDY_SUPERVISOR_STOPPED' in stderr


def test_supervisor_thread_failure_is_not_ready():
    class BrokenSupervisor:
        metrics = {'broken': {}}

        @staticmethod
        def run_forever(_stop, interval_seconds=5, on_cycle=None):
            raise RuntimeError('synthetic local thread failure')

    service = SupervisorService(BrokenSupervisor(), interval_seconds=0.01)
    service.start()
    deadline = time.monotonic() + 2
    while service.status()['running'] and time.monotonic() < deadline:
        time.sleep(0.01)
    service.stop()

    assert service.is_ready() is False
    assert service.status()['fatal_error_code'] == 'RuntimeError'


def test_composite_readiness_fails_closed_when_supervisor_is_unavailable(runtime):
    application = create_composite_application(
        runtime,
        'local-webhook-secret',
        'local-mcp-token',
        supervisor_readiness_check=lambda: False,
    )

    async def probe():
        async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=application),
                base_url='http://127.0.0.1:8788') as client:
            return await client.get('/health'), await client.get('/ready')

    health, ready = anyio.run(probe)
    assert health.status_code == 200
    assert ready.status_code == 503
    assert ready.json() == {
        'checks': {'database': 'ok', 'supervisor': 'unavailable'},
        'status': 'not_ready',
    }
