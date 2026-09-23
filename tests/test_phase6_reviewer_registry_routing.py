import json
from pathlib import Path
from uuid import uuid4

import pytest

from conftest import CONTRACTS, Flow
from grokbuddy.domain.model import HubError, PermissionDenied
from grokbuddy.infrastructure.clock import ManualClock
from grokbuddy.infrastructure.reviewer_registry import (
    ReviewerRegistry,
    load_service_reviewer_registry,
)
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.interfaces.gateway import ClientGateway
from scripts import grokbuddy_composite


REVIEWER_1 = "workbuddy-reviewer-001"
REVIEWER_2 = "workbuddy-reviewer-002"
AGENT_1 = "10000000-0000-4000-8000-000000000001"
AGENT_2 = "20000000-0000-4000-8000-000000000002"
CREDENTIAL_REF = "GrokBuddy/GROKBUDDY_GROK_REVIEWER_TOKEN"


def registry_document(active=REVIEWER_1, *, enabled_1=True, include_active=True):
    document = {
        "version": 1,
        "reviewers": {
            REVIEWER_1: {
                "displayName": "WorkBuddy审核员",
                "enabled": enabled_1,
                "credentialRef": CREDENTIAL_REF,
                "connector": {
                    "type": "grok_bot",
                    "agentId": AGENT_1,
                    "serverId": "1001",
                },
            },
            REVIEWER_2: {
                "displayName": "审核员1",
                "enabled": True,
                "credentialRef": CREDENTIAL_REF,
                "connector": {
                    "type": "grok_bot",
                    "agentId": AGENT_2,
                    "serverId": "1002",
                },
            },
        },
    }
    if include_active:
        document["activeReviewer"] = active
    return document


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def load_registry(tmp_path, document):
    return ReviewerRegistry.load(write_json(tmp_path / str(uuid4()), document))


def routed_plan_request(runtime, reviewer_id, pull_request_number):
    flow = Flow(runtime)
    flow.plan()
    runtime.github_bindings.bind_pull_request(
        repository_id=9001,
        repository_full_name="example/reviewer-registry",
        pull_request_number=pull_request_number,
        task_id=flow.id,
        reviewer_actor_id=reviewer_id,
        hub_pointer_base="https://grokbuddy.example.invalid",
    )
    runtime.hub.route_future_reviews(
        "builder", flow.id, reviewer_id, flow.version, flow.key())
    receipt = ClientGateway(runtime).invoke("request_plan_review", {
        "task_id": flow.id,
        "expected_version": flow.version,
        "idempotency_key": flow.key(),
    })
    return flow, receipt["review_request_id"]


def test_active_change_after_restart_only_changes_later_request(tmp_path):
    registry_1 = load_registry(tmp_path, registry_document(REVIEWER_1))
    runtime_dir = tmp_path / "registry-runtime"
    runtime_1 = LocalRuntime(
        runtime_dir, CONTRACTS, clock=ManualClock(), legacy_create_test_mode=True,
        default_reviewer_actor_id=registry_1.active_reviewer_actor_id,
    )
    registry_1.register_with(runtime_1)
    old_flow, old_request = routed_plan_request(runtime_1, REVIEWER_1, 101)
    old_before = runtime_1.hub.get_review(old_request)["request"]["envelope"]
    assert old_before["expected_reviewer_actor_id"] == REVIEWER_1

    registry_2 = load_registry(tmp_path, registry_document(REVIEWER_2))
    runtime_2 = LocalRuntime(
        runtime_dir, CONTRACTS, clock=ManualClock(), legacy_create_test_mode=True,
        default_reviewer_actor_id=registry_2.active_reviewer_actor_id,
    )
    registry_2.register_with(runtime_2)
    _, new_request = routed_plan_request(runtime_2, REVIEWER_2, 102)

    old_after = runtime_2.hub.get_review(old_request)["request"]["envelope"]
    new_envelope = runtime_2.hub.get_review(new_request)["request"]["envelope"]
    assert old_after == old_before
    assert old_after["expected_reviewer_actor_id"] == REVIEWER_1
    assert new_envelope["expected_reviewer_actor_id"] == REVIEWER_2

    old_review_id = runtime_2.hub.get_review(old_request)["request"]["review_id"]
    with pytest.raises(PermissionDenied):
        runtime_2.hub.validate_grok_event_route(
            REVIEWER_2, old_request, old_flow.id, old_review_id)


@pytest.mark.parametrize("document", [
    registry_document("unknown-reviewer"),
    registry_document(REVIEWER_1, enabled_1=False),
    registry_document(include_active=False),
])
def test_unknown_disabled_or_missing_active_fails_closed(tmp_path, document):
    with pytest.raises(HubError):
        ReviewerRegistry.load(write_json(tmp_path / str(uuid4()), document))


def test_malformed_or_secret_bearing_registry_fails_closed(tmp_path):
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(HubError):
        ReviewerRegistry.load(malformed)

    document = registry_document()
    document["reviewers"][REVIEWER_1]["token"] = "must-not-be-accepted"
    with pytest.raises(HubError):
        ReviewerRegistry.load(write_json(tmp_path / "secret.json", document))


def test_service_legacy_assertion_cannot_override_registry(tmp_path):
    root = tmp_path / "repository"
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    write_json(config_dir / "reviewers.json", registry_document(REVIEWER_2))
    service = {
        "reviewerActor": REVIEWER_1,
        "reviewerRegistryPath": "config/reviewers.json",
    }
    service_path = write_json(config_dir / "service.json", service)
    with pytest.raises(HubError):
        load_service_reviewer_registry(service_path)


def test_composite_startup_selection_rejects_invalid_registry(tmp_path):
    invalid = write_json(
        tmp_path / "disabled.json",
        registry_document(REVIEWER_1, enabled_1=False),
    )
    args = grokbuddy_composite._parser().parse_args([
        "--runtime-dir", str(tmp_path / "runtime"),
        "--reviewer-registry", str(invalid),
    ])
    with pytest.raises(HubError):
        grokbuddy_composite._reviewer_configuration(args)


def test_formal_registry_keeps_verified_production_default_and_no_secret_value(tmp_path):
    root = Path(__file__).resolve().parents[1]
    registry, path = load_service_reviewer_registry(
        root / "config" / "grokbuddy.service.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert registry.active_reviewer_actor_id == "grok-reviewer-b"
    assert registry.active.credential_ref == CREDENTIAL_REF
    assert set(raw["reviewers"]["grok-reviewer-b"]) == {
        "connector", "credentialRef", "displayName", "enabled"}
    assert "Bearer " not in path.read_text(encoding="utf-8")

    runtime = LocalRuntime(
        tmp_path / "formal-default", CONTRACTS, clock=ManualClock(),
        legacy_create_test_mode=True,
        default_reviewer_actor_id=registry.active_reviewer_actor_id,
    )
    registry.register_with(runtime)
    _, request_id = routed_plan_request(runtime, "grok-reviewer-b", 103)
    envelope = runtime.hub.get_review(request_id)["request"]["envelope"]
    assert envelope["expected_reviewer_actor_id"] == "grok-reviewer-b"
