"""Local diff-only tests for the Step 6.17 read-only evidence harness."""

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sqlite3


SCRIPT = Path(__file__).parents[1] / "scripts" / "windows" / "Test-GrokBuddyTriggerIsolation.py"
SPEC = spec_from_file_location("trigger_isolation_harness", SCRIPT)
HARNESS = module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(HARNESS)


def _database(path):
    connection = sqlite3.connect(path)
    for table in HARNESS.CORE_TABLES:
        connection.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    connection.execute("PRAGMA user_version=4")
    connection.commit()
    return connection


def _task(task_id="TASK-B", state="NEW"):
    digest = "a" * 64
    return {
        "id": task_id,
        "state": state,
        "version": 0,
        "created_at": 1,
        "conversation_id": "conversation-live",
        "grokbuddy_enabled": True,
        "trigger_message_id": "message-b",
        "trigger_evidence": {
            "phrase": HARNESS.PHRASE,
            "conversation_id": "conversation-live",
            "message_id": "message-b",
            "body_sha256": digest,
            "source_sha256": digest,
            "source_artifact_id": "ART-source",
            "source_artifact_sha256": digest,
            "start_byte": 0,
            "end_byte": len(HARNESS.PHRASE.encode("utf-8")),
            "segment_sources": ["user_body"],
        },
    }


def _snapshot(path, label):
    return HARNESS.collect_snapshot(path, label, 1000)


def test_case_a_and_bprime_require_zero_mutation(tmp_path):
    database = tmp_path / "hub.db"
    connection = _database(database)
    connection.close()
    before = _snapshot(database, "before")
    after = _snapshot(database, "after")

    assert HARNESS.compare_snapshots("A", before, after)["verdict"] == "PASS"
    assert HARNESS.compare_snapshots("BPRIME", before, after)["verdict"] == "PASS"


def test_case_b_requires_one_active_task_with_complete_evidence(tmp_path):
    database = tmp_path / "hub.db"
    connection = _database(database)
    connection.close()
    before = _snapshot(database, "b-before")
    connection = sqlite3.connect(database)
    task = _task()
    connection.execute(
        "INSERT INTO tasks(id,data) VALUES (?,?)",
        (task["id"], json.dumps(task, ensure_ascii=False, separators=(",", ":"))),
    )
    connection.commit()
    connection.close()
    after = _snapshot(database, "b-after")

    result = HARNESS.compare_snapshots("B", before, after)

    assert result["verdict"] == "PASS"
    assert result["checks"]["new_task_id"] == "TASK-B"
    assert result["checks"]["conversation_active_after_one"] is True


def test_case_c_requires_terminal_b_task_and_zero_mutation(tmp_path):
    database = tmp_path / "hub.db"
    connection = _database(database)
    task = _task(state="DONE")
    connection.execute(
        "INSERT INTO tasks(id,data) VALUES (?,?)",
        (task["id"], json.dumps(task, ensure_ascii=False, separators=(",", ":"))),
    )
    connection.commit()
    connection.close()
    before = _snapshot(database, "c-before")
    after = _snapshot(database, "c-after")

    result = HARNESS.compare_snapshots("C", before, after, task_id="TASK-B")

    assert result["verdict"] == "PASS"
    assert result["checks"]["b_task_terminal_before"] is True
    assert result["checks"]["conversation_active_after_zero"] is True


def test_zero_mutation_detects_changed_row_content(tmp_path):
    database = tmp_path / "hub.db"
    connection = _database(database)
    connection.execute(
        "INSERT INTO review_requests(id,data) VALUES (?,?)",
        ("RR-1", '{"id":"RR-1","status":"PENDING"}'),
    )
    connection.commit()
    connection.close()
    before = _snapshot(database, "before")
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE review_requests SET data=? WHERE id=?",
        ('{"id":"RR-1","status":"IN_PROGRESS"}', "RR-1"),
    )
    connection.commit()
    connection.close()
    after = _snapshot(database, "after")

    result = HARNESS.compare_snapshots("A", before, after)

    assert result["verdict"] == "FAIL"
    assert result["table_deltas"]["review_requests"]["changed_ids"] == ["RR-1"]


def test_zero_mutation_detects_empty_table_addition(tmp_path):
    database = tmp_path / "hub.db"
    connection = _database(database)
    connection.close()
    before = _snapshot(database, "before")
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE later_table (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    connection.commit()
    connection.close()
    after = _snapshot(database, "after")

    result = HARNESS.compare_snapshots("A", before, after)

    assert result["verdict"] == "FAIL"
    assert result["table_deltas"]["later_table"]["existed_before"] is False
    assert result["table_deltas"]["later_table"]["exists_after"] is True
