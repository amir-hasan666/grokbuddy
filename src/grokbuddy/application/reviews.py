from grokbuddy.domain.model import HubError, PermissionDenied, Role, ReviewType
from .common import Services, uid, canonical, audit, iso, digest


class ReviewService(Services):
    def request_review(self, actor_id, task_id, review_type, reviewer_id, expected_version, key,
                       protocol_version=None):
        params = [task_id, review_type, reviewer_id, expected_version, protocol_version]
        with self.command(actor_id, 'request_review', key, params, Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            try:
                kind = ReviewType(review_type)
            except ValueError as exc:
                raise HubError('Unknown review type') from exc
            task = self.task_for(repo, task_id, actor, expected_version)
            protocol_version = protocol_version or task.get('review_protocol_version', 'v1')
            if protocol_version not in ('v1', 'v2'):
                raise HubError('Unsupported Review protocol version')
            if task.get('review_protocol_version') == 'v2' and protocol_version != 'v2':
                raise HubError('Phase 6 Task review protocol cannot be downgraded')
            reviewer = self.actor(repo, reviewer_id, Role.REVIEWER)
            if actor['provider_id'] == reviewer['provider_id']:
                raise PermissionDenied('Builder and Reviewer must have independent identities')
            plan = kind == ReviewType.PLAN
            expected_state = 'PLANNING' if plan else 'SELF_TESTING'
            if task['state'] != expected_state or task['active_rr_id']:
                raise HubError('Task cannot request this review')
            artifact_id = task['current_plan_id'] if plan else task['current_final_id']
            if not artifact_id:
                raise HubError('Frozen review input is required')
            artifact, _ = self.artifact(repo, task_id, artifact_id, kinds={'PLAN' if plan else 'FINAL_PACKAGE'})
            if protocol_version == 'v2':
                if plan and (not task.get('current_plan_scope') or not task.get('current_plan_scope_hash')):
                    raise HubError('v2 Plan review requires a frozen structured scope')
                if not plan and (not task.get('approved_scope') or not task.get('approved_scope_hash')):
                    raise HubError('v2 Final review requires an approved Plan scope')
            if not plan:
                if not task.get('self_test_passed'):
                    raise HubError('Passing self-test required')
                self.ensure_actions_closed(repo, task)
            previous = repo.find('review_requests', task_id=task_id, review_type=kind.value)
            round_number = max((r['review_round'] for r in previous), default=0) + 1
            limit = task['plan_limit'] if plan else task['final_limit']
            if round_number > limit:
                self.escalate(repo, task, 'ROUND_LIMIT')
                box['response'] = {'review_request_id': None, 'status': 'ESCALATED'}
                return box['response']
            profile = repo.get('review_profiles', task['profile'] + '@' + task['profile_version'])
            profile_artifact = self.add_artifact(repo, task_id, actor, 'SOURCE_FILE', canonical(profile['rules']))
            findings = repo.find('review_findings', task_id=task_id)
            context = self.add_artifact(repo, task_id, actor, 'SOURCE_FILE', canonical({'findings': findings}))
            request_id, review_id = uid('RR'), uid('REV')
            timeout = self.settings.plan_review_timeout if plan else self.settings.final_review_timeout
            deadline = min(task['deadline_at'], self.clock.now() + timeout * 1_000_000)
            envelope = dict(protocol_version=protocol_version, task_id=task_id, review_request_id=request_id,
                            review_id=review_id, review_type=kind.value, review_round=round_number,
                            content_revision=task['content_revision'], review_profile=task['profile'],
                            review_profile_version=task['profile_version'], profile_sha256=profile['sha256'],
                            input_sha256=artifact['sha256'], profile_artifact_id=profile_artifact['id'],
                            input_artifact_id=artifact_id, expected_reviewer_actor_id=reviewer_id,
                            deadline_at=iso(deadline))
            if protocol_version == 'v2':
                # request_plan/request_final is the only Task mutation below.
                envelope['expected_task_version'] = task['version'] + 1
            self.contracts.validate('request', envelope)
            request = dict(id=request_id, task_id=task_id, review_id=review_id, review_type=kind.value,
                           review_round=round_number, status='PENDING', input_artifact_id=artifact_id,
                           created_at=self.clock.now(), deadline_at=deadline, envelope=envelope,
                           context_artifact_id=context['id'], round_limit=limit,
                           protocol_version=protocol_version,
                           expected_task_version=envelope.get('expected_task_version'))
            repo.add('review_requests', request)
            repo.add('review_rounds', dict(id=request_id, task_id=task_id, review_type=kind.value,
                     round_number=round_number, evaluation_status='PENDING'))
            task['active_rr_id'] = request_id
            self.change(repo, task, 'request_plan' if plan else 'request_final', actor, request_id)
            repo.add('outbox_events', dict(id=uid('OUT'), task_id=task_id, review_request_id=request_id,
                     status='READY', attempts=0, next_attempt_at=self.clock.now(), lease_until=0,
                     lease_token=None, lease_generation=0, delivery_key=request_id,
                     request_hash=digest(envelope), input_hash=artifact['sha256'],
                     profile_hash=profile['sha256'], frozen_task_version=task['version'],
                     created_at=self.clock.now()))
            audit(repo, self.clock, actor, 'REVIEW_REQUEST_CREATED', task_id, request_id=request_id,
                  review_round=round_number, input_sha256=artifact['sha256'])
            box['response'] = {'review_request_id': request_id, 'status': 'PENDING'}
            return box['response']
