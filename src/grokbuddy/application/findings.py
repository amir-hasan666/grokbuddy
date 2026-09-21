from grokbuddy.domain.model import HubError, Role
from grokbuddy.domain.rules import finding_transition
from .common import Services, uid, audit


class FindingService(Services):
    def respond_finding(self, actor_id, finding_id, action, evidence_id, expected_version, key):
        with self.command(actor_id, 'respond_finding', key,
                          [finding_id, action, evidence_id, expected_version], Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            finding = repo.get('review_findings', finding_id)
            task = self.task_for(repo, finding['task_id'], actor, expected_version)
            if task['active_rr_id']:
                raise HubError('Finding responses are frozen during an active review')
            if action not in ('accept', 'reject', 'fix'):
                raise HubError('Reviewer verification only enters through an evaluation event')
            if action in ('reject', 'fix'):
                self.artifact(repo, task['id'], evidence_id, kinds={'EVIDENCE', 'TEST_RESULT', 'DIFF'})
            if action == 'fix':
                plan_fix = finding.get('review_type') == 'PLAN_REVIEW' and task['state'] == 'PLANNING'
                if task['state'] != 'EXECUTING' and not plan_fix:
                    raise HubError('Begin the matching remediation before recording a fix')
            old = finding['status']
            finding['status'] = finding_transition(old, action, actor['role'])
            finding['version'] += 1
            finding['updated_at'] = self.clock.now()
            repo.save('review_findings', finding)
            repo.add('finding_events', dict(id=uid('EVT'), finding_id=finding_id, task_id=task['id'],
                     old_status=old, new_status=finding['status'], actor_id=actor_id,
                     evidence_artifact_id=evidence_id, at=self.clock.now()))
            self.touch(repo, task)
            audit(repo, self.clock, actor, 'FINDING_' + action.upper(), task['id'], old, finding['status'],
                  finding_id=finding_id, evidence_artifact_id=evidence_id)
            box['response'] = finding
            return finding
