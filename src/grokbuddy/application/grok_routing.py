"""Explicit, audited Reviewer B registration and future-request routing."""

from copy import deepcopy
import json
import re

from grokbuddy.domain.model import ACTIVE_REQUEST, Conflict, HubError, PermissionDenied, Role
from .common import Services, audit, uid


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_SERVER = re.compile(r"[0-9]{1,20}\Z")


class GrokRoutingService(Services):
    def retry_final_with_grok(self, human_actor_id, builder_actor_id, task_id, old_request_id,
                              new_limit, new_deadline, reason, expected_version, key):
        """Resume a terminal Mock request via existing Application commands.

        Each step has a stable command key, so retrying after a partial failure
        reuses its persisted receipt instead of opening another review round.
        """
        if not isinstance(key, str) or not key or len(key) > 160:
            raise HubError('A bounded retry key is required')
        with self.db.transaction() as repo:
            task = repo.get('tasks', task_id)
            old = repo.get('review_requests', old_request_id)
            route = repo.find('grok_reviewer_routes', task_id=task_id)
            if (old['task_id'] != task_id or old['review_type'] != 'FINAL_REVIEW'
                    or old['status'] not in ('TIMED_OUT', 'ESCALATED', 'FAILED')
                    or old['envelope']['expected_reviewer_actor_id'] != 'mock-reviewer'
                    or not route):
                raise HubError('A terminal Mock Final RR and Reviewer B route are required')
            reviewer_actor_id = route[0]['reviewer_actor_id']
            _, package_bytes = self.artifact(repo, task_id, old['input_artifact_id'],
                                             old['envelope']['input_sha256'], {'FINAL_PACKAGE'})
            if not task.get('self_test_id') or task['approved_plan_id'] is None:
                raise HubError('Original Final package and self-test are required')
            old_test_id = task['self_test_id']
        package = json.loads(package_bytes)
        resumed = self.resume(human_actor_id, task_id, 'FINAL_REVIEW', new_limit,
                              new_deadline, reason, expected_version, key + ':resume')
        tested = self.self_test(builder_actor_id, task_id, old_test_id, True,
                                resumed['version'], key + ':self-test')
        new_package = deepcopy(package)
        new_package['content_revision'] = tested['content_revision']
        self.submit_final_package(builder_actor_id, task_id, new_package,
                                  tested['version'], key + ':final-package')
        return self.request_review(builder_actor_id, task_id, 'FINAL_REVIEW',
                                   reviewer_actor_id, tested['version'] + 1,
                                   key + ':request-review')

    def validate_grok_event_route(self, reviewer_actor_id, request_id, task_id, review_id):
        """Bind a signed event to a registered route; EventService decides replay/late status."""
        with self.db.transaction() as repo:
            actor = self.actor(repo, reviewer_actor_id, Role.REVIEWER)
            rr = repo.get('review_requests', request_id)
            routes = repo.find('grok_reviewer_routes', task_id=rr['task_id'])
            if (actor['reviewer_type'] != 'grok_bot'
                    or rr['task_id'] != task_id or rr['review_id'] != review_id
                    or rr['envelope']['expected_reviewer_actor_id'] != reviewer_actor_id
                    or not routes or routes[0]['reviewer_actor_id'] != reviewer_actor_id):
                raise PermissionDenied('Grok event does not match a registered route')

    def grok_request(self, reviewer_actor_id, request_id):
        """Return only a current request routed to this authenticated Reviewer."""
        with self.db.transaction() as repo:
            self.actor(repo, reviewer_actor_id, Role.REVIEWER)
            rr = repo.get('review_requests', request_id)
            task = repo.get('tasks', rr['task_id'])
            if (rr['envelope']['expected_reviewer_actor_id'] != reviewer_actor_id
                    or rr['status'] not in ACTIVE_REQUEST or task['active_rr_id'] != rr['id']
                    or task.get('automation_frozen')
                    or task['state'] in ('PLAN_HUMAN_REVIEW', 'FINAL_HUMAN_REVIEW')
                    or self.clock.now() >= rr['deadline_at'] or self.clock.now() >= task['deadline_at']):
                raise PermissionDenied('Review request is not current for this Reviewer')
            route = repo.find('grok_reviewer_routes', task_id=task['id'])
            if not route or route[0]['reviewer_actor_id'] != reviewer_actor_id:
                raise PermissionDenied('Review request has no authenticated Grok route')
            envelope = dict(rr['envelope'])
            if envelope.get('protocol_version') == 'v2':
                # The immutable request records the version at dispatch.  A
                # ReviewStarted event may advance the Task, so an authenticated
                # Reviewer read receives the current CAS anchor for completion.
                envelope['expected_task_version'] = task['version']
            return dict(envelope=envelope, context_artifact_id=rr['context_artifact_id'],
                        expected_task_state=task['state'], expected_task_version=task['version'])

    def grok_artifact(self, reviewer_actor_id, request_id, artifact_id):
        """Read only input/profile/context bytes referenced by a current RR."""
        request = self.grok_request(reviewer_actor_id, request_id)
        allowed = {request['context_artifact_id'],
                   request['envelope']['input_artifact_id'],
                   request['envelope']['profile_artifact_id']}
        if artifact_id not in allowed:
            raise PermissionDenied('Artifact is outside frozen Reviewer scope')
        with self.db.transaction() as repo:
            return self.artifact(repo, request['envelope']['task_id'], artifact_id)

    def register_reviewer(self, actor_id, reviewer_actor_id, name, agent_id, server_id):
        """Trusted local setup; never substitutes a credential or proves execution."""
        if (not isinstance(reviewer_actor_id, str) or not reviewer_actor_id
                or not isinstance(name, str) or not name
                or not isinstance(agent_id, str) or not _UUID.fullmatch(agent_id)
                or not isinstance(server_id, str) or not _SERVER.fullmatch(server_id)):
            raise HubError('Grok Reviewer identity configuration is invalid')
        provider_id = f'grok-bot:{server_id}:{agent_id}'
        record = dict(id=reviewer_actor_id, name=name, role=Role.REVIEWER.value,
                      provider_id=provider_id, reviewer_type='grok_bot',
                      agent_id=agent_id, server_id=server_id, enabled=True)
        with self.db.transaction() as repo:
            system = self.actor(repo, actor_id, Role.SYSTEM)
            old = repo.find('actors', id=reviewer_actor_id)
            if old:
                if old[0] != record:
                    raise Conflict('Grok Reviewer identity is immutable')
                return old[0]
            repo.add('actors', record)
            audit(repo, self.clock, system, 'GROK_REVIEWER_REGISTERED',
                  reviewer_actor_id=reviewer_actor_id, provider_id=provider_id)
            return record

    def route_future_reviews(self, actor_id, task_id, reviewer_actor_id, expected_version, key):
        params = [task_id, reviewer_actor_id, expected_version]
        with self.command(actor_id, 'route_future_grok_reviews', key, params, Role.BUILDER) as (repo, actor, box):
            if 'replay' in box:
                return box['replay']
            task = self.task_for(repo, task_id, actor, expected_version, live=False)
            if task['state'] in ('DONE', 'CANCELLED', 'FAILED'):
                raise HubError('Terminal Task cannot gain a future Reviewer route')
            reviewer = self.actor(repo, reviewer_actor_id, Role.REVIEWER)
            if reviewer['reviewer_type'] != 'grok_bot' or not reviewer.get('agent_id') or not reviewer.get('server_id'):
                raise HubError('Target is not a registered Grok Reviewer')
            if actor['provider_id'] == reviewer['provider_id']:
                raise HubError('Builder and Reviewer must have independent identities')
            binding = repo.find('github_bindings', task_id=task_id)
            if not binding:
                raise HubError('Grok route requires a bound pull request')
            old = repo.find('grok_reviewer_routes', task_id=task_id)
            if old:
                if old[0]['reviewer_actor_id'] != reviewer_actor_id:
                    raise Conflict('Grok route is immutable for this Task')
                box['response'] = old[0]
                return old[0]
            route = dict(id=uid('GRR'), task_id=task_id, reviewer_actor_id=reviewer_actor_id,
                         binding_id=binding[0]['id'], agent_id=reviewer['agent_id'],
                         server_id=reviewer['server_id'], created_at=self.clock.now(),
                         applies_to='FUTURE_REQUESTS_ONLY')
            repo.add('grok_reviewer_routes', route)
            audit(repo, self.clock, actor, 'GROK_REVIEWER_ROUTE_CREATED', task_id,
                  reviewer_actor_id=reviewer_actor_id, route_id=route['id'],
                  active_rr_unchanged=task.get('active_rr_id'))
            box['response'] = route
            return route
