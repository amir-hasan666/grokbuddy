"""Pure frozen Review bindings shared by application checks and Reviewer adapters."""


RESULT_BINDINGS = (
    'protocol_version', 'task_id', 'review_request_id', 'review_id',
    'review_type', 'review_round', 'content_revision', 'review_profile',
    'review_profile_version', 'profile_sha256', 'input_sha256',
)


def frozen_result_fields(envelope):
    result = {field: envelope[field] for field in RESULT_BINDINGS}
    if envelope['protocol_version'] == 'v2':
        result['expected_task_version'] = envelope['expected_task_version']
        if 'decision_policy_version' in envelope:
            result['decision_policy_version'] = envelope['decision_policy_version']
    return result


def result_binding_error(envelope, result, actor, task_version):
    """Shared ingress/preflight checks, after result schema validation."""
    for field in RESULT_BINDINGS:
        if result[field] != envelope[field]:
            return 'VALIDATION_FAILURE', '$.' + field, 'Result does not match frozen request'
    if result.get('decision_policy_version') != envelope.get('decision_policy_version'):
        return ('VALIDATION_FAILURE', '$.decision_policy_version',
                'Result decision policy does not match frozen request')
    for field, expected in (('id', actor['id']), ('type', actor['reviewer_type'])):
        if result['reviewer'][field] != expected:
            return ('VALIDATION_FAILURE', '$.reviewer.' + field,
                    'Result reviewer declaration mismatch')
    if result['protocol_version'] == 'v2' and result['expected_task_version'] != task_version:
        return 'CONFLICT', '$.expected_task_version', 'Review result used a stale Task version'
    return None
