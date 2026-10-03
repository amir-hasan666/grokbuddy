"""Explicit, audited Reviewer B registration and future-request routing."""

from copy import deepcopy
import json
import re

from grokbuddy.domain.model import (ACTIVE_REQUEST, Conflict, HubError, PermissionDenied,
                                   ReviewDeliveryUnavailable, Role)
from grokbuddy.domain.review_result import frozen_result_fields, result_binding_error
from .common import Services, audit, uid


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_SERVER = re.compile(r"[0-9]{1,20}\Z")

REVIEWER_HTTP = 'REVIEWER_HTTP'
GITHUB_COMMENT = 'GITHUB_COMMENT'
LOCAL_ADAPTER = 'LOCAL_ADAPTER'


def select_review_delivery_channel(repo, task, reviewer, protocol_version):
    """Freeze one auditable delivery contract before a ReviewRequest exists."""
    if reviewer.get('reviewer_type') != 'grok_bot':
        return LOCAL_ADAPTER
    bindings = repo.find('github_bindings', task_id=task['id'])
    routes = repo.find('grok_reviewer_routes', task_id=task['id'])
    if not bindings and not routes:
        if protocol_version == 'v2' and task.get('review_protocol_version') == 'v2':
            return REVIEWER_HTTP
        raise ReviewDeliveryUnavailable(
            'Unbound Grok review delivery requires a formal v2 Task')
    if (len(bindings) == 1 and len(routes) == 1
            and routes[0]['reviewer_actor_id'] == reviewer['id']
            and routes[0].get('binding_id') == bindings[0]['id']):
        return GITHUB_COMMENT
    raise ReviewDeliveryUnavailable(
        'Grok review requires either no binding/route or one matching binding and route')


def grok_delivery_contract_matches(repo, rr, task, reviewer_actor_id):
    """Re-check the frozen channel without deriving authority from an external carrier."""
    if rr['envelope']['expected_reviewer_actor_id'] != reviewer_actor_id:
        return False
    bindings = repo.find('github_bindings', task_id=task['id'])
    routes = repo.find('grok_reviewer_routes', task_id=task['id'])
    channel = rr.get('delivery_channel')
    if channel == REVIEWER_HTTP:
        # Binding/route created later apply only to future requests.  They must
        # not rewrite or invalidate this RR's already frozen HTTP channel.
        return rr.get('protocol_version') == 'v2'
    if channel in (None, GITHUB_COMMENT):  # None preserves historical routed requests.
        return (len(bindings) == 1 and len(routes) == 1
                and routes[0]['reviewer_actor_id'] == reviewer_actor_id
                and routes[0].get('binding_id') == bindings[0]['id'])
    return False


class GrokRoutingService(Services):
    def ensure_registry_reviewer(self, actor_id, reviewer_actor_id, name, agent_id, server_id):
        """Register a configured Reviewer or verify its immutable technical identity.

        Registry display names are operational labels.  An existing Actor row is
        not rewritten when that label changes; provider and execution identity
        remain immutable.
        """
        if (not isinstance(reviewer_actor_id, str) or not reviewer_actor_id
                or not isinstance(name, str) or not name
                or not isinstance(agent_id, str) or not _UUID.fullmatch(agent_id)
                or not isinstance(server_id, str) or not _SERVER.fullmatch(server_id)):
            raise HubError('Grok Reviewer identity configuration is invalid')
        provider_id = f'grok-bot:{server_id}:{agent_id}'
        with self.db.transaction() as repo:
            system = self.actor(repo, actor_id, Role.SYSTEM)
            old = repo.find('actors', id=reviewer_actor_id)
            if old:
                stable = old[0]
                if (stable.get('role') != Role.REVIEWER.value
                        or stable.get('provider_id') != provider_id
                        or stable.get('reviewer_type') != 'grok_bot'
                        or stable.get('agent_id') != agent_id
                        or stable.get('server_id') != server_id
                        or stable.get('enabled') is not True):
                    raise Conflict('Grok Reviewer technical identity is immutable')
                return stable
            record = dict(id=reviewer_actor_id, name=name, role=Role.REVIEWER.value,
                          provider_id=provider_id, reviewer_type='grok_bot',
                          agent_id=agent_id, server_id=server_id, enabled=True)
            repo.add('actors', record)
            audit(repo, self.clock, system, 'GROK_REVIEWER_REGISTERED',
                  reviewer_actor_id=reviewer_actor_id, provider_id=provider_id,
                  registration_source='REVIEWER_REGISTRY')
            return record

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
            if (actor['reviewer_type'] != 'grok_bot'
                    or rr['task_id'] != task_id or rr['review_id'] != review_id
                    or not grok_delivery_contract_matches(
                        repo, rr, repo.get('tasks', rr['task_id']), reviewer_actor_id)):
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
            if not grok_delivery_contract_matches(repo, rr, task, reviewer_actor_id):
                raise PermissionDenied('Review request has no authenticated Grok delivery route')
            envelope = dict(rr['envelope'])
            if envelope.get('protocol_version') == 'v2':
                # The immutable request records the version at dispatch.  A
                # ReviewStarted event may advance the Task, so an authenticated
                # Reviewer read receives the current CAS anchor for completion.
                envelope['expected_task_version'] = task['version']
            return dict(envelope=envelope, context_artifact_id=rr['context_artifact_id'],
                        expected_task_state=task['state'], expected_task_version=task['version'],
                        result_bindings=frozen_result_fields(envelope),
                        review_materials=self._grok_materials(repo, reviewer_actor_id, request_id)['artifacts'])

    def grok_result_preflight(self, reviewer_actor_id, request_id, payload):
        """Read-only schema/binding checks. Findings and verdict apply asynchronously."""
        current = self.grok_request(reviewer_actor_id, request_id)
        with self.db.transaction() as repo:
            actor = self.actor(repo, reviewer_actor_id, Role.REVIEWER)
            field_path = self.contracts.error_path('result', payload)
            error = ('VALIDATION_FAILURE', field_path, None) if field_path else result_binding_error(
                current['envelope'], payload, actor, current['expected_task_version'])
        return {'valid': error is None, 'review_request_id': request_id,
                'error_code': error[0] if error else None,
                'field_path': error[1] if error else None,
                'task_version': current['expected_task_version'],
                'checked': ['result_schema', 'request_bindings', 'reviewer_identity', 'task_version'],
                'not_checked': ['finding_transitions', 'verdict_policy', 'async_application'],
                'submitted': False}

    def grok_materials(self, reviewer_actor_id, request_id):
        """Resolve only RR-bound evidence; historical requests stay read-only."""
        with self.db.transaction() as repo:
            return self._grok_materials(repo, reviewer_actor_id, request_id)

    def grok_materials_check(self, reviewer_actor_id, request_id):
        """Read every whitelisted blob; never ACK, create evidence or advance a Task."""
        with self.db.transaction() as repo:
            materials = self._grok_materials(repo, reviewer_actor_id, request_id)
            checks = []
            for label, value in materials['artifacts'].items():
                for index, item in enumerate(value if isinstance(value, list) else [value]):
                    try:
                        artifact, _ = self.artifact(repo, materials['task_id'],
                                                    item['artifact_id'], item['sha256'])
                    except HubError as exc:
                        checks.append({'material': label, 'index': index, **item,
                                       'readable': False, 'error_code': exc.code})
                    else:
                        checks.append({'material': label, 'index': index, **item,
                                       'readable': True, 'size_bytes': artifact['size_bytes'],
                                       'error_code': None})
            return {'request_id': request_id, 'valid': all(c['readable'] for c in checks),
                    'checks': checks, 'scope': 'RR_BOUND_ARTIFACT_BYTES', 'submitted': False}

    def _grok_materials(self, repo, reviewer_actor_id, request_id):
        actor = self.actor(repo, reviewer_actor_id, Role.REVIEWER)
        rr = repo.get('review_requests', request_id)
        task = repo.get('tasks', rr['task_id'])
        if (actor.get('reviewer_type') != 'grok_bot'
                or rr['envelope']['expected_reviewer_actor_id'] != reviewer_actor_id
                or not grok_delivery_contract_matches(repo, rr, task, reviewer_actor_id)):
            raise PermissionDenied('Review request is not routed to this Reviewer')

        def ref(artifact_id, expected_sha=None):
            artifact = repo.get('artifacts', artifact_id)
            if (artifact['task_id'] != task['id']
                    or expected_sha is not None and artifact['sha256'] != expected_sha):
                raise PermissionDenied('Review material is outside frozen Task scope')
            return {'artifact_id': artifact_id, 'sha256': artifact['sha256']}

        materials = {
            'profile': ref(rr['envelope']['profile_artifact_id'], rr['envelope']['profile_sha256']),
            'input': ref(rr['input_artifact_id'], rr['envelope']['input_sha256']),
            'context': ref(rr['context_artifact_id']),
            'original_task': ref(task['original_task_id']),
        }
        trigger = task.get('trigger_evidence') or {}
        if trigger.get('source_artifact_id'):
            materials['trigger'] = ref(trigger['source_artifact_id'],
                                       trigger.get('source_artifact_sha256'))
        if rr['review_type'] == 'PLAN_REVIEW':
            _, content = self.artifact(repo, task['id'], rr['context_artifact_id'],
                                       kinds={'SOURCE_FILE'})
            context = json.loads(content)
            if context.get('supporting_artifacts'):
                materials['supporting_artifacts'] = [ref(item['artifact_id'], item['sha256'])
                                                     for item in context['supporting_artifacts']]
        if rr['review_type'] == 'FINAL_REVIEW':
            _, content = self.artifact(repo, task['id'], rr['input_artifact_id'],
                                       rr['envelope']['input_sha256'], {'FINAL_PACKAGE'})
            package = json.loads(content)
            if (package.get('task_id') != task['id']
                    or package.get('original_task', {}).get('artifact_id') != task['original_task_id']):
                raise PermissionDenied('Final package does not match its Task')
            for name in ('original_task', 'approved_plan', 'diff_artifact'):
                if name in package:
                    item = package[name]
                    materials[name] = ref(item['artifact_id'], item['sha256'])
            for name in ('test_results', 'generated_files'):
                materials[name] = [ref(item['artifact_id'], item['sha256'])
                                   for item in package.get(name, [])]
        return {'request_id': rr['id'], 'task_id': task['id'],
                'review_type': rr['review_type'], 'request_status': rr['status'],
                'artifacts': materials}

    def grok_artifact(self, reviewer_actor_id, request_id, artifact_id):
        """Read only evidence explicitly bound to this RR and its Task."""
        materials = self.grok_materials(reviewer_actor_id, request_id)
        allowed = [item for value in materials['artifacts'].values()
                   for item in (value if isinstance(value, list) else [value])]
        match = next((item for item in allowed if item['artifact_id'] == artifact_id), None)
        if match is None:
            raise PermissionDenied('Artifact is outside frozen Reviewer scope')
        with self.db.transaction() as repo:
            return self.artifact(repo, materials['task_id'], artifact_id, match['sha256'])

    def grok_ingress_status(self, reviewer_actor_id, ingress_id):
        """Read a submission receipt without advancing inbox processing."""
        with self.db.transaction() as repo:
            self.actor(repo, reviewer_actor_id, Role.REVIEWER)
            incoming = repo.get('inbox_events', ingress_id)
            rr = repo.get('review_requests', incoming['review_request_id'])
            task = repo.get('tasks', rr['task_id'])
            if (incoming['actor_id'] != reviewer_actor_id
                    or incoming['task_id'] != task['id']
                    or rr['envelope']['expected_reviewer_actor_id'] != reviewer_actor_id
                    or not grok_delivery_contract_matches(repo, rr, task, reviewer_actor_id)):
                raise PermissionDenied('Ingress receipt is outside Reviewer scope')
            field_path = incoming.get('field_path')
            field_path_source = 'STORED' if field_path is not None else None
            if (field_path is None and incoming['status'] == 'REJECTED'
                    and incoming.get('event_type') == 'ReviewCompleted'):
                _, content = self.artifact(repo, task['id'], incoming['payload_artifact_id'],
                                           incoming['payload_sha256'], {'REVIEW_RESULT'})
                field_path = self.contracts.error_path('result', json.loads(content))
                if field_path is not None:
                    field_path_source = 'CURRENT_SCHEMA_REVALIDATION'
            return {'ingress_id': incoming['id'], 'review_request_id': rr['id'],
                    'status': incoming['status'], 'error_code': incoming.get('error_code'),
                    'field_path': field_path, 'field_path_source': field_path_source,
                    'reason_code': (incoming.get('rejection_details') or {}).get('reason_code'),
                    'rejection_details': deepcopy(incoming.get('rejection_details')),
                    'rejection_details_source': 'STORED' if incoming.get('rejection_details') else None,
                    'request_status': rr['status'],
                    'task': {'id': task['id'], 'state': task['state'], 'version': task['version']},
                    'accepted_review': next((
                        {'review_id': review['id'], 'reported_verdict': review['reported_verdict'],
                         'effective_verdict': review['effective_verdict']}
                        for review in repo.find('reviews', review_request_id=rr['id'])
                        if incoming['event_type'] == 'ReviewCompleted'
                        and incoming['status'] in ('APPLIED', 'DUPLICATE')
                        and review['result_hash'] == incoming['payload_sha256']), None)}

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
