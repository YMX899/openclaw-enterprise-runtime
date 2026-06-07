import base64
import hashlib
import unittest

from openclaw_video.openclaw_auth import (
    DifyDatabasePasswordAuthenticator,
    CompositeOpenClawAuthenticator,
    HuahuoPasswordAuthenticator,
    OpenClawAuthenticationError,
    OpenClawPasswordIdentity,
    compare_dify_password,
    parse_account_aliases,
)

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


def _dify_hash(password: str, salt: bytes) -> tuple[str, str]:
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 10000).hex().encode("ascii")
    return base64.b64encode(hashed).decode("ascii"), base64.b64encode(salt).decode("ascii")


class FakeCursor:
    def __init__(self, account_row, tenant_rows):
        self.account_row = account_row
        self.tenant_rows = tenant_rows
        self.calls = 0
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params):
        self.calls += 1
        self.last_query = query
        self.last_params = params
        self.queries.append((query, params))

    def fetchone(self):
        return self.account_row

    def fetchall(self):
        return self.tenant_rows


class FakeConnection:
    def __init__(self, account_row, tenant_rows):
        self.cursor_obj = FakeCursor(account_row, tenant_rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return self.cursor_obj


class OpenClawAuthTests(unittest.TestCase):
    def test_compare_dify_password_matches_pbkdf2_sha256_hex_base64_shape(self):
        hashed, salt = _dify_hash("correct-password", b"1234567890123456")

        self.assertTrue(compare_dify_password("correct-password", hashed, salt))
        self.assertFalse(compare_dify_password("wrong-password", hashed, salt))
        self.assertFalse(compare_dify_password("correct-password", "not-base64", salt))
        self.assertFalse(compare_dify_password("correct-password", hashed, "not-base64"))

    def test_parse_account_aliases(self):
        aliases = parse_account_aliases("phone-login=user@example.com, phone-b = account-b ")

        self.assertEqual(aliases["phone-login"], "user@example.com")
        self.assertEqual(aliases["phone-b"], "account-b")

    def test_database_authenticator_returns_profile_and_current_workspace(self):
        hashed, salt = _dify_hash("login-password", b"abcdefghijklmnop")
        account_row = {
            "id": "account-a",
            "email": "user@example.com",
            "name": "User",
            "password": hashed,
            "password_salt": salt,
            "status": "active",
        }
        tenant_rows = [
            {"id": "tenant-current", "current": True},
            {"id": "tenant-other", "current": False},
        ]
        conn = FakeConnection(account_row, tenant_rows)
        auth = DifyDatabasePasswordAuthenticator(
            account_aliases={"login-account": "user@example.com"},
            connection_factory=lambda: conn,
        )

        identity = auth.authenticate("login-account", "login-password")

        self.assertEqual(identity.profile, {"id": "account-a"})
        self.assertEqual(
            identity.workspaces,
            {
                "data": [
                    {"id": "tenant-current", "current": True},
                    {"id": "tenant-other", "current": False},
                ]
            },
        )
        account_query, account_params = conn.cursor_obj.queries[0]
        self.assertIn("lower(email)", account_query)
        self.assertIn("user@example.com", account_params)

    def test_database_authenticator_rejects_wrong_password_and_banned_status(self):
        hashed, salt = _dify_hash("login-password", b"abcdefghijklmnop")
        auth = DifyDatabasePasswordAuthenticator(
            connection_factory=lambda: FakeConnection(
                {
                    "id": "account-a",
                    "email": "user@example.com",
                    "name": "User",
                    "password": hashed,
                    "password_salt": salt,
                    "status": "banned",
                },
                [{"id": "tenant-current", "current": True}],
            )
        )

        with self.assertRaises(OpenClawAuthenticationError):
            auth.authenticate("user@example.com", "login-password")

        auth = DifyDatabasePasswordAuthenticator(
            connection_factory=lambda: FakeConnection(
                {
                    "id": "account-a",
                    "email": "user@example.com",
                    "name": "User",
                    "password": hashed,
                    "password_salt": salt,
                    "status": "active",
                },
                [{"id": "tenant-current", "current": True}],
            )
        )
        with self.assertRaises(OpenClawAuthenticationError):
            auth.authenticate("user@example.com", "wrong-password")

    @unittest.skipIf(httpx is None, "httpx is not installed")
    def test_huahuo_password_authenticator_uses_login_then_user_info_without_echoing_tokens(self):
        requests = []

        def handler(request):
            requests.append((request.method, request.url.path, request.headers.get("Authorization", ""), request.content))
            if request.url.path == "/api/login":
                return httpx.Response(
                    200,
                    json={"status": 1, "data": {"accessToken": "huahuo-access", "refreshToken": "huahuo-refresh"}},
                )
            if request.url.path == "/api/front/user/queryUserInfo":
                self.assertTrue(request.headers.get("Authorization", "").startswith("Bearer "))
                return httpx.Response(
                    200,
                    json={"status": 1, "data": {"id": 19, "loginName": "safe-user", "mobile": "hidden"}},
                )
            return httpx.Response(404)

        auth = HuahuoPasswordAuthenticator(
            "https://www.huahuoai.com",
            tenant_id="huahuo-front",
            transport=httpx.MockTransport(handler),
        )

        identity = auth.authenticate("phone-login", "login-password")

        self.assertEqual(identity.profile, {"id": "huahuo:19"})
        self.assertEqual(identity.workspaces, {"data": [{"id": "huahuo-front", "current": True}]})
        self.assertEqual(requests[0][0:2], ("POST", "/api/login"))
        rendered = repr(identity)
        self.assertNotIn("huahuo-access", rendered)
        self.assertNotIn("huahuo-refresh", rendered)
        self.assertNotIn("login-password", rendered)

    @unittest.skipIf(httpx is None, "httpx is not installed")
    def test_huahuo_password_authenticator_rejects_login_failure(self):
        def handler(request):
            return httpx.Response(200, json={"status": 0, "message": "bad login"})

        auth = HuahuoPasswordAuthenticator(
            "https://www.huahuoai.com",
            transport=httpx.MockTransport(handler),
        )

        with self.assertRaises(OpenClawAuthenticationError):
            auth.authenticate("phone-login", "wrong-password")

    def test_composite_authenticator_tries_next_provider_after_login_failure(self):
        class FailingAuthenticator:
            def authenticate(self, account, password):
                raise OpenClawAuthenticationError("login failed")

        class PassingAuthenticator:
            def authenticate(self, account, password):
                return OpenClawPasswordIdentity(
                    profile={"id": "account-b"},
                    workspaces={"data": [{"id": "tenant-b", "current": True}]},
                )

        auth = CompositeOpenClawAuthenticator(FailingAuthenticator(), PassingAuthenticator())

        identity = auth.authenticate("account", "password")

        self.assertEqual(identity.profile, {"id": "account-b"})


if __name__ == "__main__":
    unittest.main()
