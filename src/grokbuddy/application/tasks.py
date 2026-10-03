import json
import hashlib
import re
from grokbuddy.domain.model import (ACTIVE_REQUEST, ActiveConversationTask, HubError,
                                    PermissionDenied, Role, TERMINAL,
                                    TriggerEvidenceInvalid, TriggerEvidenceRequired)
from .common import Services, audit, uid, canonical, digest
from .trigger import verify_trigger
from grokbuddy.domain.review_policy import V1_DUAL_ROUND, V1_LIMIT


def _validated_scope(scope):
    if not isinstance(scope, dict) or not scope or set(scope) - {'summary', 'files', 'components'}:
        raise HubError('Plan scope must be a non-empty structured object')
    normalized = {}
    if 'summary' in scope:
        if not isinstance(scope['summary'], str) or not scope['summary'].strip():
            raise HubError('Scope summary must be a non-empty string')
        normalized['summary'] = scope['summary'].strip()
    for field in ('files', 'components'):
        if field in scope:
            values = scope[field]
            if (not isinstance(values, list) or not values
                    or not all(isinstance(value, str) and value.strip() for value in values)):
                raise HubError(f'Scope {field} must contain non-empty strings')
            cleaned = [value.strip() for value in values]
            if len(set(cleaned)) != len(cleaned):
                raise HubError(f'Scope {field} must not contain duplicates')
            normalized[field] = cleaned
    return normalized


def _scope_within(proposed, approved):
    proposed = _validated_scope(proposed)
    if not isinstance(approved, dict):
        return False, proposed
    for field in ('files', 'components'):
        if field in proposed and not set(proposed[field]).issubset(set(approved.get(field, []))):
            return False, proposed
    return True, proposed


def _display_file_path(path):
    """A package filename is a relative display name, never a host file path."""
    return (isinstance(path, str) and 1 <= len(path) <= 500
            and not path.startswith('/') and '\\' not in path and ':' not in path
            and not any(ord(char) < 32 for char in path)
            and not path.lower().endswith(('.log', '.trace'))
            and 'logs' not in (part.lower() for part in path.split('/'))
            and all(part not in ('', '.', '..') for part in path.split('/')))


_RESTRICTED_TEXT = re.compile(
    r"(?im)^\s*authorization\s*:|(?:secret|token|password|api[_-]?key)\s*[:=]"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+\S+"
    r"|\b[A-Za-z]:\\|\\\\[^\s\\]+\\"
    r"|(?<![A-Za-z0-9])/(?:home|Users|tmp|var|mnt|etc)/"
)


class TaskService(Services):
    def record_workbuddy_message(self, actor_id, task_id, stage, body, key):
        """Capture one Task business message without changing Task/Review state."""
        if stage not in {'PLAN', 'PLAN_REVISION', 'CODE', 'TEST', 'DELIVERY'}:
            raise HubError('Unknown WorkBuddy message stage')
        if not isinstance(body, str) or not body.strip() or len(body) > 64000:
            raise HubError('WorkBuddy message must contain 1 to 64000 characters')
        if _RESTRICTED_TEXT.search(body):
            raise HubError('WorkBuddy message contains restricted content')
        with self.command(actor_id, 'record_workbuddy_message', key,
                          [task_id, stage, body], Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            if actor.get('worker_type') or actor.get('trigger_source'):
                raise PermissionDenied('Ordinary Builder principal required')
            self.task_for(repo, task_id, actor, live=False)
            result = self.add_artifact(
                repo, task_id, actor, 'WORKBUDDY_MESSAGE',
                canonical({'schema_version': 1, 'stage': stage, 'body': body}),
                'application/json')
            audit(repo, self.clock, actor, 'WORKBUDDY_MESSAGE_RECORDED', task_id,
                  artifact_id=result['id'], stage=stage)
            box['response'] = result
            return result

    def create_task(self, actor_id, description, key, profile='generic', profile_version='1.0',
                    trigger_evidence=None):
        if not isinstance(description, str) or not description.strip():
            raise HubError('Original task is required')
        params = [description, profile, profile_version, trigger_evidence]
        # A rejected create must not leave a command receipt or rejection audit.
        with self.command(actor_id, 'create_task', key, params, Role.BUILDER,
                          audit_rejection=False) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            repo.get('review_profiles', profile + '@' + profile_version)
            if trigger_evidence is None:
                if not getattr(self, 'legacy_create_test_mode', False):
                    raise TriggerEvidenceRequired('Current user trigger evidence is required')
                frozen, source_bytes = None, None
            else:
                if actor.get('trigger_source') != 'workbuddy':
                    raise PermissionDenied('Dedicated WorkBuddy ingress principal required')
                frozen, source_bytes = verify_trigger(
                    trigger_evidence, description, actor_id,
                    getattr(self, 'trigger_source_key', None), self.clock.now())
                existing = repo.find('tasks', conversation_id=frozen['conversation_id'])
                if any(task['state'] not in TERMINAL for task in existing):
                    raise ActiveConversationTask('Conversation already has an active GrokBuddy Task')
                if any(task.get('trigger_message_id') == frozen['message_id'] for task in existing):
                    raise TriggerEvidenceInvalid('Current user message was already used to create a Task')
            task = dict(id=uid('TASK'), owner_id=actor_id, state='NEW', version=0, created_at=self.clock.now(),
                        deadline_at=self.clock.now() + self.settings.max_task_duration * 1_000_000,
                        profile=profile, profile_version=profile_version, content_revision=0,
                        current_plan_id=None, approved_plan_id=None, current_final_id=None, active_rr_id=None,
                        self_test_id=None, total_findings_created=0, escalation_reason=None,
                         revision_round=0,
                         completion_basis=None, gate_reason=None, automation_frozen=False,
                         plan_limit=V1_LIMIT if frozen else self.settings.max_plan_review_rounds,
                         final_limit=V1_LIMIT if frozen else self.settings.max_final_review_rounds,
                         decision_policy_version=V1_DUAL_ROUND if frozen else None,
                         decision_policy_snapshot=(dict(version=V1_DUAL_ROUND,
                                                        plan_max_rounds=V1_LIMIT,
                                                        final_max_rounds=V1_LIMIT) if frozen else None),
                         plan_extra_budget=0, final_extra_budget=0,
                        review_protocol_version='v2' if frozen is not None else 'v1',
                        grokbuddy_enabled=frozen is not None,
                        conversation_id=frozen['conversation_id'] if frozen else None,
                        trigger_message_id=frozen['message_id'] if frozen else None,
                        trigger_evidence=frozen)
            repo.add('tasks', task)
            if frozen:
                source = self.add_artifact(repo, task['id'], actor, 'SOURCE_FILE',
                                           source_bytes, 'application/json')
                task['trigger_evidence'] = {**frozen, 'source_artifact_id': source['id'],
                                            'source_artifact_sha256': source['sha256']}
            original = self.add_artifact(repo, task['id'], actor, 'SOURCE_FILE', description.encode('utf-8'), 'text/plain')
            task['original_task_id'] = original['id']
            repo.save('tasks', task)
            audit(repo, self.clock, actor, 'TASK_CREATED', task['id'], new='NEW',
                  trigger_source_sha256=frozen['source_sha256'] if frozen else None)
            box['response'] = task
            return task

    def get_conversation_context(self, conversation_id):
        """Derive task-scoped context from Hub state; terminal Tasks cannot stick."""
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise HubError('conversation_id is required')
        with self.db.transaction() as repo:
            active = [task for task in repo.find('tasks', conversation_id=conversation_id)
                      if task['state'] not in TERMINAL and task.get('grokbuddy_enabled')]
        if len(active) > 1:
            raise ActiveConversationTask('Conversation has conflicting active Tasks')
        return {'grokbuddy_enabled': bool(active),
                'task_id': active[0]['id'] if active else None}

    def get_task(self, task_id):
        with self.db.transaction() as repo:
            return repo.get('tasks', task_id)

    def get_artifact(self, artifact_id):
        """Read artifact metadata only; content remains behind the ArtifactStore."""
        with self.db.transaction() as repo:
            return repo.get('artifacts', artifact_id)

    def get_review(self, request_id):
        with self.db.transaction() as repo:
            request = repo.get('review_requests', request_id)
            reviews = repo.find('reviews', review_request_id=request_id)
            review = reviews[0] if reviews else None
            return {'request': request, 'review': review,
                    'result': review.get('result_snapshot') if review else None}

    def list_pending_review_requests(self):
        """List non-terminal review requests without claiming or advancing them."""
        with self.db.transaction() as repo:
            requests = [
                request for request in repo.find('review_requests')
                if request['status'] in ACTIVE_REQUEST
            ]
        requests.sort(key=lambda request: (request['created_at'], request['id']))
        return [
            {
                'id': request['id'],
                'task_id': request['task_id'],
                'review_type': request['review_type'],
                'status': request['status'],
            }
            for request in requests
        ]

    def list_findings(self, task_id):
        with self.db.transaction() as repo:
            return repo.find('review_findings', task_id=task_id)

    def get_plan_review_readiness(self, actor_id, task_id):
        """A Builder-scoped, read-only preparation hint; request guards remain authoritative."""
        with self.db.transaction() as repo:
            actor = self.actor(repo, actor_id, Role.BUILDER)
            task = self.task_for(repo, task_id, actor, live=False)
            requests = repo.find('review_requests', task_id=task_id, review_type='PLAN_REVIEW')
            current_round = max((request['review_round'] for request in requests), default=0)
            limit = task['plan_limit']
            if task.get('decision_policy_version') == V1_DUAL_ROUND:
                limit = min(limit, V1_LIMIT)
            bound_material_ids = {ref['artifact_id'] for ref in task.get('current_plan_material_refs', [])}
            findings = []
            for finding in repo.find('review_findings', task_id=task_id):
                if finding.get('review_type') != 'PLAN_REVIEW':
                    continue
                next_action = None
                if not finding.get('advisory', False):
                    next_action = {
                        'OPEN': 'accept_or_reject_with_evidence',
                        'ACCEPTED': 'fix_with_evidence',
                        'FIXED': 'reviewer_verification',
                        'REJECTED_WITH_EVIDENCE': 'reviewer_verification',
                    }.get(finding['status'])
                fix_evidence_id = None
                if finding['status'] == 'FIXED' and not finding.get('advisory', False):
                    fixes = [event for event in repo.find('finding_events', task_id=task_id,
                                                          finding_id=finding['id'])
                             if event['new_status'] == 'FIXED' and event.get('evidence_artifact_id')]
                    if fixes:
                        fix_evidence_id = fixes[-1]['evidence_artifact_id']
                findings.append({
                    'finding_id': finding['id'], 'review_id': finding['review_id'],
                    'current_status': finding['status'], 'finding_version': finding['version'],
                    'severity': finding['severity'], 'advisory': finding.get('advisory', False),
                    'next_action': next_action, 'fix_evidence_artifact_id': fix_evidence_id,
                    'fix_evidence_bound': fix_evidence_id in bound_material_ids if fix_evidence_id else False,
                })
            unready = [finding['finding_id'] for finding in findings
                       if finding['current_status'] in ('OPEN', 'ACCEPTED') and not finding['advisory']]
            unbound = [finding['finding_id'] for finding in findings
                       if finding['current_status'] == 'FIXED' and not finding['advisory']
                       and not finding['fix_evidence_bound']]
            checks = {
                'planning': task['state'] == 'PLANNING',
                'no_active_review': not task['active_rr_id'],
                'task_live': task['state'] not in TERMINAL and self.clock.now() < task['deadline_at'],
                'automation_unfrozen': not task.get('automation_frozen', False),
                'plan_input_present': bool(task.get('current_plan_id')),
                'plan_scope_present': task.get('review_protocol_version') != 'v2' or bool(
                    task.get('current_plan_scope') and task.get('current_plan_scope_hash')),
                'round_available': current_round < limit,
            }
            can_request = all(checks.values())
            return {
                'task_id': task_id, 'task_state': task['state'],
                'expected_task_version': task['version'], 'active_rr_id': task['active_rr_id'],
                'current_plan_id': task.get('current_plan_id'),
                'decision_policy_version': task.get('decision_policy_version'),
                'gate_reason': task.get('gate_reason'), 'deadline_at': task['deadline_at'],
                'next_review_round': current_round + 1, 'round_limit': limit,
                'rounds_remaining': max(0, limit - current_round),
                'checks': checks, 'can_request_review': can_request,
                'ready_for_review': can_request and not unready and not unbound,
                'unready_findings': unready, 'unbound_fix_evidence': unbound, 'findings': findings,
            }

    def list_actionable_findings(self, task_id, review_request_id=None):
        """Return Hub-authoritative, non-closed findings for a Task or one Review APPLY."""
        with self.db.transaction() as repo:
            task = repo.get('tasks', task_id)
            findings = repo.find('review_findings', task_id=task['id'])
            if review_request_id is not None:
                request = repo.get('review_requests', review_request_id)
                if request['task_id'] != task_id:
                    raise PermissionDenied('Review request is outside task scope')
                reviews = repo.find('reviews', review_request_id=review_request_id)
                finding_ids = set(reviews[0].get('actionable_finding_ids', [])) if reviews else set()
                findings = [finding for finding in findings if finding['id'] in finding_ids]
            return [finding for finding in findings
                    if finding['status'] not in ('VERIFIED', 'WAIVED_BY_HUMAN')
                    and not finding.get('advisory', False)]

    def audit_log(self, task_id):
        with self.db.transaction() as repo:
            return repo.find('audit_logs', task_id=task_id)

    def move(self, actor_id, task_id, action, expected_version, key):
        # Only Builder lifecycle commands, never review/approval/terminal transitions.
        if action not in ('begin_plan', 'execute', 'self_test_failed'):
            raise HubError('Not a public Builder command')
        with self.command(actor_id, action, key, [task_id, expected_version], Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            task = self.task_for(repo, task_id, actor, expected_version)
            if action == 'execute':
                self.ensure_actions_closed(repo, task)
                if (task.get('review_protocol_version') == 'v2'
                        and task['state'] == 'FINAL_CHANGES_REQUIRED'):
                    raise HubError('Use begin_final_fix so scope and finding guards are enforced')
            self.change(repo, task, action, actor)
            if action == 'execute' and task.get('review_protocol_version') == 'v2':
                self._create_worker_assignment(repo, task, actor)
            box['response'] = task
            return task

    def submit_artifact(self, actor_id, task_id, kind, content, key, mime='text/plain'):
        allowed = {'PLAN', 'FINAL_PACKAGE', 'DIFF', 'TEST_RESULT', 'SOURCE_FILE', 'SQL', 'REPORT', 'EVIDENCE', 'LOG'}
        if kind not in allowed or not isinstance(content, bytes):
            raise HubError('Invalid submitted artifact')
        params = [task_id, kind, hashlib.sha256(content).hexdigest(), mime]
        with self.command(actor_id, 'submit_artifact', key, params, Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            if actor.get('worker_type') == 'workbuddy':
                task = repo.get('tasks', task_id)
                assignments = repo.find('worker_assignments', task_id=task_id)
                claimed = [item for item in assignments
                           if item['status'] == 'CLAIMED' and item.get('worker_principal_id') == actor_id]
                if claimed:
                    if task['state'] != 'EXECUTING' or task.get('automation_frozen'):
                        raise PermissionDenied('Worker assignment is not executable')
                else:
                    if not getattr(self, 'legacy_worker_test_mode', False):
                        raise PermissionDenied('Claim a v2 Worker assignment before uploading artifacts')
                    task = self.task_for(repo, task_id, actor)
                    if task.get('worker_status') != 'CLAIMED':
                        raise PermissionDenied('Claim task before uploading artifacts')
            else:
                task = self.task_for(repo, task_id, actor)
            result = self.add_artifact(repo, task_id, actor, kind, content, mime)
            box['response'] = result
            return result

    def submit_plan(self, actor_id, task_id, artifact_id, expected_version, key, approved_scope=None,
                    supporting_artifact_ids=None):
        params = [task_id, artifact_id, expected_version, approved_scope]
        if supporting_artifact_ids is not None:
            params.append(supporting_artifact_ids)
        with self.command(actor_id, 'submit_plan', key,
                          params, Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            task = self.task_for(repo, task_id, actor, expected_version)
            if task['state'] != 'PLANNING' or task['active_rr_id']:
                raise HubError('Plan can only change while planning')
            self.artifact(repo, task_id, artifact_id, kinds={'PLAN'})
            materials = []
            if supporting_artifact_ids is not None:
                if (not isinstance(supporting_artifact_ids, list)
                        or any(not isinstance(item, str) or not item for item in supporting_artifact_ids)
                        or len(set(supporting_artifact_ids)) != len(supporting_artifact_ids)):
                    raise HubError('Plan supporting Artifacts must be unique Artifact IDs')
                for identity in supporting_artifact_ids:
                    material, _ = self.artifact(repo, task_id, identity, kinds={'SOURCE_FILE', 'EVIDENCE'})
                    materials.append({'artifact_id': identity, 'sha256': material['sha256']})
            scope = None
            if task.get('review_protocol_version') == 'v2':
                scope = _validated_scope(approved_scope)
                human_scope = task.get('human_modification_scope')
                if human_scope is not None and not _scope_within(scope, human_scope)[0]:
                    raise HubError('Revised Plan exceeds the Human-specified modification scope')
                if task.get('pending_revision_kind') == 'PLAN_REVIEW':
                    task['revision_round'] = task.get('revision_round', 0) + 1
                    task['pending_revision_kind'] = None
            task.update(current_plan_id=artifact_id, current_final_id=None, approved_plan_id=None,
                         current_plan_material_refs=materials,
                         current_plan_scope=scope, current_plan_scope_hash=digest(scope) if scope else None,
                         human_modification_scope=None, human_modification_finding_ids=None,
                         content_revision=task['content_revision'] + 1)
            self.touch(repo, task)
            audit(repo, self.clock, actor, 'PLAN_SUBMITTED', task_id, artifact_id=artifact_id)
            box['response'] = task
            return task

    def self_test(self, actor_id, task_id, test_artifact_id, passed, expected_version, key):
        if type(passed) is not bool:
            raise HubError('Self-test requires a boolean result')
        with self.command(actor_id, 'self_test', key, [task_id, test_artifact_id, passed, expected_version], Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            task = self.task_for(repo, task_id, actor, expected_version)
            self.artifact(repo, task_id, test_artifact_id, kinds={'TEST_RESULT'})
            self.ensure_actions_closed(repo, task)
            if task.get('review_protocol_version') == 'v2':
                assignments = repo.find('worker_assignments', task_id=task_id)
                if not assignments:
                    raise HubError('Latest Worker assignment must complete before self-test')
                latest_assignment = max(assignments, key=lambda item: item['generation'])
                if latest_assignment['status'] != 'COMPLETED':
                    raise HubError('Latest Worker assignment must complete before self-test')
                for finding_id in latest_assignment.get('finding_ids', []):
                    finding = repo.get('review_findings', finding_id)
                    if finding['status'] != 'FIXED':
                        raise HubError('Worker fix findings require linked completion evidence')
            task.update(self_test_id=test_artifact_id, self_test_passed=passed, current_final_id=None,
                        content_revision=task['content_revision'] + 1)
            self.change(repo, task, 'self_test', actor)
            if not passed:
                self.change(repo, task, 'self_test_failed', actor)
            audit(repo, self.clock, actor, 'SELF_TEST', task_id, artifact_id=test_artifact_id, passed=passed)
            box['response'] = task
            return task

    def submit_final_package(self, actor_id, task_id, package, expected_version, key):
        with self.command(actor_id, 'submit_final_package', key, [task_id, package, expected_version], Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            self.contracts.validate('final-package', package)
            task = self.task_for(repo, task_id, actor, expected_version)
            if task['state'] != 'SELF_TESTING' or not task.get('self_test_passed'):
                raise HubError('Passing self-test required')
            if package['task_id'] != task_id or package['content_revision'] != task['content_revision']:
                raise HubError('Package revision mismatch')
            if package['self_test']['status'] != 'PASS':
                raise HubError('Package self-test did not pass')
            self._validate_final_materials(repo, task, package)
            if task['self_test_id'] not in {r['artifact_id'] for r in package['test_results']}:
                raise HubError('Package omits current self-test evidence')
            profile = repo.get('review_profiles', task['profile'] + '@' + task['profile_version'])
            if (package['review_profile'], package['review_profile_version'], package['profile_sha256']) != (task['profile'], task['profile_version'], profile['sha256']):
                raise HubError('Package profile mismatch')
            self.artifact(repo, task_id, package['profile_artifact_id'], profile['sha256'], {'SOURCE_FILE'})
            self.ensure_actions_closed(repo, task)
            if task.get('review_protocol_version') == 'v2':
                if task.get('pending_revision_kind') == 'FINAL_REVIEW':
                    task['revision_round'] = task.get('revision_round', 0) + 1
                    task['pending_revision_kind'] = None
            result = self.add_artifact(repo, task_id, actor, 'FINAL_PACKAGE', canonical(package))
            task['current_final_id'] = result['id']
            self.touch(repo, task)
            box['response'] = result
            return result

    def _validate_final_materials(self, repo, task, package):
        """Identical evidence checks for preflight and the authoritative submission."""
        task_id = task['id']
        if task.get('decision_policy_version') == V1_DUAL_ROUND:
            method, files = package.get('operation_method'), package.get('generated_files')
            if not isinstance(method, str) or not method.strip():
                raise HubError('V1 Final package requires operation method')
            if _RESTRICTED_TEXT.search(method):
                raise HubError('Operation method contains restricted content')
            if not isinstance(files, list) or not files:
                raise HubError('V1 Final package requires generated file Artifacts')
            paths = [item['path'] for item in files]
            if (any(not _display_file_path(path) for path in paths)
                    or len(set(paths)) != len(paths)
                    or not set(paths).issubset(set(package['changed_files']))):
                raise HubError('Generated file paths must be unique approved relative paths')
            for item in files:
                self.artifact(repo, task_id, item['artifact_id'], item['sha256'], {'SOURCE_FILE'})
        if (package['original_task']['artifact_id'] != task['original_task_id']
                or package['approved_plan']['artifact_id'] != task['approved_plan_id']):
            raise HubError('Package must reference original task and approved plan')
        for item in (package['original_task'], package['approved_plan']):
            self.artifact(repo, task_id, item['artifact_id'], item['sha256'])
        for item in package['test_results']:
            self.artifact(repo, task_id, item['artifact_id'], item['sha256'], {'TEST_RESULT'})
        if 'diff_artifact' in package:
            item = package['diff_artifact']
            self.artifact(repo, task_id, item['artifact_id'], item['sha256'], {'DIFF'})
        if task.get('review_protocol_version') == 'v2':
            approved_files = set((task.get('approved_scope') or {}).get('files', []))
            if not set(package['changed_files']).issubset(approved_files):
                raise HubError('Final package changed files exceed approved Plan scope')

    def preflight_final_review(self, actor_id, task_id, fields):
        """Check supplied material bytes before gateway commands create or change state."""
        with self.db.transaction() as repo:
            actor = self.actor(repo, actor_id, Role.BUILDER)
            task = self.task_for(repo, task_id, actor, live=False)
            try:
                def ref(identity):
                    item, _ = self.artifact(repo, task_id, identity)
                    return {'artifact_id': item['id'], 'sha256': item['sha256']}

                profile = repo.get('review_profiles', task['profile'] + '@' + task['profile_version'])
                package = {name: fields[name] for name in (
                    'change_scope', 'changed_files', 'known_risks', 'unverified_items')}
                package.update(protocol_version='v1', task_id=task_id,
                               content_revision=task['content_revision'] + 1,
                               original_task=ref(task['original_task_id']),
                               approved_plan=ref(task['approved_plan_id']),
                               diff_artifact=ref(fields['diff_artifact_id']),
                               test_results=[ref(fields['test_artifact_id'])],
                               self_test={'status': 'PASS', 'summary': fields['self_test_summary']},
                               review_profile=task['profile'], review_profile_version=task['profile_version'],
                               profile_sha256=profile['sha256'])
                if 'operation_method' in fields:
                    package['operation_method'] = fields['operation_method']
                if 'generated_files' in fields:
                    files = fields['generated_files']
                    if (not isinstance(files, list) or any(
                            not isinstance(item, dict) or set(item) != {'path', 'artifact_id'}
                            or any(not isinstance(v, str) or not v for v in item.values())
                            for item in files)):
                        raise HubError('generated_files must contain path and artifact_id')
                    package['generated_files'] = [{'path': item['path'], **ref(item['artifact_id'])}
                                                  for item in files]
                field_path = self.contracts.final_materials_error_path(package)
                if field_path is not None:
                    return {'ready': False, 'task_id': task_id, 'submitted': False,
                            'issues': [{'error_code': 'VALIDATION_FAILURE', 'field_path': field_path,
                                        'message': 'Final package material contract is invalid'}]}
                self._validate_final_materials(repo, task, package)
            except HubError as exc:
                return {'ready': False, 'task_id': task_id, 'submitted': False,
                        'issues': [{'error_code': exc.code, 'field_path': None, 'message': str(exc)}]}
            return {'ready': True, 'task_id': task_id, 'submitted': False, 'issues': [],
                    'provided_file_paths': [item['path'] for item in package.get('generated_files', [])],
                    'changed_files_without_source': sorted(set(package['changed_files']) - {
                        item['path'] for item in package.get('generated_files', [])}),
                    'checked': ['package_material_contract', 'task_scope', 'artifact_bytes', 'approved_files'],
                    'not_checked': ['worker_completion', 'self_test_transition', 'reviewer_delivery',
                                    'semantic_material_completeness', 'async_application']}

    def begin_final_fix(self, actor_id, task_id, finding_ids, proposed_scope, expected_version, key):
        params = [task_id, finding_ids, proposed_scope, expected_version]
        with self.command(actor_id, 'begin_final_fix', key, params, Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            task = self.task_for(repo, task_id, actor, expected_version)
            if task.get('review_protocol_version') != 'v2' or task['state'] != 'FINAL_CHANGES_REQUIRED':
                raise HubError('No v2 Final fix is awaiting execution')
            if not isinstance(finding_ids, list) or not finding_ids or len(set(finding_ids)) != len(finding_ids):
                raise HubError('A unique non-empty finding scope is required')
            allowed = set(task.get('final_fix_finding_ids') or [])
            if not set(finding_ids).issubset(allowed):
                raise HubError('Final fix references findings outside the frozen Review scope')
            within, normalized = _scope_within(proposed_scope, task.get('approved_scope'))
            if not within:
                task.update(scope_change_request=normalized, pending_revision_kind='PLAN_REVIEW',
                            approved_plan_id=None, approved_scope=None, approved_scope_hash=None,
                            current_final_id=None, self_test_passed=False)
                self.change(repo, task, 'scope_replan', actor)
                audit(repo, self.clock, actor, 'FINAL_FIX_SCOPE_EXCEEDED', task_id,
                      finding_ids=finding_ids, proposed_scope_hash=digest(normalized))
                box['response'] = {'status': 'PLAN_CHANGE_REQUIRED', 'task': task}
                return box['response']
            task['active_fix_finding_ids'] = list(finding_ids)
            task['active_fix_scope'] = normalized
            self.change(repo, task, 'execute', actor)
            assignment = self._create_worker_assignment(repo, task, actor)
            box['response'] = {'status': 'EXECUTING', 'task': task, 'assignment': assignment}
            return box['response']

    def profile_snapshot(self, actor_id, task_id, key):
        with self.command(actor_id, 'profile_snapshot', key, [task_id], Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            task = self.task_for(repo, task_id, actor)
            profile = repo.get('review_profiles', task['profile'] + '@' + task['profile_version'])
            result = self.add_artifact(repo, task_id, actor, 'SOURCE_FILE', canonical(profile['rules']))
            box['response'] = result
            return result
