from grokbuddy.domain.model import HubError, Role, TERMINAL, CLOSED_FINDING
from grokbuddy.domain.rules import finding_transition
from .common import Services, uid, digest, canonical, audit
from .tasks import _scope_within, _validated_scope


HUMAN_GATE_STATES = {'PLAN_HUMAN_REVIEW', 'FINAL_HUMAN_REVIEW'}


class GovernanceService(Services):
    def _decision(self, repo, task, actor, kind, reason, **scope):
        if not isinstance(reason, str) or not reason.strip():
            raise HubError('Human decision requires a reason')
        reason_artifact = self.add_artifact(repo, task['id'], actor, 'EVIDENCE', reason.encode('utf-8'), 'text/plain')
        decision = dict(id=uid('APR'), task_id=task['id'], kind=kind, status='CONSUMED',
                        approver_id=actor['id'], scope=scope, reason_artifact_id=reason_artifact['id'],
                        decision_at=self.clock.now(), consumed_at=self.clock.now())
        repo.add('human_approvals', decision)
        repo.add('approval_events', dict(id=uid('EVT'), approval_id=decision['id'], action=kind,
                 actor_id=actor['id'], at=self.clock.now()))
        audit(repo, self.clock, actor, kind, task['id'], approval_id=decision['id'], reason_artifact_id=reason_artifact['id'])
        return decision

    def _action_binding(self, repo, task, action):
        required = {'operation', 'environment', 'targets', 'parameters', 'artifact_id',
                    'precheck_artifact_id', 'backup_artifact_id', 'rollback_artifact_id', 'verification_artifact_id'}
        if not isinstance(action, dict) or set(action) != required:
            raise HubError('Action scope requires exact operation, environment, targets and evidence')
        if not all(isinstance(action[k], str) and action[k].strip() for k in ('operation', 'environment')):
            raise HubError('Action operation/environment is required')
        if not isinstance(action['targets'], list) or not action['targets'] or not all(isinstance(x, str) and x for x in action['targets']):
            raise HubError('Action targets are required')
        if not isinstance(action['parameters'], dict):
            raise HubError('Action parameters must be an object')
        hashes = {}
        for field in required:
            if field.endswith('_artifact_id') or field == 'artifact_id':
                artifact, _ = self.artifact(repo, task['id'], action[field])
                hashes[field] = artifact['sha256']
        return dict(task_id=task['id'], content_revision=task['content_revision'], action=action, hashes=hashes)

    @staticmethod
    def _human_ids(value, name, *, allow_empty=True):
        if (not isinstance(value, list) or (not allow_empty and not value)
                or not all(isinstance(item, str) and item for item in value)
                or len(set(value)) != len(value)):
            raise HubError(f'{name} must be a unique list of identifiers')
        return sorted(value)

    @staticmethod
    def _gate_review_type(task):
        if task['state'] not in HUMAN_GATE_STATES:
            raise HubError('Task is not awaiting a Human Gate decision')
        if task['state'] == 'PLAN_HUMAN_REVIEW':
            return 'PLAN_REVIEW'
        return 'FINAL_REVIEW'

    def _latest_gate_request(self, repo, task, review_type):
        requests = repo.find('review_requests', task_id=task['id'], review_type=review_type)
        if not requests:
            raise HubError('Human Gate has no related Review Request')
        return max(requests, key=lambda request: request['review_round'])

    def _unresolved_finding_ids(self, repo, task):
        return sorted(finding['id'] for finding in repo.find('review_findings', task_id=task['id'])
                      if finding['status'] not in CLOSED_FINDING)

    def _set_human_deadline(self, task, new_deadline_at, *, required=False):
        if new_deadline_at is None:
            if required or self.clock.now() >= task['deadline_at']:
                raise HubError('A future Human-authorized task deadline is required')
            return task['deadline_at']
        if type(new_deadline_at) is not int or new_deadline_at <= self.clock.now():
            raise HubError('Human-authorized task deadline must be a future integer timestamp')
        task['deadline_at'] = new_deadline_at
        return new_deadline_at

    def _grant_review_budget(self, repo, task, actor, review_type, extra_review_budget,
                             reason, related_request_id):
        if type(extra_review_budget) is not int or extra_review_budget < 1:
            raise HubError('Extra review budget must be a positive integer')
        plan = review_type == 'PLAN_REVIEW'
        default_limit = (self.settings.max_plan_review_rounds if plan
                         else self.settings.max_final_review_rounds)
        hard_extra_limit = (self.settings.max_human_plan_extra_rounds if plan
                            else self.settings.max_human_final_extra_rounds)
        limit_field = 'plan_limit' if plan else 'final_limit'
        extra_field = 'plan_extra_budget' if plan else 'final_extra_budget'
        current_limit = task.get(limit_field, default_limit)
        current_extra = max(task.get(extra_field, current_limit - default_limit),
                            current_limit - default_limit)
        new_extra = current_extra + extra_review_budget
        if new_extra > hard_extra_limit:
            raise HubError('Extra review budget exceeds the configured Human hard limit')
        new_limit = current_limit + extra_review_budget
        task[limit_field] = new_limit
        task[extra_field] = new_extra
        return self._decision(
            repo, task, actor, 'HUMAN_REVIEW_BUDGET', reason,
            review_type=review_type, related_review_request_id=related_request_id,
            granted_budget=extra_review_budget, total_extra_budget=new_extra,
            default_limit=default_limit, new_round_limit=new_limit,
            hard_extra_limit=hard_extra_limit)

    def _ensure_next_review_budget(self, repo, task, actor, review_type,
                                   extra_review_budget, reason, related_request_id):
        rounds = repo.find('review_requests', task_id=task['id'], review_type=review_type)
        current_round = max((request['review_round'] for request in rounds), default=0)
        limit_field = 'plan_limit' if review_type == 'PLAN_REVIEW' else 'final_limit'
        approval = None
        if extra_review_budget:
            approval = self._grant_review_budget(
                repo, task, actor, review_type, extra_review_budget, reason,
                related_request_id)
        if current_round >= task[limit_field]:
            raise HubError('A separate explicit Human review budget is required')
        return approval

    def _stop_task_automation(self, repo, task, reason, *, cancel_assignments=False):
        self.stop_request(repo, task, 'ESCALATED', reason)
        request_ids = {request['id'] for request in repo.find('review_requests', task_id=task['id'])}
        for request_id in request_ids:
            for event in repo.find('outbox_events', review_request_id=request_id):
                if event['status'] not in ('SENT', 'CANCELLED'):
                    event.update(status='CANCELLED', lease_token=None, cancelled_at=self.clock.now(),
                                 cancellation_reason=reason)
                    repo.save('outbox_events', event)
            for job in repo.find('mock_jobs', id=request_id):
                if job['status'] not in ('DONE', 'CANCELLED'):
                    job.update(status='CANCELLED', lease_token=None,
                               cancelled_at=self.clock.now(), cancellation_reason=reason)
                    repo.save('mock_jobs', job)
        if cancel_assignments:
            for assignment in repo.find('worker_assignments', task_id=task['id']):
                if assignment['status'] in ('OFFERED', 'CLAIMED'):
                    assignment.update(status='CANCELLED', version=assignment.get('version', 0) + 1,
                                      lease_token=None, lease_until=0,
                                      cancelled_at=self.clock.now(), cancellation_reason=reason)
                    repo.save('worker_assignments', assignment)

    def _abort_task(self, repo, task, actor, reason, decision_kind):
        decision = self._decision(repo, task, actor, decision_kind, reason,
                                  from_state=task['state'], conversation_id=task.get('conversation_id'))
        self._stop_task_automation(repo, task, 'TASK_CANCELLED', cancel_assignments=True)
        task.update(automation_frozen=True, gate_reason='TASK_CANCELLED',
                    grokbuddy_enabled=False, context_invalidated_at=self.clock.now(),
                    context_invalidated_by=actor['id'], context_invalidation_reason='ABORT')
        self.change(repo, task, 'cancel', actor)
        return {'task': task, 'decision': 'ABORT', 'approval_id': decision['id']}

    def human_gate_decide(self, actor_id, task_id, decision, reason, expected_version, key,
                          acknowledged_findings=None, modification_scope=None, finding_ids=None,
                          extra_review_budget=0, new_deadline_at=None):
        """Apply one authenticated, CAS-bound Human decision to a v2 Review Gate."""
        params = [task_id, decision, reason, expected_version, acknowledged_findings,
                  modification_scope, finding_ids, extra_review_budget, new_deadline_at]
        with self.command(actor_id, 'human_gate_decide', key, params, Role.HUMAN) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            task = self.task_for(repo, task_id, actor, expected_version, live=False)
            if not isinstance(decision, str) or decision not in {'ACCEPT', 'MODIFY', 'CONTINUE', 'ABORT'}:
                raise HubError('Unknown Human Gate decision')
            review_type = self._gate_review_type(task)
            plan = review_type == 'PLAN_REVIEW'
            related = self._latest_gate_request(repo, task, review_type)
            unresolved = self._unresolved_finding_ids(repo, task)

            if decision == 'ABORT':
                if any(value not in (None, [], 0) for value in
                       (acknowledged_findings, modification_scope, finding_ids,
                        extra_review_budget, new_deadline_at)):
                    raise HubError('Abort does not accept review continuation fields')
                response = self._abort_task(repo, task, actor, reason, 'HUMAN_GATE_ABORT')
                box['response'] = response
                return response

            self.ensure_actions_closed(repo, task)
            if decision == 'ACCEPT':
                if any(value not in (None, [], 0) for value in
                       (modification_scope, finding_ids, extra_review_budget)):
                    raise HubError('Accept does not accept modification or budget fields')
                acknowledged = self._human_ids(
                    acknowledged_findings, 'acknowledged_findings')
                if acknowledged != unresolved:
                    raise HubError('Accept must acknowledge every unresolved finding')
                if not plan and new_deadline_at is not None:
                    raise HubError('Final Accept does not extend a terminal Task deadline')
                if plan:
                    self._set_human_deadline(task, new_deadline_at)
                input_id = task.get('current_plan_id' if plan else 'current_final_id')
                if not input_id or related['input_artifact_id'] != input_id:
                    raise HubError('Accept must bind the latest frozen Review input')
                artifact, _ = self.artifact(
                    repo, task_id, input_id, kinds={'PLAN' if plan else 'FINAL_PACKAGE'})
                reviews = repo.find('reviews', review_request_id=related['id'])
                if not reviews:
                    raise HubError('Accept requires an immutable completed Review')
                if not plan:
                    if not task.get('self_test_passed') or not task.get('self_test_id'):
                        raise HubError('Final Accept requires a qualified Final Package and self-test')
                    self.artifact(repo, task_id, task['self_test_id'], kinds={'TEST_RESULT'})
                self._stop_task_automation(repo, task, 'HUMAN_GATE_ACCEPT')
                kind = 'PLAN_OVERRIDE' if plan else 'FINAL_OVERRIDE'
                snapshot = reviews[0].get('result_snapshot') or {}
                approval = self._decision(
                    repo, task, actor, kind, reason, review_type=review_type,
                    related_review_request_id=related['id'], related_review_id=related['review_id'],
                    input_artifact_id=input_id, input_sha256=artifact['sha256'],
                    acknowledged_findings=acknowledged,
                    acknowledged_risks=snapshot.get('risks', []),
                    content_revision=task['content_revision'])
                task.update(automation_frozen=False, gate_reason=None,
                            last_human_gate_decision=decision,
                            last_human_gate_decision_id=approval['id'])
                if plan:
                    task.update(approved_plan_id=input_id,
                                approved_scope=task.get('current_plan_scope'),
                                approved_scope_hash=task.get('current_plan_scope_hash'),
                                pending_revision_kind=None)
                    action = 'human_accept_plan'
                else:
                    task.update(completion_basis='HUMAN_OVERRIDE',
                                completion_actor_id=actor['id'],
                                completion_at=self.clock.now(),
                                completion_reason_artifact_id=approval['reason_artifact_id'],
                                completion_related_rr_id=related['id'],
                                grokbuddy_enabled=False,
                                context_invalidated_at=self.clock.now(),
                                context_invalidated_by=actor['id'],
                                context_invalidation_reason='DONE')
                    action = 'human_accept_final'
                self.change(repo, task, action, actor, related['id'])
                response = {'task': task, 'decision': decision, 'approval_id': approval['id']}
                box['response'] = response
                return response

            if acknowledged_findings not in (None, []):
                raise HubError('Only Accept uses acknowledged_findings')

            if decision == 'MODIFY':
                normalized_scope = _validated_scope(modification_scope)
                selected = self._human_ids(finding_ids, 'finding_ids', allow_empty=not unresolved)
                if not set(selected).issubset(unresolved):
                    raise HubError('Modify references findings outside the current actionable scope')
                target_review_type = review_type
                within = True
                if not plan:
                    within, normalized_scope = _scope_within(
                        normalized_scope, task.get('approved_scope'))
                    if not within:
                        target_review_type = 'PLAN_REVIEW'
                budget_approval = self._ensure_next_review_budget(
                    repo, task, actor, target_review_type, extra_review_budget,
                    reason, related['id'])
                self._set_human_deadline(task, new_deadline_at)
                self._stop_task_automation(repo, task, 'HUMAN_GATE_MODIFY')
                approval = self._decision(
                    repo, task, actor, 'HUMAN_GATE_MODIFY', reason,
                    review_type=review_type, next_review_type=target_review_type,
                    related_review_request_id=related['id'], modification_scope=normalized_scope,
                    finding_ids=selected, scope_within_approved_plan=within,
                    budget_approval_id=budget_approval['id'] if budget_approval else None)
                task.update(automation_frozen=False, gate_reason=None,
                            last_human_gate_decision=decision,
                            last_human_gate_decision_id=approval['id'])
                assignment = None
                if plan:
                    task.update(human_modification_scope=normalized_scope,
                                human_modification_finding_ids=selected,
                                pending_revision_kind='PLAN_REVIEW')
                    action = 'human_modify_plan'
                elif within:
                    task.update(active_fix_finding_ids=selected,
                                active_fix_scope=normalized_scope,
                                final_fix_finding_ids=unresolved)
                    action = 'human_modify_final'
                else:
                    task.update(scope_change_request=normalized_scope,
                                human_modification_scope=normalized_scope,
                                human_modification_finding_ids=selected,
                                pending_revision_kind='PLAN_REVIEW', approved_plan_id=None,
                                approved_scope=None, approved_scope_hash=None,
                                current_final_id=None, self_test_passed=False)
                    action = 'human_modify_final_replan'
                self.change(repo, task, action, actor, related['id'])
                if action == 'human_modify_final':
                    assignment = self._create_worker_assignment(repo, task, actor)
                response = {'task': task, 'decision': decision, 'approval_id': approval['id'],
                            'budget_approval_id': budget_approval['id'] if budget_approval else None,
                            'assignment': assignment}
                box['response'] = response
                return response

            if any(value is not None for value in (modification_scope, finding_ids)):
                raise HubError('Continue does not accept modification fields')
            budget_approval = self._grant_review_budget(
                repo, task, actor, review_type, extra_review_budget, reason, related['id'])
            deadline = self._set_human_deadline(task, new_deadline_at, required=True)
            self._stop_task_automation(repo, task, 'HUMAN_GATE_CONTINUE')
            reuse_frozen_input = bool(
                (task.get('current_plan_id') if plan else task.get('current_final_id'))
                and related['input_artifact_id'] ==
                (task.get('current_plan_id') if plan else task.get('current_final_id'))
                and (plan or (task.get('self_test_passed') and task.get('self_test_id'))))
            if plan and not reuse_frozen_input:
                raise HubError('Plan Continue requires the same frozen Plan input')
            approval = self._decision(
                repo, task, actor, 'HUMAN_GATE_CONTINUE', reason,
                review_type=review_type, related_review_request_id=related['id'],
                budget_approval_id=budget_approval['id'],
                extra_review_budget=extra_review_budget,
                new_round_limit=task['plan_limit' if plan else 'final_limit'],
                new_deadline_at=deadline, reuse_frozen_input=reuse_frozen_input)
            task.update(automation_frozen=False, gate_reason=None,
                        last_human_gate_decision=decision,
                        last_human_gate_decision_id=approval['id'],
                        pending_revision_kind=None)
            assignment = None
            if plan:
                action = 'human_continue_plan'
            elif reuse_frozen_input:
                action = 'human_continue_final'
            else:
                task.update(active_fix_finding_ids=unresolved,
                            active_fix_scope=task.get('approved_scope'))
                action = 'human_continue_final_rework'
            self.change(repo, task, action, actor, related['id'])
            if action == 'human_continue_final_rework':
                assignment = self._create_worker_assignment(repo, task, actor)
            response = {'task': task, 'decision': decision, 'approval_id': approval['id'],
                        'budget_approval_id': budget_approval['id'], 'assignment': assignment}
            box['response'] = response
            return response

    def request_action(self, actor_id, task_id, action, ttl_seconds, expected_version, key):
        with self.command(actor_id, 'request_action', key, [task_id, action, ttl_seconds, expected_version], Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            task = self.task_for(repo, task_id, actor, expected_version)
            if type(ttl_seconds) is not int or ttl_seconds <= 0:
                raise HubError('Approval TTL must be positive')
            if repo.find('human_approvals', task_id=task_id, kind='HIGH_RISK_ACTION', status='APPROVED'):
                raise HubError('Consume or resolve existing action authorization first')
            binding = self._action_binding(repo, task, action)
            approval = dict(id=uid('APR'), task_id=task_id, kind='HIGH_RISK_ACTION', status='PENDING',
                            binding=binding, action_digest=digest(binding), requested_by=actor_id,
                            expires_at=min(task['deadline_at'], self.clock.now() + ttl_seconds * 1_000_000),
                            approver_id=None, created_at=self.clock.now())
            repo.add('human_approvals', approval)
            self.change(repo, task, 'request_approval', actor)
            repo.add('approval_events', dict(id=uid('EVT'), approval_id=approval['id'], action='REQUESTED', actor_id=actor_id, at=self.clock.now()))
            audit(repo, self.clock, actor, 'APPROVAL_REQUESTED', task_id, approval_id=approval['id'], action_digest=approval['action_digest'])
            box['response'] = approval
            return approval

    def decide_action(self, actor_id, approval_id, approve, reason, expected_version, key, reject_to='cancel'):
        params = [approval_id, approve, reason, expected_version, reject_to]
        with self.command(actor_id, 'decide_action', key, params, Role.HUMAN) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            approval = repo.get('human_approvals', approval_id)
            task = self.task_for(repo, approval['task_id'], actor, expected_version)
            if type(approve) is not bool or not reason.strip() or reject_to not in ('cancel', 'replan'):
                raise HubError('Invalid approval decision')
            if approval['kind'] != 'HIGH_RISK_ACTION' or approval['status'] != 'PENDING':
                raise HubError('Approval is not pending')
            if self.clock.now() >= approval['expires_at']:
                raise HubError('Approval expired')
            current = self._action_binding(repo, task, approval['binding']['action'])
            if digest(current) != approval['action_digest']:
                raise HubError('Action changed since approval request')
            evidence = self.add_artifact(repo, task['id'], actor, 'EVIDENCE', reason.encode('utf-8'), 'text/plain')
            approval.update(status='APPROVED' if approve else 'REJECTED', approver_id=actor_id,
                            reason_artifact_id=evidence['id'], decision_at=self.clock.now(),
                            withdrawn=not approve and reject_to == 'replan')
            repo.save('human_approvals', approval)
            self.change(repo, task, 'approve_action' if approve else ('cancel' if reject_to == 'cancel' else 'reject_replan'), actor)
            repo.add('approval_events', dict(id=uid('EVT'), approval_id=approval_id, action=approval['status'], actor_id=actor_id, at=self.clock.now()))
            audit(repo, self.clock, actor, 'HUMAN_' + approval['status'], task['id'], approval_id=approval_id)
            box['response'] = approval
            return approval

    def consume_action(self, actor_id, approval_id, action, expected_version, key):
        with self.command(actor_id, 'consume_action', key, [approval_id, action, expected_version], Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            approval = repo.get('human_approvals', approval_id)
            task = self.task_for(repo, approval['task_id'], actor, expected_version)
            if task['state'] != 'EXECUTING' or approval['status'] != 'APPROVED' or self.clock.now() >= approval['expires_at']:
                raise HubError('No valid action authorization')
            if digest(self._action_binding(repo, task, action)) != approval['action_digest']:
                raise HubError('Action scope or revision changed')
            approval.update(status='CONSUMED', consumed_at=self.clock.now())
            repo.save('human_approvals', approval)
            self.touch(repo, task)
            repo.add('approval_events', dict(id=uid('EVT'), approval_id=approval_id, action='CONSUMED', actor_id=actor_id, at=self.clock.now()))
            audit(repo, self.clock, actor, 'ACTION_AUTHORIZATION_CONSUMED', task['id'], approval_id=approval_id)
            box['response'] = {'approval_id': approval_id, 'status': 'CONSUMED', 'execution_performed': False}
            return box['response']

    def withdraw_action(self, actor_id, approval_id, reason, expected_version, key):
        """Human abandons an unexecuted expired/rejected action; this grants no execution permission."""
        with self.command(actor_id, 'withdraw_action', key, [approval_id, reason, expected_version], Role.HUMAN) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            approval = repo.get('human_approvals', approval_id)
            task = self.task_for(repo, approval['task_id'], actor, expected_version, live=False)
            if approval['kind'] == 'HIGH_RISK_ACTION' and approval['status'] in ('PENDING', 'APPROVED') and self.clock.now() >= approval['expires_at']:
                approval['status'] = 'EXPIRED'
                repo.save('human_approvals', approval)
                repo.add('approval_events', dict(id=uid('EVT'), approval_id=approval_id, action='EXPIRED', actor_id=actor_id, at=self.clock.now()))
                audit(repo, self.clock, actor, 'APPROVAL_EXPIRED', task['id'], approval_id=approval_id)
            if task['state'] in TERMINAL or approval['kind'] != 'HIGH_RISK_ACTION' or approval['status'] not in ('EXPIRED', 'REJECTED'):
                raise HubError('Only unexecuted expired/rejected actions can be withdrawn')
            decision = self._decision(repo, task, actor, 'ACTION_WITHDRAWN', reason, approval_id=approval_id)
            approval.update(status='REJECTED', withdrawn=True, withdrawal_decision_id=decision['id'])
            repo.save('human_approvals', approval)
            repo.add('approval_events', dict(id=uid('EVT'), approval_id=approval_id, action='WITHDRAWN', actor_id=actor_id, at=self.clock.now()))
            self.touch(repo, task)
            box['response'] = approval
            return approval

    def waive_finding(self, actor_id, finding_id, reason, expected_version, key):
        with self.command(actor_id, 'waive_finding', key, [finding_id, reason, expected_version], Role.HUMAN) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            finding = repo.get('review_findings', finding_id)
            task = self.task_for(repo, finding['task_id'], actor, expected_version, live=False)
            if task['state'] in TERMINAL or task['active_rr_id']:
                raise HubError('Waiver requires a nonterminal task without active review')
            old = finding['status']
            new = finding_transition(old, 'waive', Role.HUMAN)
            decision = self._decision(repo, task, actor, 'FINDING_WAIVER', reason, finding_id=finding_id,
                                      content_revision=task['content_revision'])
            finding.update(status=new, version=finding['version'] + 1, updated_at=self.clock.now())
            repo.save('review_findings', finding)
            repo.add('finding_events', dict(id=uid('EVT'), finding_id=finding_id, task_id=task['id'],
                     old_status=old, new_status=new, approval_id=decision['id'], actor_id=actor_id, at=self.clock.now()))
            self.touch(repo, task)
            box['response'] = finding
            return finding

    def resume(self, actor_id, task_id, review_type, new_limit, new_deadline, reason, expected_version, key):
        params = [task_id, review_type, new_limit, new_deadline, reason, expected_version]
        with self.command(actor_id, 'resume', key, params, Role.HUMAN) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            task = self.task_for(repo, task_id, actor, expected_version, live=False)
            if review_type not in ('PLAN_REVIEW', 'FINAL_REVIEW') or type(new_limit) is not int or new_limit < 1 or new_deadline <= self.clock.now():
                raise HubError('Explicit future deadline and review budget required')
            previous = repo.find('review_requests', task_id=task_id, review_type=review_type)
            if new_limit <= max((r['review_round'] for r in previous), default=0):
                raise HubError('Resume budget must permit a new evaluation')
            # Approval failures cannot be solved by a review resume.
            self.ensure_actions_closed(repo, task)
            if review_type == 'FINAL_REVIEW' and not task.get('approved_plan_id'):
                raise HubError('Final remediation requires an approved plan')
            decision = self._decision(repo, task, actor, 'RESUME', reason, review_type=review_type,
                                      new_limit=new_limit, new_deadline=new_deadline)
            self.stop_request(repo, task, 'ESCALATED', 'HUMAN_RESUME')
            task.update(deadline_at=new_deadline, escalation_reason=None)
            task['plan_limit' if review_type == 'PLAN_REVIEW' else 'final_limit'] = new_limit
            self.change(repo, task, 'resume_plan' if review_type == 'PLAN_REVIEW' else 'resume_final', actor)
            box['response'] = task
            return task

    def override_review(self, actor_id, task_id, review_type, input_artifact_id, acknowledged_findings,
                        reason, expires_at, expected_version, key, new_deadline=None):
        params = [task_id, review_type, input_artifact_id, acknowledged_findings, reason, expires_at, expected_version, new_deadline]
        with self.command(actor_id, 'override_review', key, params, Role.HUMAN) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            task = self.task_for(repo, task_id, actor, expected_version, live=False)
            if review_type not in ('PLAN_REVIEW', 'FINAL_REVIEW') or expires_at <= self.clock.now():
                raise HubError('Invalid override scope or expiry')
            if self.clock.now() >= task['deadline_at']:
                if new_deadline is None or new_deadline <= self.clock.now():
                    raise HubError('Expired task requires explicit new deadline')
                task['deadline_at'] = new_deadline
            self.ensure_actions_closed(repo, task)
            plan = review_type == 'PLAN_REVIEW'
            expected_input = task['current_plan_id'] if plan else task['current_final_id']
            if not expected_input or input_artifact_id != expected_input:
                raise HubError('Override must bind current frozen input')
            artifact, _ = self.artifact(repo, task_id, input_artifact_id)
            if not plan and not task.get('self_test_passed'):
                raise HubError('Override does not bypass self-test evidence')
            unresolved = {f['id'] for f in repo.find('review_findings', task_id=task_id) if f['status'] not in CLOSED_FINDING}
            if set(acknowledged_findings) != unresolved:
                raise HubError('Override must acknowledge every unresolved finding')
            decision = self._decision(repo, task, actor, 'REVIEW_OVERRIDE', reason, review_type=review_type,
                                      artifact_id=input_artifact_id, sha256=artifact['sha256'],
                                      findings=sorted(unresolved), expires_at=expires_at, content_revision=task['content_revision'])
            self.stop_request(repo, task, 'ESCALATED', 'HUMAN_OVERRIDE')
            if plan:
                task['approved_plan_id'] = input_artifact_id
            self.change(repo, task, 'override_plan' if plan else 'override_final', actor)
            box['response'] = {'task': task, 'approval_id': decision['id']}
            return box['response']

    def cancel(self, actor_id, task_id, reason, expected_version, key):
        with self.command(actor_id, 'cancel', key, [task_id, reason, expected_version], Role.HUMAN) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            task = self.task_for(repo, task_id, actor, expected_version, live=False)
            response = self._abort_task(repo, task, actor, reason, 'CANCEL')
            box['response'] = response['task']
            return response['task']
