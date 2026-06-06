import unittest
from datetime import timedelta

from openclaw_video.job_state import JobStatus
from openclaw_video.job_store import InMemoryJobStore, JobLeaseError, JobNotFound, JobOwnershipError, now_utc


class JobStoreTests(unittest.TestCase):
    def test_claim_next_moves_queued_to_running_once(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        claimed = store.claim_next()
        self.assertEqual(claimed.job_id, job.job_id)
        self.assertEqual(claimed.status, JobStatus.RUNNING)
        self.assertEqual(claimed.attempt_count, 1)
        self.assertEqual(claimed.worker_id, "worker")
        self.assertIsNotNone(claimed.lease_expires_at)
        self.assertIsNone(store.claim_next())

    def test_create_job_idempotency_key_returns_existing_job(self):
        store = InMemoryJobStore()
        first = store.create_job(
            "owner",
            "session",
            "https://v.douyin.com/abc",
            idempotency_key="same-request",
        )
        second = store.create_job(
            "owner",
            "session",
            "https://v.douyin.com/abc",
            idempotency_key="same-request",
        )
        self.assertEqual(first.job_id, second.job_id)
        self.assertEqual(
            store.get_job_by_idempotency("owner", "session", "same-request").job_id,
            first.job_id,
        )

    def test_owner_isolation(self):
        store = InMemoryJobStore()
        job = store.create_job("owner-a", "session", "https://v.douyin.com/abc")
        with self.assertRaises(JobOwnershipError):
            store.get_job(job.job_id, "owner-b")

    def test_count_active_jobs_excludes_terminal_statuses(self):
        store = InMemoryJobStore()
        running = store.create_job("owner", "session", "https://v.douyin.com/running")
        claimed = store.claim_next("worker-a")
        queued = store.create_job("owner", "session", "https://v.douyin.com/queued")
        succeeded = store.create_job("owner", "session", "https://v.douyin.com/succeeded")
        failed = store.create_job("owner", "session", "https://v.douyin.com/failed")
        cancelled = store.create_job("owner", "session", "https://v.douyin.com/cancelled")
        self.assertEqual(claimed.job_id, running.job_id)
        self.assertEqual(running.status, JobStatus.RUNNING)
        store.complete_job(succeeded.job_id, {"ok": True}, "schema")
        store.fail_job(failed.job_id, "failed")
        store.cancel_job(cancelled.job_id, "owner")
        self.assertEqual(store.count_active_jobs("owner"), 2)
        self.assertEqual(store.count_active_jobs("other-owner"), 0)
        self.assertEqual(queued.status, JobStatus.QUEUED)

    def test_complete_stores_result(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        store.claim_next()
        completed = store.complete_job(job.job_id, {"ok": True}, "schema")
        self.assertEqual(completed.status, JobStatus.SUCCEEDED)
        self.assertEqual(store.get_result(job.job_id, "owner").result, {"ok": True})

    def test_complete_rejects_stale_worker(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        store.claim_next("worker-a")
        with self.assertRaises(JobLeaseError):
            store.complete_job(job.job_id, {"ok": True}, "schema", worker_id="worker-b")

    def test_fail_rejects_stale_worker(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        store.claim_next("worker-a")
        with self.assertRaises(JobLeaseError):
            store.fail_job(job.job_id, "tool_failed", worker_id="worker-b")

    def test_heartbeat_extends_current_worker_lease(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        store.claim_next("worker-a", lease_seconds=1)
        updated = store.heartbeat_job(job.job_id, "worker-a", lease_seconds=30)
        self.assertEqual(updated.worker_id, "worker-a")
        self.assertGreater(updated.lease_expires_at, updated.heartbeat_at)

    def test_heartbeat_rejects_wrong_worker(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        store.claim_next("worker-a")
        with self.assertRaises(JobLeaseError):
            store.heartbeat_job(job.job_id, "worker-b")

    def test_recover_expired_lease_requeues_job(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        claimed = store.claim_next("worker-a", lease_seconds=1)
        recovered = store.recover_expired_leases(now=claimed.lease_expires_at + timedelta(seconds=1))
        self.assertEqual(recovered, 1)
        requeued = store.get_job(job.job_id)
        self.assertEqual(requeued.status, JobStatus.QUEUED)
        self.assertIsNone(requeued.worker_id)
        reclaimed = store.claim_next("worker-b")
        self.assertEqual(reclaimed.job_id, job.job_id)
        self.assertEqual(reclaimed.attempt_count, 2)

    def test_cancel_enforces_owner(self):
        store = InMemoryJobStore()
        job = store.create_job("owner-a", "session", "https://v.douyin.com/abc")
        with self.assertRaises(JobOwnershipError):
            store.cancel_job(job.job_id, "owner-b")
        cancelled = store.cancel_job(job.job_id, "owner-a")
        self.assertEqual(cancelled.status, JobStatus.CANCELLED)

    def test_cancel_missing_job(self):
        store = InMemoryJobStore()
        with self.assertRaises(JobNotFound):
            store.cancel_job("missing", "owner")

    def test_cleanup_terminal_jobs_before_only_removes_owner_expired_terminal_jobs(self):
        store = InMemoryJobStore()
        old_cutoff = now_utc() - timedelta(days=7)
        old_finished_at = old_cutoff - timedelta(seconds=1)
        recent_finished_at = old_cutoff + timedelta(seconds=1)

        old_upload = store.create_job("owner", "session", "upload://11111111-1111-1111-1111-111111111111/sample.mp4")
        old_douyin = store.create_job("owner", "session", "https://v.douyin.com/old")
        recent = store.create_job("owner", "session", "https://v.douyin.com/recent")
        active = store.create_job("owner", "session", "https://v.douyin.com/active")
        other_owner = store.create_job("other-owner", "session", "https://v.douyin.com/other")

        store.complete_job(old_upload.job_id, {"ok": True}, "schema")
        store.fail_job(old_douyin.job_id, "failed")
        store.cancel_job(recent.job_id, "owner")
        store.complete_job(other_owner.job_id, {"ok": True}, "schema")

        old_upload.finished_at = old_finished_at
        old_douyin.finished_at = old_finished_at
        recent.finished_at = recent_finished_at
        other_owner.finished_at = old_finished_at

        result = store.cleanup_terminal_jobs_before("owner", old_cutoff)

        self.assertEqual(result.deleted_jobs, 2)
        self.assertEqual(result.deleted_results, 1)
        self.assertEqual(set(result.deleted_job_ids), {old_upload.job_id, old_douyin.job_id})
        self.assertEqual(result.upload_uris, (old_upload.video_url_canonical,))
        with self.assertRaises(JobNotFound):
            store.get_job(old_upload.job_id, "owner")
        with self.assertRaises(JobNotFound):
            store.get_job(old_douyin.job_id, "owner")
        self.assertEqual(store.get_job(recent.job_id, "owner").status, JobStatus.CANCELLED)
        self.assertEqual(store.get_job(active.job_id, "owner").status, JobStatus.QUEUED)
        self.assertEqual(store.get_job(other_owner.job_id, "other-owner").status, JobStatus.SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
