"""Task-frozen review decision policies; protocol versions remain independent."""

V1_DUAL_ROUND = 'grokbuddy-v1-dual-round'
V1_LIMIT = 2


def is_v1_dual_round(task):
    return task.get('decision_policy_version') == V1_DUAL_ROUND
