"""Copy frozen Review Request fields into a Reviewer result without inference."""


def frozen_result_fields(envelope):
    fields = (
        'protocol_version', 'task_id', 'review_request_id', 'review_id',
        'review_type', 'review_round', 'content_revision', 'review_profile',
        'review_profile_version', 'profile_sha256', 'input_sha256',
    )
    result = {field: envelope[field] for field in fields}
    if envelope['protocol_version'] == 'v2':
        result['expected_task_version'] = envelope['expected_task_version']
        if 'decision_policy_version' in envelope:
            result['decision_policy_version'] = envelope['decision_policy_version']
    return result
