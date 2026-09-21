import os
from pathlib import Path

from grokbuddy.domain.model import Settings, Role, Conflict
from grokbuddy.adapters.sqlite import SQLiteDatabase
from grokbuddy.adapters.artifact import FileArtifactStore
from grokbuddy.adapters.contracts import JsonContracts
from grokbuddy.adapters.mock import MockReviewerAdapter
from grokbuddy.adapters.grok_bot import GrokBotReviewerAdapter
from grokbuddy.adapters.mock_queue import SQLiteMockQueue
from grokbuddy.application.tasks import TaskService
from grokbuddy.application.worker_tasks import WorkerTaskService
from grokbuddy.application.reviews import ReviewService
from grokbuddy.application.findings import FindingService
from grokbuddy.application.governance import GovernanceService
from grokbuddy.application.events import EventService
from grokbuddy.application.github import (GitHubBindingService, GitHubEventService,
                                           GitHubProjectionService)
from grokbuddy.application.workers import (BindingRouteWorker, Dispatcher, ProjectionWorker,
                                            ReviewerIntakeWorker, Supervisor, TimeoutService)
from grokbuddy.application.grok_routing import GrokRoutingService
from grokbuddy.application.common import digest, iso
from .clock import SystemClock
from .profiles import PROFILE_RULES


class Hub(TaskService, WorkerTaskService, ReviewService, FindingService, GovernanceService, GrokRoutingService):
    """In-process trusted-host API. No MCP/HTTP/CLI integration or external authentication."""

    def __init__(self, *args, trigger_source_key=None, legacy_create_test_mode=False,
                 legacy_worker_test_mode=False):
        super().__init__(*args)
        self.trigger_source_key = trigger_source_key
        self.legacy_create_test_mode = legacy_create_test_mode
        self.legacy_worker_test_mode = legacy_worker_test_mode


class LocalRuntime:
    def __init__(self, directory, contracts_directory, *, clock=None, settings=None, jitter=None,
                 trigger_source_key=None, legacy_create_test_mode=False,
                 legacy_worker_test_mode=False):
        self.directory = Path(directory)
        self.settings = settings or Settings()
        self.clock = clock or SystemClock()
        self.db = SQLiteDatabase(self.directory / 'hub.db')
        self.store = FileArtifactStore(self.directory / 'artifacts', self.settings.max_artifact_bytes)
        self.contracts = JsonContracts(contracts_directory)
        self._seed()
        args = (self.db, self.store, self.contracts, self.clock, self.settings)
        if trigger_source_key is None:
            configured_key = os.environ.get('GROKBUDDY_TRIGGER_SOURCE_KEY')
            trigger_source_key = configured_key.encode('utf-8') if configured_key else None
        self.hub = Hub(*args, trigger_source_key=trigger_source_key,
                       legacy_create_test_mode=legacy_create_test_mode,
                       legacy_worker_test_mode=legacy_worker_test_mode)
        self.events = EventService(*args)
        self.timeouts = TimeoutService(*args)
        self.queue = SQLiteMockQueue(*args)
        self.mock = MockReviewerAdapter(self.queue, self.clock, iso)
        self.dispatcher = Dispatcher(*args, adapter=self.mock, jitter=jitter,
                                     reviewer_actor_ids={'mock-reviewer'})
        self.github_bindings = GitHubBindingService(*args)
        self.github_events = GitHubEventService(*args, review_service=self.hub)
        self.github_projections = GitHubProjectionService(*args)

    def _seed(self):
        # Local principals are explicit simulation identities, never production accounts.
        principals = [('builder', Role.BUILDER), ('mock-reviewer', Role.REVIEWER),
                      ('human', Role.HUMAN), ('system', Role.SYSTEM)]
        with self.db.transaction() as repo:
            for name, role in principals:
                record = dict(id=name, name=name, role=role.value, provider_id='local:' + name,
                              enabled=True, reviewer_type='mock' if role == Role.REVIEWER else None)
                old = repo.find('actors', id=name)
                if not old:
                    repo.add('actors', record)
                elif old[0] != record:
                    raise Conflict('Local principal configuration changed unexpectedly')
            worker = dict(id='workbuddy-worker', name='WorkBuddy Worker', role=Role.BUILDER.value,
                          provider_id='local:workbuddy-worker', enabled=True, reviewer_type=None,
                          worker_type='workbuddy')
            old_worker = repo.find('actors', id=worker['id'])
            if not old_worker:
                repo.add('actors', worker)
            elif old_worker[0] != worker:
                raise Conflict('WorkBuddy Worker principal configuration changed unexpectedly')
            ingress = dict(id='workbuddy-ingress', name='WorkBuddy Ingress',
                           role=Role.BUILDER.value, provider_id='local:workbuddy-ingress',
                           enabled=True, reviewer_type=None, trigger_source='workbuddy')
            old_ingress = repo.find('actors', id=ingress['id'])
            if not old_ingress:
                repo.add('actors', ingress)
            elif old_ingress[0] != ingress:
                raise Conflict('WorkBuddy ingress principal configuration changed unexpectedly')
            for name, rules in PROFILE_RULES.items():
                record = dict(id=name + '@1.0', name=name, version='1.0', rules=rules, sha256=digest(rules))
                old = repo.find('review_profiles', id=record['id'])
                if not old:
                    repo.add('review_profiles', record)
                elif old[0]['sha256'] != record['sha256']:
                    raise Conflict('Profile rules changed without a new version')

    def tick(self):
        """One bounded local worker iteration, explicitly invoked after request submission."""
        return {'timeouts': self.timeouts.sweep(), 'dispatch': self.dispatcher.dispatch_one(),
                'mock': self.mock.run_one(), 'event': self.events.handle_one()}

    def supervisor(self, *, projection_transport=None, binding_policy=None,
                   intake_source='local-mock-supervisor'):
        """Build the Phase 6.6 scheduler without starting a service or external I/O."""
        args = (self.db, self.store, self.contracts, self.clock, self.settings)
        intake = ReviewerIntakeWorker(
            *args, reviewer_actor_id='mock-reviewer',
            consumer=lambda rr: self.mock.run_one(rr['id']),
            reconciler=lambda rr: self.queue.completed(rr['id']),
            source=intake_source)
        binding_routes = BindingRouteWorker(self, binding_policy) if binding_policy else None
        projections = (ProjectionWorker(self.github_projections, projection_transport)
                       if projection_transport is not None else None)
        return Supervisor(binding_routes=binding_routes, recovery=self.timeouts,
                          dispatcher=self.dispatcher, intake=intake, events=self.events,
                          projections=projections)

    def grok_dispatcher(self, transport, reviewer_actor_id, public_base_url):
        """Build a separately routed worker; the local Mock worker stays unchanged."""
        with self.db.transaction() as repo:
            actor = repo.get('actors', reviewer_actor_id)
        if actor['role'] != Role.REVIEWER.value or actor['reviewer_type'] != 'grok_bot':
            raise Conflict('Configured actor is not a Grok Reviewer')
        adapter = GrokBotReviewerAdapter(
            self.db, transport, self.clock, reviewer_actor_id=reviewer_actor_id,
            agent_id=actor['agent_id'], server_id=actor['server_id'],
            public_base_url=public_base_url)
        args = (self.db, self.store, self.contracts, self.clock, self.settings)
        return Dispatcher(*args, adapter=adapter, reviewer_actor_ids={reviewer_actor_id})
