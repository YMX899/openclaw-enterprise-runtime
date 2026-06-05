import unittest

from openclaw_video.identity import IdentityError, derive_openclaw_routing_user, derive_principal


class IdentityTests(unittest.TestCase):
    def test_derives_stable_principal_without_plain_ids(self):
        principal = derive_principal(
            "secret",
            {"id": "account-1"},
            {"items": [{"id": "tenant-1", "current": True}]},
        )
        self.assertEqual(principal.account_id, "account-1")
        self.assertEqual(principal.tenant_id, "tenant-1")
        self.assertEqual(len(principal.principal_id), 64)
        self.assertNotIn("tenant-1", principal.principal_id)
        self.assertNotIn("account-1", principal.principal_id)

    def test_fails_closed_when_no_current_workspace(self):
        with self.assertRaises(IdentityError):
            derive_principal("secret", {"id": "account-1"}, {"items": [{"id": "tenant-1"}]})

    def test_fails_closed_when_multiple_current_workspaces(self):
        with self.assertRaises(IdentityError):
            derive_principal(
                "secret",
                {"id": "account-1"},
                {"items": [{"id": "a", "current": True}, {"id": "b", "current": True}]},
            )

    def test_routing_user_depends_on_session(self):
        a = derive_openclaw_routing_user("secret", "principal", "session-a")
        b = derive_openclaw_routing_user("secret", "principal", "session-b")
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()

