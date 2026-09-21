from pathlib import Path
from uuid import uuid4
import socket
import pytest

from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.infrastructure.clock import ManualClock


CONTRACTS = Path(__file__).resolve().parents[1] / 'docs' / 'contracts'


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    original_connect = socket.socket.connect

    def local_only(sock, address):
        # Windows' asyncio Proactor loop implements socketpair with an
        # ephemeral loopback TCP connection.  Permit only that local runtime
        # primitive while keeping every external connection prohibited.
        if (isinstance(address, tuple) and address
                and address[0] in ('127.0.0.1', '::1')):
            return original_connect(sock, address)
        raise AssertionError('Local Core tests must not make network connections')

    def denied(*args, **kwargs):
        raise AssertionError('Local Core tests must not make network connections')

    monkeypatch.setattr(socket.socket, 'connect', local_only)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def runtime(tmp_path):
    return LocalRuntime(tmp_path / '本地 core', CONTRACTS, clock=ManualClock(),
                        jitter=lambda maximum: 1, legacy_create_test_mode=True,
                        legacy_worker_test_mode=True)


class Flow:
    def __init__(self, runtime, create=True):
        self.r = runtime
        self.h = runtime.hub
        if create:
            self.id = self.h.create_task('builder', 'A local task with evidence', self.key())['id']

    @staticmethod
    def key():
        return str(uuid4())

    @property
    def task(self):
        return self.h.get_task(self.id)

    @property
    def version(self):
        return self.task['version']

    def rows(self, table, **filters):
        with self.r.db.transaction() as repo:
            return repo.find(table, **filters)

    def artifact(self, kind='EVIDENCE', text='local evidence'):
        return self.h.submit_artifact('builder', self.id, kind, text.encode(), self.key())

    def move(self, action):
        return self.h.move('builder', self.id, action, self.version, self.key())

    def plan(self):
        if self.task['state'] in ('NEW', 'PLAN_CHANGES_REQUIRED'):
            self.move('begin_plan')
        artifact = self.artifact('PLAN', 'Independent review plan ' + self.key())
        return self.h.submit_plan('builder', self.id, artifact['id'], self.version, self.key())

    def request(self, kind='PLAN_REVIEW', scenario='PASS', **config):
        receipt = self.h.request_review('builder', self.id, kind, 'mock-reviewer', self.version, self.key())
        assert receipt['status'] == 'PENDING'
        self.r.mock.configure(receipt['review_request_id'], scenario, **config)
        return receipt['review_request_id']

    def drive(self):
        result = self.r.tick()
        while self.r.events.handle_one() is not None:
            pass
        return result

    def executing(self):
        self.plan()
        self.request()
        self.drive()
        assert self.task['state'] == 'PLAN_APPROVED'
        self.move('execute')

    def ref(self, identity):
        row = self.rows('artifacts', id=identity)[0]
        return {'artifact_id': row['id'], 'sha256': row['sha256']}

    def package(self):
        if self.task['state'] == 'FINAL_CHANGES_REQUIRED':
            self.move('execute')
        test = self.artifact('TEST_RESULT', 'The latest tests passed: ' + self.key())
        self.h.self_test('builder', self.id, test['id'], True, self.version, self.key())
        profile = self.h.profile_snapshot('builder', self.id, self.key())
        diff = self.artifact('DIFF', 'Updated source: ' + self.key())
        task = self.task
        package = dict(protocol_version='v1', task_id=self.id, content_revision=task['content_revision'],
                       original_task=self.ref(task['original_task_id']), approved_plan=self.ref(task['approved_plan_id']),
                       change_scope='Local implementation', changed_files=['local.txt'], diff_artifact=self.ref(diff['id']),
                       test_results=[self.ref(test['id'])], self_test={'status': 'PASS', 'summary': 'Local tests passed'},
                       known_risks=[], unverified_items=['External integration'], review_profile='generic',
                       review_profile_version='1.0', profile_sha256=profile['sha256'], profile_artifact_id=profile['id'])
        self.h.submit_final_package('builder', self.id, package, self.version, self.key())
        return package

    def action(self):
        evidence = self.artifact()
        script = self.artifact('SQL', '-- reviewed action script; no actual database execution')
        return dict(operation='PRODUCTION_DML', environment='production', targets=['one-approved-resource'], parameters={'key': 42},
                    artifact_id=script['id'], precheck_artifact_id=evidence['id'], backup_artifact_id=evidence['id'],
                    rollback_artifact_id=evidence['id'], verification_artifact_id=evidence['id'])


@pytest.fixture
def flow(runtime):
    return Flow(runtime)
