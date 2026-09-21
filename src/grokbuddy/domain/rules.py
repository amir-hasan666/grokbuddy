from .model import (TaskState as T, FindingStatus as F, Role, Verdict,
                    CLOSED_FINDING, TERMINAL, IllegalTransition)


# Event-labelled edges: a caller cannot obtain a transition by requesting a state.
TASK_EDGES = {
    "begin_plan": ({T.NEW, T.PLAN_CHANGES_REQUIRED}, T.PLANNING),
    "request_plan": ({T.PLANNING}, T.PLAN_REVIEW_PENDING),
    "plan_started": ({T.PLAN_REVIEW_PENDING}, T.PLAN_REVIEWING),
    "plan_pass": ({T.PLAN_REVIEW_PENDING, T.PLAN_REVIEWING}, T.PLAN_APPROVED),
    "plan_changes": ({T.PLAN_REVIEW_PENDING, T.PLAN_REVIEWING}, T.PLAN_CHANGES_REQUIRED),
    "plan_human_review": ({T.NEW, T.PLANNING, T.PLAN_REVIEW_PENDING,
                            T.PLAN_REVIEWING, T.PLAN_CHANGES_REQUIRED}, T.PLAN_HUMAN_REVIEW),
    "plan_block": ({T.PLAN_REVIEW_PENDING, T.PLAN_REVIEWING}, T.BLOCKED),
    "execute": ({T.PLAN_APPROVED, T.FINAL_CHANGES_REQUIRED}, T.EXECUTING),
    "self_test": ({T.EXECUTING}, T.SELF_TESTING),
    "self_test_failed": ({T.SELF_TESTING}, T.EXECUTING),
    "request_final": ({T.SELF_TESTING}, T.FINAL_REVIEW_PENDING),
    "final_started": ({T.FINAL_REVIEW_PENDING}, T.FINAL_REVIEWING),
    "final_pass": ({T.FINAL_REVIEW_PENDING, T.FINAL_REVIEWING}, T.DONE),
    "final_changes": ({T.FINAL_REVIEW_PENDING, T.FINAL_REVIEWING}, T.FINAL_CHANGES_REQUIRED),
    "final_human_review": ({T.PLAN_APPROVED, T.EXECUTING, T.SELF_TESTING,
                             T.FINAL_REVIEW_PENDING, T.FINAL_REVIEWING,
                             T.FINAL_CHANGES_REQUIRED}, T.FINAL_HUMAN_REVIEW),
    "human_accept_plan": ({T.PLAN_HUMAN_REVIEW}, T.PLAN_APPROVED),
    "human_accept_final": ({T.FINAL_HUMAN_REVIEW}, T.DONE),
    "human_modify_plan": ({T.PLAN_HUMAN_REVIEW}, T.PLANNING),
    "human_modify_final": ({T.FINAL_HUMAN_REVIEW}, T.EXECUTING),
    "human_modify_final_replan": ({T.FINAL_HUMAN_REVIEW}, T.PLANNING),
    "human_continue_plan": ({T.PLAN_HUMAN_REVIEW}, T.PLANNING),
    "human_continue_final": ({T.FINAL_HUMAN_REVIEW}, T.SELF_TESTING),
    "human_continue_final_rework": ({T.FINAL_HUMAN_REVIEW}, T.EXECUTING),
    "final_block": ({T.FINAL_REVIEW_PENDING, T.FINAL_REVIEWING}, T.BLOCKED),
    "scope_replan": ({T.FINAL_CHANGES_REQUIRED, T.EXECUTING}, T.PLANNING),
    "request_approval": ({T.EXECUTING}, T.AWAITING_HUMAN_APPROVAL),
    "approve_action": ({T.AWAITING_HUMAN_APPROVAL}, T.EXECUTING),
    "reject_replan": ({T.AWAITING_HUMAN_APPROVAL}, T.PLANNING),
    "resume_plan": ({T.BLOCKED, T.ESCALATED}, T.PLANNING),
    "resume_final": ({T.BLOCKED, T.ESCALATED}, T.EXECUTING),
    "override_plan": ({T.PLAN_REVIEW_PENDING, T.PLAN_REVIEWING, T.PLAN_CHANGES_REQUIRED,
                       T.BLOCKED, T.ESCALATED}, T.PLAN_APPROVED),
    "override_final": ({T.FINAL_REVIEW_PENDING, T.FINAL_REVIEWING, T.FINAL_CHANGES_REQUIRED,
                        T.BLOCKED, T.ESCALATED}, T.DONE),
    "cancel": (set(T) - TERMINAL, T.CANCELLED),
    "fail": (set(T) - TERMINAL, T.FAILED),
    "escalate": (set(T) - TERMINAL - {T.ESCALATED}, T.ESCALATED),
}


def transition(state: str, event: str) -> str:
    edge = TASK_EDGES.get(event)
    if not edge or state not in edge[0]:
        raise IllegalTransition(f"Cannot apply {event} to {state}")
    return edge[1].value


FINDING_EDGES = {
    "accept": (Role.BUILDER, {F.OPEN, F.REJECTED_WITH_EVIDENCE}, F.ACCEPTED),
    "reject": (Role.BUILDER, {F.OPEN, F.ACCEPTED}, F.REJECTED_WITH_EVIDENCE),
    "fix": (Role.BUILDER, {F.ACCEPTED}, F.FIXED),
    "verify": (Role.REVIEWER, {F.FIXED, F.REJECTED_WITH_EVIDENCE}, F.VERIFIED),
    "reopen": (Role.REVIEWER, {F.FIXED, F.REJECTED_WITH_EVIDENCE}, F.OPEN),
    "waive": (Role.HUMAN, set(F) - CLOSED_FINDING, F.WAIVED_BY_HUMAN),
}


def finding_transition(state: str, action: str, role: str) -> str:
    edge = FINDING_EDGES.get(action)
    if not edge or role != edge[0] or state not in edge[1]:
        raise IllegalTransition(f"Cannot {action} finding in {state} as {role}")
    return edge[2].value


def aggregate_verdict(findings: list[dict], reported: str) -> str:
    unresolved = [f for f in findings if f['status'] not in CLOSED_FINDING]
    calculated = (Verdict.BLOCK if any(f['severity'] == 'CRITICAL' for f in unresolved)
                  else Verdict.NEEDS_CHANGES if unresolved else Verdict.PASS)
    rank = {Verdict.PASS: 0, Verdict.NEEDS_CHANGES: 1, Verdict.BLOCK: 2}
    return max(Verdict(reported), calculated, key=rank.get).value
