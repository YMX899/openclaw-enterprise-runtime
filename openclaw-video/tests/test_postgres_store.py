from datetime import UTC, datetime, timedelta
import unittest

from openclaw_video.job_state import JobStatus
from openclaw_video.job_store import JobLeaseError
from openclaw_video.postgres_store import Jsonb, PostgresJobStore


def job_row(**overrides):
    now = datetime(2026, 6, 6, tzinfo=UTC)
    row = {
        "job_id": "job-1",
        "owner_principal_id": "owner",
        "bridge_session_id": "session",
        "video_url_canonical": "https://v.douyin.com/abc",
        "status": "queued",
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "attempt_count": 0,
        "error_code": None,
        "result_schema_version": None,
        "result_location": None,
        "idempotency_key": None,
        "worker_id": None,
        "heartbeat_at": None,
        "lease_expires_at": None,
    }
    row.update(overrides)
    return row


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.connection.queries.append((sql, params))

    def fetchone(self):
        if not self.connection.results:
            return None
        return self.connection.results.pop(0)

    def fetchall(self):
        if not self.connection.results:
            return []
        return self.connection.results.pop(0)


class FakeConnection:
    def __init__(self, results):
        self.results = list(results)
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self)


class PostgresJobStoreTests(unittest.TestCase):
    def test_create_job_idempotency_conflict_returns_existing_without_changing_url(self):
        fake = FakeConnection([job_row(idempotency_key="same-request")])
        store = PostgresJobStore(connection_factory=lambda: fake)
        job = store.create_job(
            "owner",
            "session",
            "https://v.douyin.com/changed",
            idempotency_key="same-request",
        )
        sql, params = fake.queries[0]
        self.assertIn("ON CONFLICT (owner_principal_id, bridge_session_id, idempotency_key)", sql)
        self.assertIn("DO UPDATE SET idempotency_key = video_jobs.idempotency_key", sql)
        self.assertEqual(params, ("owner", "session", "https://v.douyin.com/changed", "same-request", "queued"))
        self.assertEqual(job.video_url_canonical, "https://v.douyin.com/abc")
        self.assertEqual(job.idempotency_key, "same-request")

    def test_claim_next_uses_worker_lease_parameters(self):
        now = datetime(2026, 6, 6, tzinfo=UTC)
        fake = FakeConnection(
            [
                job_row(
                    status="running",
                    started_at=now,
                    attempt_count=1,
                    worker_id="worker-a",
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=120),
                )
            ]
        )
        store = PostgresJobStore(connection_factory=lambda: fake)
        job = store.claim_next("worker-a", 120)
        sql, params = fake.queries[0]
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)
        self.assertEqual(params, ("worker-a", 120))
        self.assertEqual(job.status, JobStatus.RUNNING)
        self.assertEqual(job.worker_id, "worker-a")

    @unittest.skipIf(Jsonb is None, "psycopg Jsonb adapter is not installed")
    def test_complete_job_with_worker_id_requires_current_lease(self):
        fake = FakeConnection(
            [
                job_row(
                    status="succeeded",
                    worker_id=None,
                    result_schema_version="schema",
                    result_location="postgres://video_results/job-1",
                )
            ]
        )
        store = PostgresJobStore(connection_factory=lambda: fake)
        job = store.complete_job("job-1", {"ok": True}, "schema", worker_id="worker-a")
        sql, params = fake.queries[0]
        self.assertIn("AND worker_id = %s", sql)
        self.assertIn("AND status = 'running'", sql)
        self.assertEqual(params, ("schema", "postgres://video_results/job-1", "job-1", "worker-a"))
        self.assertEqual(job.status, JobStatus.SUCCEEDED)

    @unittest.skipIf(Jsonb is None, "psycopg Jsonb adapter is not installed")
    def test_complete_job_with_stale_worker_raises_lease_error(self):
        fake = FakeConnection([None])
        store = PostgresJobStore(connection_factory=lambda: fake)
        with self.assertRaises(JobLeaseError):
            store.complete_job("job-1", {"ok": True}, "schema", worker_id="worker-a")

    def test_recover_expired_leases_returns_database_count(self):
        fake = FakeConnection([[{"job_id": "job-1"}, {"job_id": "job-2"}]])
        store = PostgresJobStore(connection_factory=lambda: fake)
        recovered = store.recover_expired_leases()
        sql, _params = fake.queries[0]
        self.assertIn("lease_expires_at < now()", sql)
        self.assertEqual(recovered, 2)


if __name__ == "__main__":
    unittest.main()
