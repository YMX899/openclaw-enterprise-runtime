import unittest

from openclaw_video.session_store import (
    InMemorySessionStore,
    MessageValidationError,
    SessionOwnershipError,
)


class SessionStoreTests(unittest.TestCase):
    def test_create_and_list_sessions_by_owner(self):
        store = InMemorySessionStore()
        session_a = store.create_session("owner-a", "A session", "routing-a")
        store.create_session("owner-b", "B session", "routing-b")
        sessions = store.list_sessions("owner-a")
        self.assertEqual([session.id for session in sessions], [session_a.id])
        self.assertEqual(sessions[0].title, "A session")

    def test_session_owner_isolation(self):
        store = InMemorySessionStore()
        session = store.create_session("owner-a", "A session", "routing-a")
        with self.assertRaises(SessionOwnershipError):
            store.get_session(session.id, "owner-b")

    def test_messages_are_isolated_by_owner(self):
        store = InMemorySessionStore()
        session = store.create_session("owner-a", "A session", "routing-a")
        message = store.add_message(session.id, "owner-a", "user", "hello")
        self.assertEqual(store.list_messages(session.id, "owner-a")[0].id, message.id)
        with self.assertRaises(SessionOwnershipError):
            store.list_messages(session.id, "owner-b")

    def test_rejects_empty_message(self):
        store = InMemorySessionStore()
        session = store.create_session("owner-a", "A session", "routing-a")
        with self.assertRaises(MessageValidationError):
            store.add_message(session.id, "owner-a", "user", " ")

    def test_delete_messages_for_jobs_is_scoped_by_owner(self):
        store = InMemorySessionStore()
        session_a = store.create_session("owner-a", "A session", "routing-a")
        session_b = store.create_session("owner-b", "B session", "routing-b")
        target = store.add_message(session_a.id, "owner-a", "user", "target", job_id="job-1")
        kept_same_owner = store.add_message(session_a.id, "owner-a", "user", "keep", job_id="job-2")
        kept_other_owner = store.add_message(session_b.id, "owner-b", "user", "other", job_id="job-1")

        deleted = store.delete_messages_for_jobs("owner-a", ["job-1"])

        self.assertEqual(deleted, 1)
        self.assertEqual([message.id for message in store.list_messages(session_a.id, "owner-a")], [kept_same_owner.id])
        self.assertEqual([message.id for message in store.list_messages(session_b.id, "owner-b")], [kept_other_owner.id])
        self.assertNotEqual(target.id, kept_same_owner.id)


if __name__ == "__main__":
    unittest.main()
