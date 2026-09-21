"""Read-only Phase 6.17 Hub snapshots and A/B/C trigger-isolation diffs.

This probe never imports LocalRuntime, starts the Hub, dispatches a review, or
opens SQLite for writing.  Snapshot collection runs in a child process with a
hard wall-clock timeout.  Evidence files contain row hashes and limited Task
metadata; message bodies, trigger signatures, and secrets are never emitted.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import queue
import sqlite3
import sys


SCHEMA = "grokbuddy.phase6.17.trigger-isolation.snapshot.v1"
RESULT_SCHEMA = "grokbuddy.phase6.17.trigger-isolation.result.v1"
PHRASE = "启用grokbuddy流程"
TERMINAL_STATES = {"DONE", "CANCELLED", "FAILED"}
CORE_TABLES = (
    "tasks",
    "review_requests",
    "reviews",
    "review_findings",
    "github_comment_projections",
)
ASIA_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


class ProbeError(RuntimeError):
    """A fail-closed probe setup or evidence error."""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic_json_write(path: Path, value: dict) -> None:
    path = path.resolve()
    if path.exists():
        raise ProbeError(f"Evidence output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    if partial.exists():
        raise ProbeError(f"Partial evidence output already exists: {partial}")
    try:
        partial.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(partial, path)
    finally:
        if partial.exists():
            partial.unlink()


def _safe_task(raw: dict) -> dict:
    evidence = raw.get("trigger_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    start = evidence.get("start_byte")
    end = evidence.get("end_byte")
    evidence_checks = {
        "present": bool(evidence),
        "phrase_exact": evidence.get("phrase") == PHRASE,
        "conversation_matches_task": bool(raw.get("conversation_id"))
        and evidence.get("conversation_id") == raw.get("conversation_id"),
        "message_matches_task": bool(raw.get("trigger_message_id"))
        and evidence.get("message_id") == raw.get("trigger_message_id"),
        "body_sha256_present": isinstance(evidence.get("body_sha256"), str)
        and len(evidence["body_sha256"]) == 64,
        "source_sha256_present": isinstance(evidence.get("source_sha256"), str)
        and len(evidence["source_sha256"]) == 64,
        "source_artifact_present": bool(evidence.get("source_artifact_id"))
        and isinstance(evidence.get("source_artifact_sha256"), str)
        and len(evidence["source_artifact_sha256"]) == 64,
        "byte_span_valid": type(start) is int and type(end) is int and 0 <= start < end,
        "segment_sources_present": isinstance(evidence.get("segment_sources"), list)
        and bool(evidence["segment_sources"]),
    }
    return {
        "task_id": raw.get("id"),
        "conversation_id": raw.get("conversation_id"),
        "state": raw.get("state"),
        "version": raw.get("version"),
        "created_at": raw.get("created_at"),
        "grokbuddy_enabled": raw.get("grokbuddy_enabled") is True,
        "trigger_message_id": raw.get("trigger_message_id"),
        "trigger_evidence_checks": evidence_checks,
    }


def _table_rows(connection: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    # Table names come only from sqlite_master and are quoted defensively.
    quoted = table.replace('"', '""')
    columns = {
        row[1] for row in connection.execute(f'PRAGMA table_info("{quoted}")')
    }
    if not {"id", "data"}.issubset(columns):
        raise ProbeError(f"Hub table lacks id/data columns: {table}")
    return connection.execute(
        f'SELECT id, data FROM "{quoted}" ORDER BY id'
    ).fetchall()


def collect_snapshot(database: Path, label: str, busy_timeout_ms: int) -> dict:
    database = database.resolve()
    if not database.is_file():
        raise ProbeError(f"Hub database does not exist: {database}")
    uri = database.as_uri() + "?mode=ro"
    connection = sqlite3.connect(
        uri,
        uri=True,
        timeout=busy_timeout_ms / 1000,
        isolation_level=None,
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
            raise ProbeError("SQLite query_only could not be enabled")
        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        missing = sorted(set(CORE_TABLES) - set(tables))
        if missing:
            raise ProbeError(f"Required Hub tables are missing: {', '.join(missing)}")

        connection.execute("BEGIN")
        fingerprints = {}
        task_rows = []
        for table in tables:
            rows = _table_rows(connection, table)
            row_digests = {row_id: _sha256(data) for row_id, data in rows}
            fingerprints[table] = {
                "count": len(rows),
                "rows_sha256": _sha256(
                    json.dumps(row_digests, sort_keys=True, separators=(",", ":"))
                ),
                "row_digests": row_digests,
            }
            if table == "tasks":
                for row_id, data in rows:
                    record = json.loads(data)
                    if not isinstance(record, dict) or record.get("id") != row_id:
                        raise ProbeError(f"Invalid Task JSON row: {row_id}")
                    task_rows.append(_safe_task(record))
        connection.execute("ROLLBACK")
    finally:
        connection.close()

    task_rows.sort(key=lambda item: (item.get("created_at") or -1, item["task_id"] or ""))
    active = [item for item in task_rows if item["state"] not in TERMINAL_STATES]
    active_grokbuddy = [item for item in active if item["grokbuddy_enabled"]]
    latest = task_rows[-1] if task_rows else None
    return {
        "schema": SCHEMA,
        "captured_at": datetime.now(ASIA_SHANGHAI).isoformat(timespec="seconds"),
        "label": label,
        "database": str(database),
        "sqlite_user_version": schema_version,
        "query_only": True,
        "summary": {
            "task_count": len(task_rows),
            "active_task_count": len(active),
            "active_grokbuddy_task_count": len(active_grokbuddy),
            "latest_task_id": latest["task_id"] if latest else None,
            "latest_conversation_id": latest["conversation_id"] if latest else None,
            "latest_state": latest["state"] if latest else None,
        },
        "tasks": task_rows,
        "tables": fingerprints,
    }


def _snapshot_worker(database: str, label: str, busy_timeout_ms: int, output: str, status) -> None:
    try:
        snapshot = collect_snapshot(Path(database), label, busy_timeout_ms)
        _atomic_json_write(Path(output), snapshot)
        status.put({"ok": True})
    except BaseException as exc:  # The parent receives a bounded, non-secret error.
        status.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def bounded_snapshot(database: Path, label: str, output: Path, timeout_seconds: int) -> dict:
    if timeout_seconds < 1 or timeout_seconds > 60:
        raise ProbeError("timeout-seconds must be between 1 and 60")
    output = output.resolve()
    if output.exists():
        raise ProbeError(f"Evidence output already exists: {output}")
    context = multiprocessing.get_context("spawn")
    status = context.Queue()
    process = context.Process(
        target=_snapshot_worker,
        args=(str(database), label, min(timeout_seconds * 1000, 5000), str(output), status),
    )
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(5)
        partial = output.with_name(output.name + ".partial")
        if partial.exists():
            partial.unlink()
        raise ProbeError(f"Snapshot exceeded hard timeout of {timeout_seconds}s")
    try:
        result = status.get(timeout=1)
    except queue.Empty as exc:
        raise ProbeError(f"Snapshot worker exited without evidence (exit={process.exitcode})") from exc
    finally:
        status.close()
        status.join_thread()
    if not result.get("ok"):
        raise ProbeError(result.get("error", "Snapshot worker failed"))
    return json.loads(output.read_text(encoding="utf-8"))


def _load_snapshot(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProbeError(f"Cannot read snapshot {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ProbeError(f"Unsupported snapshot schema: {path}")
    return value


def _table_deltas(before: dict, after: dict) -> dict:
    names = sorted(set(before["tables"]) | set(after["tables"]))
    deltas = {}
    for name in names:
        existed_before = name in before["tables"]
        exists_after = name in after["tables"]
        old = before["tables"].get(name, {"count": 0, "row_digests": {}})
        new = after["tables"].get(name, {"count": 0, "row_digests": {}})
        old_rows, new_rows = old["row_digests"], new["row_digests"]
        added = sorted(set(new_rows) - set(old_rows))
        removed = sorted(set(old_rows) - set(new_rows))
        changed = sorted(
            row_id for row_id in set(old_rows) & set(new_rows)
            if old_rows[row_id] != new_rows[row_id]
        )
        deltas[name] = {
            "existed_before": existed_before,
            "exists_after": exists_after,
            "count_before": old["count"],
            "count_after": new["count"],
            "count_delta": new["count"] - old["count"],
            "added_ids": added,
            "removed_ids": removed,
            "changed_ids": changed,
        }
    return deltas


def _task_map(snapshot: dict) -> dict[str, dict]:
    return {task["task_id"]: task for task in snapshot["tasks"]}


def _active_for_conversation(snapshot: dict, conversation_id: str) -> list[dict]:
    return [
        task for task in snapshot["tasks"]
        if task["conversation_id"] == conversation_id
        and task["state"] not in TERMINAL_STATES
        and task["grokbuddy_enabled"]
    ]


def compare_snapshots(
    case: str,
    before: dict,
    after: dict,
    task_id: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    case = case.upper()
    deltas = _table_deltas(before, after)
    failures = []
    checks = {}
    all_unchanged = all(
        delta["existed_before"] == delta["exists_after"]
        and not delta["added_ids"]
        and not delta["removed_ids"]
        and not delta["changed_ids"]
        for delta in deltas.values()
    ) and before["sqlite_user_version"] == after["sqlite_user_version"]

    if before["database"] != after["database"]:
        failures.append("before/after snapshots refer to different Hub databases")

    if case in {"A", "C", "BPRIME"}:
        checks["all_hub_tables_unchanged"] = all_unchanged
        if not all_unchanged:
            failures.append("one or more Hub tables changed; expected zero mutation")

    before_tasks, after_tasks = _task_map(before), _task_map(after)
    if case == "B":
        task_delta = deltas["tasks"]
        exactly_one = (
            task_delta["count_delta"] == 1
            and len(task_delta["added_ids"]) == 1
            and not task_delta["removed_ids"]
            and not task_delta["changed_ids"]
        )
        checks["exactly_one_new_task"] = exactly_one
        if not exactly_one:
            failures.append("B must add exactly one Task without removing/changing pre-existing Tasks")
        if task_delta["added_ids"]:
            new_task_id = task_delta["added_ids"][0]
            new_task = after_tasks[new_task_id]
            actual_conversation = new_task.get("conversation_id")
            evidence_ok = all(new_task["trigger_evidence_checks"].values())
            active_after = (
                _active_for_conversation(after, actual_conversation)
                if actual_conversation else []
            )
            active_before = (
                _active_for_conversation(before, actual_conversation)
                if actual_conversation else []
            )
            checks.update({
                "new_task_id": new_task_id,
                "conversation_id": actual_conversation,
                "new_task_nonterminal": new_task["state"] not in TERMINAL_STATES,
                "grokbuddy_enabled": new_task["grokbuddy_enabled"],
                "trigger_evidence_complete": evidence_ok,
                "conversation_active_before_zero": len(active_before) == 0,
                "conversation_active_after_one": len(active_after) == 1,
            })
            for name in (
                "new_task_nonterminal",
                "grokbuddy_enabled",
                "trigger_evidence_complete",
                "conversation_active_before_zero",
                "conversation_active_after_one",
            ):
                if not checks[name]:
                    failures.append(f"B check failed: {name}")
            if conversation_id is not None:
                checks["expected_conversation_matches"] = actual_conversation == conversation_id
                if not checks["expected_conversation_matches"]:
                    failures.append("B Task conversation_id differs from the expected conversation")

    if case == "C":
        if not task_id:
            failures.append("C requires --task-id for the Task created in B")
        elif task_id not in before_tasks or task_id not in after_tasks:
            failures.append("B Task is absent from the C before/after snapshot")
        else:
            old_task, new_task = before_tasks[task_id], after_tasks[task_id]
            actual_conversation = old_task.get("conversation_id")
            checks.update({
                "b_task_terminal_before": old_task["state"] in TERMINAL_STATES,
                "b_task_terminal_after": new_task["state"] in TERMINAL_STATES,
                "b_task_conversation_stable": bool(actual_conversation)
                and new_task.get("conversation_id") == actual_conversation,
                "conversation_active_before_zero": len(
                    _active_for_conversation(before, actual_conversation)
                ) == 0,
                "conversation_active_after_zero": len(
                    _active_for_conversation(after, actual_conversation)
                ) == 0,
                "conversation_id": actual_conversation,
            })
            for name in (
                "b_task_terminal_before",
                "b_task_terminal_after",
                "b_task_conversation_stable",
                "conversation_active_before_zero",
                "conversation_active_after_zero",
            ):
                if not checks[name]:
                    failures.append(f"C precondition/check failed: {name}")
            if conversation_id is not None:
                checks["expected_conversation_matches"] = actual_conversation == conversation_id
                if not checks["expected_conversation_matches"]:
                    failures.append("C Task conversation_id differs from the expected conversation")

    changed_tables = [
        name for name, delta in deltas.items()
        if delta["existed_before"] != delta["exists_after"]
        or delta["added_ids"]
        or delta["removed_ids"]
        or delta["changed_ids"]
    ]
    return {
        "schema": RESULT_SCHEMA,
        "evaluated_at": datetime.now(ASIA_SHANGHAI).isoformat(timespec="seconds"),
        "case": case,
        "verdict": "PASS" if not failures else "FAIL",
        "before_label": before["label"],
        "after_label": after["label"],
        "checks": checks,
        "changed_tables": changed_tables,
        "table_deltas": deltas,
        "failures": failures,
        "boundary": "Local read-only diff evidence only; not a WorkBuddy signer or Phase 6.20 E2E.",
    }


def _print_snapshot(snapshot: dict, output: Path) -> None:
    summary = snapshot["summary"]
    print("PHASE6-STEP6.17 SNAPSHOT: PASS")
    print(f"output={output.resolve()}")
    print(f"captured_at={snapshot['captured_at']}")
    print(f"query_only={str(snapshot['query_only']).lower()}")
    for key in (
        "task_count",
        "active_task_count",
        "active_grokbuddy_task_count",
        "latest_task_id",
        "latest_conversation_id",
        "latest_state",
    ):
        print(f"{key}={summary[key]}")


def _print_result(result: dict, output: Path) -> None:
    print(f"PHASE6-STEP6.17 CASE {result['case']}: {result['verdict']}")
    print(f"output={output.resolve()}")
    print(f"changed_tables={','.join(result['changed_tables']) or '(none)'}")
    for name, value in result["checks"].items():
        print(f"{name}={value}")
    for failure in result["failures"]:
        print(f"failure={failure}")


def _parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Read-only Phase 6.17 Hub snapshot and trigger-isolation diff probe."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot", help="Capture a query-only Hub snapshot.")
    snapshot.add_argument(
        "--database",
        type=Path,
        default=root / "var" / "github-manual" / "hub.db",
    )
    snapshot.add_argument("--label", required=True)
    snapshot.add_argument("--output", required=True, type=Path)
    snapshot.add_argument("--timeout-seconds", type=int, default=10)

    compare = subparsers.add_parser("compare", help="Compare two saved snapshots.")
    compare.add_argument("--case", required=True, choices=("A", "B", "C", "BPRIME"))
    compare.add_argument("--before", required=True, type=Path)
    compare.add_argument("--after", required=True, type=Path)
    compare.add_argument("--output", required=True, type=Path)
    compare.add_argument("--task-id")
    compare.add_argument("--conversation-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "snapshot":
            snapshot = bounded_snapshot(
                args.database, args.label, args.output, args.timeout_seconds
            )
            _print_snapshot(snapshot, args.output)
            return 0
        before = _load_snapshot(args.before)
        after = _load_snapshot(args.after)
        result = compare_snapshots(
            args.case,
            before,
            after,
            task_id=args.task_id,
            conversation_id=args.conversation_id,
        )
        _atomic_json_write(args.output, result)
        _print_result(result, args.output)
        return 0 if result["verdict"] == "PASS" else 1
    except ProbeError as exc:
        print(f"PHASE6-STEP6.17 PROBE: ERROR\nerror={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
