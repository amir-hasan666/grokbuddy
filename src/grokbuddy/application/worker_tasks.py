"""Local Worker handoff without changing the review state machine."""

from grokbuddy.domain.model import Conflict, HubError, PermissionDenied, Role
from .common import Services, audit, digest, uid


class WorkerTaskService(Services):
    def _assignment(self, repo, task_id, statuses=('OFFERED', 'CLAIMED')):
        matches = [item for item in repo.find('worker_assignments', task_id=task_id)
                   if item['status'] in statuses]
        if len(matches) > 1:
            raise Conflict('Task has conflicting live Worker assignments')
        return matches[0] if matches else None

    def _create_worker_assignment(self, repo, task, actor):
        if task['state'] != 'EXECUTING' or task.get('automation_frozen'):
            raise Conflict('Worker assignment requires an unfrozen EXECUTING Task')
        if self._assignment(repo, task['id']):
            raise Conflict('Task already has a live Worker assignment')
        plan_id = task.get('approved_plan_id')
        scope = task.get('approved_scope')
        if not plan_id or not isinstance(scope, dict) or not scope:
            raise HubError('Approved Plan and scope are required for Worker assignment')
        plan, _ = self.artifact(repo, task['id'], plan_id, kinds={'PLAN'})
        generations = repo.find('worker_assignments', task_id=task['id'])
        generation = max((item['generation'] for item in generations), default=0) + 1
        assignment = dict(
            id=uid('WA'), task_id=task['id'], generation=generation, status='OFFERED', version=0,
            worker_principal_id=None, lease_token=None, lease_until=0, lease_generation=0, attempts=0,
            approved_plan_artifact_id=plan_id, approved_plan_hash=plan['sha256'],
            approved_scope=scope, approved_scope_hash=digest(scope),
            finding_ids=list(task.get('active_fix_finding_ids') or []),
            completion_artifact_id=None, completion_hash=None,
            offered_by=actor['id'], offered_at=self.clock.now())
        repo.add('worker_assignments', assignment)
        audit(repo, self.clock, actor, 'WORKER_ASSIGNMENT_OFFERED', task['id'],
              assignment_id=assignment['id'], generation=generation,
              approved_plan_hash=plan['sha256'], approved_scope_hash=assignment['approved_scope_hash'])
        return assignment

    def _legacy_worker_only(self):
        if not getattr(self, 'legacy_worker_test_mode', False):
            raise PermissionDenied('Legacy owner-transfer Worker path is test-only')

    def offer_task(self, actor_id, task_id, expected_version, key):
        self._legacy_worker_only()
        with self.command(actor_id, 'offer_task', key, [task_id, expected_version], Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            if actor.get('worker_type'):
                raise PermissionDenied('Worker cannot offer tasks')
            task = self.task_for(repo, task_id, actor, expected_version)
            if task['state'] != 'NEW' or task.get('worker_status'):
                raise Conflict('Task is not available to offer')
            task['worker_status'] = 'OFFERED'
            self.touch(repo, task)
            audit(repo, self.clock, actor, 'TASK_OFFERED', task_id, worker_status='OFFERED')
            box['response'] = task
            return task

    def list_available_worker_tasks(self, actor_id):
        with self.db.transaction() as repo:
            actor = self.actor(repo, actor_id, Role.BUILDER)
            if actor.get('worker_type') != 'workbuddy':
                raise PermissionDenied('WorkBuddy Worker principal required')
            formal = []
            for assignment in repo.find('worker_assignments', status='OFFERED'):
                task = repo.get('tasks', assignment['task_id'])
                if (task['state'] == 'EXECUTING' and not task.get('automation_frozen')
                        and self.clock.now() < task['deadline_at']):
                    formal.append({'task_id': task['id'], 'state': task['state'],
                                   'worker_status': assignment['status'],
                                   'assignment_id': assignment['id'],
                                   'generation': assignment['generation'],
                                   'version': assignment['version'],
                                   'deadline_at': task['deadline_at']})
            tasks = []
            if getattr(self, 'legacy_worker_test_mode', False):
                tasks = [task for task in repo.find('tasks')
                         if task.get('worker_status') == 'OFFERED' and task['state'] == 'NEW'
                         and self.clock.now() < task['deadline_at']]
        if formal:
            formal.sort(key=lambda item: (item['generation'], item['task_id']))
            return formal
        tasks.sort(key=lambda task: (task['created_at'], task['id']))
        return [{'task_id': task['id'], 'state': task['state'], 'worker_status': 'OFFERED',
                 'version': task['version'], 'deadline_at': task['deadline_at']} for task in tasks]

    def get_worker_task(self, actor_id, task_id):
        with self.db.transaction() as repo:
            actor = self.actor(repo, actor_id, Role.BUILDER)
            if actor.get('worker_type') != 'workbuddy':
                raise PermissionDenied('WorkBuddy Worker principal required')
            task = repo.get('tasks', task_id)
            assignment = self._assignment(repo, task_id)
            if assignment and (assignment['status'] == 'OFFERED'
                               or assignment.get('worker_principal_id') == actor_id):
                _, original = self.artifact(repo, task_id, task['original_task_id'], kinds={'SOURCE_FILE'})
                _, plan = self.artifact(repo, task_id, assignment['approved_plan_artifact_id'],
                                        assignment['approved_plan_hash'], {'PLAN'})
                return {'task': task, 'assignment': assignment,
                        'instruction': original.decode('utf-8'),
                        'approved_plan': plan.decode('utf-8'),
                        'approved_scope': assignment['approved_scope']}
            self._legacy_worker_only()
            if not (task.get('worker_status') == 'OFFERED' or
                    (task.get('worker_status') == 'CLAIMED' and task['owner_id'] == actor_id)):
                raise PermissionDenied('Task is not offered to this Worker')
            _, content = self.artifact(repo, task_id, task['original_task_id'], kinds={'SOURCE_FILE'})
            return {'task': task, 'instruction': content.decode('utf-8')}

    def claim_task(self, actor_id, task_id, expected_version, key):
        if type(expected_version) is not int or expected_version < 0:
            raise HubError('An integer expected_version is required')
        with self.command(actor_id, 'claim_task', key, [task_id, expected_version], Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            if actor.get('worker_type') != 'workbuddy':
                raise PermissionDenied('WorkBuddy Worker principal required')
            task = repo.get('tasks', task_id)
            assignment = self._assignment(repo, task_id)
            if assignment:
                if (assignment['version'] != expected_version or assignment['status'] != 'OFFERED'
                        or task['state'] != 'EXECUTING' or task.get('automation_frozen')):
                    raise Conflict('Worker assignment is not available to claim')
                claimed = {**assignment, 'status': 'CLAIMED', 'version': assignment['version'] + 1,
                           'worker_principal_id': actor_id, 'lease_token': uid('LEASE'),
                           'lease_until': min(task['deadline_at'],
                                              self.clock.now() + self.settings.lease_seconds * 1_000_000),
                           'lease_generation': assignment['lease_generation'] + 1,
                           'attempts': assignment['attempts'] + 1,
                           'claimed_at': self.clock.now()}
                repo.compare_and_swap('worker_assignments', claimed,
                                      {'version': assignment['version'], 'status': 'OFFERED',
                                       'lease_generation': assignment['lease_generation']})
                audit(repo, self.clock, actor, 'WORKER_ASSIGNMENT_CLAIMED', task_id,
                      assignment_id=claimed['id'], generation=claimed['generation'],
                      lease_generation=claimed['lease_generation'])
                box['response'] = claimed
                return claimed
            self._legacy_worker_only()
            if task['version'] != expected_version:
                raise Conflict('Stale task version')
            if task.get('worker_status') != 'OFFERED' or task['state'] != 'NEW':
                raise Conflict('Task is not available to claim')
            if self.clock.now() >= task['deadline_at']:
                raise HubError('Task is expired')
            task['owner_id'] = actor_id
            task['worker_status'] = 'CLAIMED'
            task['worker_claimed_by'] = actor_id
            task['worker_claimed_at'] = self.clock.now()
            self.touch(repo, task)
            audit(repo, self.clock, actor, 'TASK_CLAIMED', task_id, worker_status='CLAIMED')
            box['response'] = task
            return task

    def report_worker_progress(self, actor_id, task_id, summary, key):
        if not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 200:
            raise HubError('Progress summary must be 1 to 200 characters')
        with self.command(actor_id, 'report_worker_progress', key, [task_id, summary], Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            if actor.get('worker_type') != 'workbuddy':
                raise PermissionDenied('WorkBuddy Worker principal required')
            task = repo.get('tasks', task_id)
            assignment = self._assignment(repo, task_id, ('CLAIMED',))
            if assignment:
                if (assignment.get('worker_principal_id') != actor_id
                        or task['state'] != 'EXECUTING' or task.get('automation_frozen')
                        or assignment['lease_until'] <= self.clock.now()):
                    raise PermissionDenied('Worker assignment is not active for this principal')
                updated = {**assignment, 'version': assignment['version'] + 1,
                           'progress_summary': summary.strip(), 'progress_at': self.clock.now(),
                           'lease_until': min(task['deadline_at'],
                                              self.clock.now() + self.settings.lease_seconds * 1_000_000)}
                repo.compare_and_swap('worker_assignments', updated,
                                      {'version': assignment['version'], 'status': 'CLAIMED',
                                       'lease_generation': assignment['lease_generation']})
                audit(repo, self.clock, actor, 'WORKER_ASSIGNMENT_PROGRESS', task_id,
                      assignment_id=updated['id'], generation=updated['generation'])
                box['response'] = updated
                return updated
            self._legacy_worker_only()
            task = self.task_for(repo, task_id, actor)
            if task.get('worker_status') != 'CLAIMED':
                raise PermissionDenied('Claim task before reporting progress')
            task['worker_progress'] = summary.strip()
            task['worker_progress_at'] = self.clock.now()
            self.touch(repo, task)
            audit(repo, self.clock, actor, 'WORKER_PROGRESS', task_id)
            box['response'] = task
            return task

    def complete_worker_task(self, actor_id, task_id, artifact_id, expected_version, key):
        """Freeze the claimed WorkBuddy result without bypassing the review state machine."""
        with self.command(actor_id, 'complete_worker_task', key,
                          [task_id, artifact_id, expected_version], Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            if actor.get('worker_type') != 'workbuddy':
                raise PermissionDenied('WorkBuddy Worker principal required')
            task = repo.get('tasks', task_id)
            assignment = self._assignment(repo, task_id, ('CLAIMED',))
            if assignment:
                if (assignment['version'] != expected_version
                        or assignment.get('worker_principal_id') != actor_id
                        or task['state'] != 'EXECUTING' or task.get('automation_frozen')
                        or assignment['lease_until'] <= self.clock.now()):
                    raise Conflict('Task is not a claimed Worker assignment awaiting completion')
                artifact, _ = self.artifact(repo, task_id, artifact_id, kinds={'EVIDENCE', 'DIFF', 'REPORT'})
                if (artifact['created_by'] != actor_id
                        or artifact['created_at'] < assignment['claimed_at']
                        or not assignment.get('progress_at')
                        or assignment['progress_at'] < artifact['created_at']):
                    raise HubError('Worker artifact and subsequent progress are required')
                completed = {**assignment, 'status': 'COMPLETED', 'version': assignment['version'] + 1,
                             'lease_token': None, 'lease_until': 0,
                             'completion_artifact_id': artifact_id,
                             'completion_hash': artifact['sha256'],
                             'completed_by': actor_id, 'completed_at': self.clock.now()}
                repo.compare_and_swap('worker_assignments', completed,
                                      {'version': assignment['version'], 'status': 'CLAIMED',
                                       'lease_generation': assignment['lease_generation']})
                audit(repo, self.clock, actor, 'WORKER_ASSIGNMENT_COMPLETED', task_id,
                      assignment_id=completed['id'], artifact_id=artifact_id,
                      sha256=artifact['sha256'], generation=completed['generation'])
                box['response'] = {**completed, 'task_state': task['state'],
                                   'task_owner_id': task['owner_id']}
                return box['response']
            self._legacy_worker_only()
            task = self.task_for(repo, task_id, actor, expected_version)
            if (task.get('worker_status') != 'CLAIMED' or task.get('worker_claimed_by') != actor_id
                    or task['state'] != 'NEW' or task.get('active_rr_id')):
                raise Conflict('Task is not a claimed Worker task awaiting completion')
            artifact, _ = self.artifact(repo, task_id, artifact_id, kinds={'EVIDENCE'})
            if (artifact['created_by'] != actor_id
                    or artifact['created_at'] < task['worker_claimed_at']
                    or not task.get('worker_progress_at')
                    or task['worker_progress_at'] < artifact['created_at']):
                raise HubError('Worker artifact and subsequent progress are required')
            task.update(worker_status='COMPLETED', worker_completed_by=actor_id,
                        worker_completed_at=self.clock.now(),
                        worker_completion_artifact_id=artifact_id,
                        worker_completion_sha256=artifact['sha256'])
            self.touch(repo, task)
            audit(repo, self.clock, actor, 'WORKER_COMPLETED', task_id,
                  artifact_id=artifact_id, sha256=artifact['sha256'],
                  worker_claimed_by=task['worker_claimed_by'])
            box['response'] = task
            return task
