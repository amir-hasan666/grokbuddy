from grokbuddy.application.common import Services, uid, digest, audit
from grokbuddy.application.events import persist_event
from grokbuddy.domain.model import Conflict, Role


class SQLiteMockQueue(Services):
    """Durable simulation transport. Exposes only queue methods to the Mock adapter."""
    def enqueue(self, key, envelope):
        with self.db.transaction() as repo:
            old = repo.find('mock_jobs', id=key)
            if old:
                if old[0]['request_digest'] != digest(envelope['request']):
                    raise Conflict('Delivery key reused for another request')
                return
            repo.add('mock_jobs', dict(id=key, envelope=envelope, request_digest=digest(envelope['request']),
                     status='READY', lease_until=0, lease_token=None))

    def contains(self, key):
        with self.db.transaction() as repo:
            return bool(repo.find('mock_jobs', id=key))

    def take(self, key=None):
        with self.db.transaction() as repo:
            for job in repo.find('mock_jobs'):
                if key is not None and job['id'] != key:
                    continue
                if job['status'] == 'READY' or (job['status'] == 'LEASED' and job['lease_until'] <= self.clock.now()):
                    job.update(status='LEASED', lease_token=uid('LEASE'),
                               lease_until=self.clock.now() + self.settings.lease_seconds * 1_000_000)
                    repo.save('mock_jobs', job)
                    return job
            return None

    def completed(self, key):
        with self.db.transaction() as repo:
            jobs = repo.find('mock_jobs', id=key)
            return bool(jobs and jobs[0]['status'] == 'DONE')

    def complete(self, job, events):
        with self.db.transaction() as repo:
            current = repo.get('mock_jobs', job['id'])
            if current['status'] != 'LEASED' or current['lease_token'] != job['lease_token']:
                raise Conflict('Mock evaluation lease lost')
            for event in events:
                persist_event(repo, self, event)
            current.update(status='DONE', lease_token=None)
            repo.save('mock_jobs', current)
            request = job['envelope']['request']
            audit(repo, self.clock, self.actor(repo, request['expected_reviewer_actor_id'], Role.REVIEWER),
                  'MOCK_EVALUATED', request['task_id'], request_id=request['review_request_id'], event_count=len(events))
