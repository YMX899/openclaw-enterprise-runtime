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


if __name__ == "__main__":
    unittest.main()
