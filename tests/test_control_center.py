"""Disposable Hub evidence for the authenticated read-only Control Center."""

import base64
import json

import anyio
import httpx2
import pytest

from grokbuddy.interfaces.composite import create_composite_application
from grokbuddy.interfaces.control_center_query import ControlCenterQuery, review_label
from grokbuddy.domain.model import HubError
from test_phase6_pack_b import V2Flow, key
from test_v1_dual_round_decisions import _apply, _result, _revised_plan


TOKEN = "control-center-test-token-at-least-32-bytes"
AUTH = {
    "authorization": "Basic " + base64.b64encode(("human:" + TOKEN).encode()).decode()
}


@pytest.mark.parametrize("kind", ["PLAN_REVIEW", "FINAL_REVIEW"])
@pytest.mark.parametrize("round_number", [1, 2])
@pytest.mark.parametrize("verdict", ["PASS", "NEEDS_CHANGES", "BLOCK"])
def test_v1_round_labels(kind, round_number, verdict):
    request = {"status": "COMPLETED", "review_type": kind, "review_round": round_number}
    label = review_label(request, {"effective_verdict": verdict}, True)
    if round_number == 2 and verdict == "BLOCK":
        assert "BLOCKED" in label
        assert ("未验收通过" in label) == (kind == "FINAL_REVIEW")
    elif round_number == 2 and verdict == "NEEDS_CHANGES":
        assert label == "无效结果"
    elif verdict == "PASS":
        assert label == ("方案已通过" if kind == "PLAN_REVIEW" else "审核通过")
    elif verdict == "NEEDS_CHANGES":
        assert label == ("方案待修订" if kind == "PLAN_REVIEW" else "代码待修改")
    else:
        assert label.startswith("R1 阻断意见")


@pytest.mark.parametrize("status", ["PENDING", "IN_PROGRESS", "TIMED_OUT", "FAILED"])
def test_pending_and_technical_events_cannot_be_pass(status):
    request = {"status": status, "review_type": "PLAN_REVIEW", "review_round": 1}
    assert "通过" not in review_label(request, None, True)
    assert "BLOCKED" not in review_label(request, None, True)


def test_plan_r2_blocked_has_hub_plan_versions_and_both_reviews(tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan("first frozen plan")
    flow.request(scenario="NEEDS_CHANGES")
    flow.drive()
    finding = flow.r.hub.list_actionable_findings(flow.task_id)[0]
    _revised_plan(flow, finding["id"])
    flow.request(scenario="BLOCK")
    flow.drive()
    detail = ControlCenterQuery(flow.r).task_detail(flow.task_id)
    block = detail["plan_r2_blocked"]
    assert detail["task"]["state"] == "PLAN_HUMAN_REVIEW"
    assert block["active"] is True
    assert block["plan_v1"]["id"] != block["plan_v2"]["id"]
    assert block["grok_r1"]["summary"]
    assert block["r2_reason"]["summary"]
    r2 = next(item for item in detail["rounds"] if item["round"] == 2)
    assert r2["label"] == "BLOCKED，等待 Human"
    assert r2["reviewer_label"] == "mock-reviewer"


def test_final_r2_blocked_keeps_file_method_tests_and_unaccepted_label(tmp_path):
    flow = V2Flow(tmp_path)
    flow.to_final_review("NEEDS_CHANGES")
    flow.fix_current_open_finding()
    flow.package()
    flow.request("FINAL_REVIEW", "BLOCK")
    flow.drive()
    query = ControlCenterQuery(flow.r)
    detail = query.task_detail(flow.task_id)
    block = detail["final_r2_blocked"]
    assert block["active"] is True
    assert block["acceptance"] == "未验收通过"
    assert block["package"]["operation_method"]
    assert len(block["package"]["generated_files"]) == 1
    assert len(block["package"]["tests"]) == 1
    assert block["r2_reason"]["summary"]
    file_id = block["package"]["generated_files"][0]["artifact"]["id"]
    _, content = query.artifact_bytes(flow.task_id, file_id)
    assert content.startswith(b"generated local file")


def test_message_capture_and_timeline_have_hub_content_and_stable_pages(tmp_path):
    flow = V2Flow(tmp_path)
    query = ControlCenterQuery(flow.r)
    for number in range(52):
        flow.r.hub.record_workbuddy_message(
            "builder", flow.task_id, "PLAN", f"Builder message {number}", key()
        )
    detail = query.task_detail(flow.task_id)
    assert len(detail["workbuddy_messages"]) == 52
    assert detail["workbuddy_messages"][0]["actor_id"] == "builder"
    cursor = None
    events = []
    while True:
        page = query.timeline(flow.task_id, cursor)
        events.extend(page["events"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(events) > 100
    assert len({(event["source"], event["id"]) for event in events}) == len(events)
    assert sum(event["source"] == "artifact" and
               event["action"] == "WORKBUDDY_MESSAGE" for event in events) == 52
    assert [query._time_key(event["at"]) for event in events] == sorted(
        query._time_key(event["at"]) for event in events)


def test_v1_retention_rejects_missing_method_bad_path_and_secret(tmp_path):
    flow = V2Flow(tmp_path)
    with pytest.raises(HubError, match="restricted content"):
        flow.r.hub.record_workbuddy_message(
            "builder", flow.task_id, "PLAN", "Authorization: Bearer unsafe", key())
    assert ControlCenterQuery(flow.r).task_detail(flow.task_id)["workbuddy_messages"] == []
    flow.approve_plan()
    flow.begin_execution()
    flow.complete_worker()
    flow.package()
    artifact = flow.r.hub.get_artifact(flow.task["current_final_id"])
    package = json.loads(flow.r.store.read(
        artifact["storage_pointer"], artifact["sha256"], artifact["size_bytes"]))
    package.pop("operation_method")
    with pytest.raises(HubError, match="operation method"):
        flow.r.hub.submit_final_package(flow.owner, flow.task_id,
                                        package, flow.version, key())
    package["operation_method"] = "Use approved local output."
    package["generated_files"][0]["path"] = "../escape.txt"
    with pytest.raises(HubError, match="relative paths"):
        flow.r.hub.submit_final_package(flow.owner, flow.task_id,
                                        package, flow.version, key())


def test_rejected_r2_result_shows_invalid_without_review_pass(tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan()
    flow.request(scenario="NEEDS_CHANGES")
    flow.drive()
    finding = flow.r.hub.list_actionable_findings(flow.task_id)[0]
    _revised_plan(flow, finding["id"])
    rr = flow.request(scenario="NEEDS_CHANGES")
    assert _apply(flow, rr, _result(flow, rr, "NEEDS_CHANGES"), "invalid-r2") == "REJECTED"
    detail = ControlCenterQuery(flow.r).task_detail(flow.task_id)
    row = next(item for item in detail["rounds"] if item["id"] == rr)
    assert row["status"] == "PENDING"
    assert row["review"] is None
    assert row["label"] == "结果无效"
    assert row["failure_code"]


@pytest.mark.parametrize("scenario", ["FAILED", "TIMEOUT"])
def test_technical_human_gate_is_not_grok_blocked(scenario, tmp_path):
    flow = V2Flow(tmp_path)
    flow.plan()
    rr = flow.request(scenario=scenario)
    flow.drive()
    if scenario == "TIMEOUT":
        flow.r.clock.advance(flow.r.settings.plan_review_timeout + 1)
        flow.r.tick()
    detail = ControlCenterQuery(flow.r).task_detail(flow.task_id)
    row = next(item for item in detail["rounds"] if item["id"] == rr)
    assert row["status"] in ("FAILED", "TIMED_OUT")
    assert row["label"] == "审核技术故障"
    assert row["review"] is None
    assert row["reviewer_label"] is None
    assert detail["plan_r2_blocked"] is None


def test_control_routes_enforce_auth_read_only_and_artifact_scope(tmp_path):
    flow = V2Flow(tmp_path)
    unrelated = flow.artifact("SOURCE_FILE", "unreferenced internal evidence")
    restricted = flow.artifact("LOG", "raw runtime log")
    flow.to_final_review("PASS")
    app = create_composite_application(
        flow.r, "webhook-secret", "remote-mcp-secret", control_token=TOKEN
    )
    detail = ControlCenterQuery(flow.r).task_detail(flow.task_id)
    generated_id = detail["packages"][0]["generated_files"][0]["artifact"]["id"]
    before_version = flow.version
    before_audit = len(flow.rows("audit_logs", task_id=flow.task_id))

    async def exercise():
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport,
                                     base_url="http://127.0.0.1:8788") as client:
            unauth = await client.get("/control/")
            wrong = await client.get("/control/api/tasks",
                                     headers={"authorization": "Bearer wrong"})
            page = await client.get("/control/", headers=AUTH)
            script = await client.get("/control/app.js", headers=AUTH)
            listed = await client.get("/control/api/tasks", headers=AUTH)
            found = await client.get(f"/control/api/tasks/{flow.task_id}", headers=AUTH)
            file = await client.get(
                f"/control/api/tasks/{flow.task_id}/artifacts/{generated_id}",
                headers=AUTH)
            excluded = await client.get(
                f"/control/api/tasks/{flow.task_id}/artifacts/{unrelated['id']}",
                headers=AUTH)
            log = await client.get(
                f"/control/api/tasks/{flow.task_id}/artifacts/{restricted['id']}",
                headers=AUTH)
            mutation = await client.post("/control/api/tasks", headers=AUTH)
            bad_cursor = await client.get(
                f"/control/api/tasks/{flow.task_id}/events?cursor=!!!",
                headers=AUTH)
            return (unauth, wrong, page, script, listed, found, file,
                    excluded, log, mutation, bad_cursor)

    results = anyio.run(exercise)
    assert [item.status_code for item in results] == [
        401, 401, 200, 200, 200, 200, 200, 403, 403, 405, 422]
    assert b"Control Center" in results[2].content
    assert b"textContent" in results[3].content
    assert results[4].json()["tasks"][0]["id"] == flow.task_id
    assert results[5].json()["rounds"][0]["reviewer_label"] == "mock-reviewer"
    assert results[6].headers["content-disposition"].startswith("attachment;")
    assert results[6].headers["cache-control"] == "no-store"
    assert b"storage_pointer" not in results[5].content
    assert b"trigger_evidence" not in results[5].content
    assert TOKEN.encode() not in b"".join(item.content for item in results)
    assert flow.version == before_version
    assert len(flow.rows("audit_logs", task_id=flow.task_id)) == before_audit
