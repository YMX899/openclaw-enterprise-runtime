import os
# Tests assume "new session has no messages" baseline; the production greeting
# injection is enabled separately via env var or create_app(inject_session_greeting=True).
os.environ.setdefault("BRIDGE_INJECT_SESSION_GREETING", "0")
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - exercised when optional deps are absent
    TestClient = None

from openclaw_video.job_store import InMemoryJobStore
from openclaw_video.identity import hmac_sha256_hex
from openclaw_video.openclaw_gateway import GatewayChatResult
from openclaw_video.session_store import InMemorySessionStore


class FakeDifyClient:
    async def profile(self, headers):
        account_id = headers.get("x-test-account")
        if not account_id:
            raise PermissionError("login required")
        return {"id": account_id}

    async def workspaces(self, headers):
        tenant_id = headers.get("x-test-tenant", "tenant-a")
        if headers.get("x-test-multiple-current") == "1":
            return {"data": [{"id": tenant_id, "current": True}, {"id": "tenant-b", "current": True}]}
        return {"data": [{"id": tenant_id, "current": True}]}


class DenyingDifyClient:
    async def profile(self, headers):
        raise PermissionError("login required")

    async def workspaces(self, headers):
        return {"data": []}


class FakeHuahuoClient:
    async def profile(self, headers):
        token = headers.get("x-huahuo-access-token") or headers.get("cookie")
        if not token:
            raise PermissionError("login required")
        return {"id": "huahuo:front-user-a"}

    async def workspaces(self, headers):
        return {"data": [{"id": "huahuo-front", "current": True}]}

    async def safe_identity_probe(self, headers):
        return {
            "provider": "huahuo_front",
            "identity_headers_present": bool(headers.get("x-huahuo-access-token") or headers.get("cookie")),
            "profile_http_status": 200,
            "profile_business_status": 1,
            "profile_data_keys": ["id", "loginName"],
            "refresh_attempted": False,
            "refresh_http_status": None,
            "refresh_business_status": None,
            "refresh_issued_access_token": False,
            "retry_http_status": None,
            "retry_business_status": None,
            "retry_data_keys": [],
            "error_stage": None,
        }


class FailingProbeHuahuoClient:
    async def profile(self, headers):
        raise PermissionError("login required")

    async def workspaces(self, headers):
        return {"data": [{"id": "huahuo-front", "current": True}]}

    async def safe_identity_probe(self, headers):
        return {
            "provider": "huahuo_front",
            "identity_headers_present": bool(headers.get("x-huahuo-access-token")),
            "profile_http_status": 200,
            "profile_business_status": 401,
            "profile_data_keys": [],
            "refresh_attempted": True,
            "refresh_http_status": 200,
            "refresh_business_status": 0,
            "refresh_issued_access_token": False,
            "retry_http_status": None,
            "retry_business_status": None,
            "retry_data_keys": [],
            "error_stage": "refresh_payload",
        }


class RefreshingDifyClient:
    async def resolve_identity(self, headers):
        from openclaw_video.dify_client import DifyIdentityContext

        return DifyIdentityContext(
            profile={"id": "account-a"},
            workspaces={"data": [{"id": "tenant-a", "current": True}]},
            set_cookie_headers=(
                "access_token=fresh-access; Path=/; HttpOnly",
                "refresh_token=fresh-refresh; Path=/; HttpOnly",
            ),
            refreshed=True,
        )

    async def safe_identity_probe(self, headers):
        return {
            "provider": "dify",
            "identity_headers_present": True,
            "cookie_names": ["refresh_token"],
            "authorization_present": False,
            "authorization_generated_from_cookie": False,
            "csrf_header_present": False,
            "profile_http_status": 401,
            "profile_body_keys": [],
            "workspaces_http_status": 401,
            "workspaces_body_keys": [],
            "refresh_attempted": True,
            "refresh_http_status": 200,
            "refresh_set_cookie_names": ["access_token", "refresh_token"],
            "retry_profile_http_status": 200,
            "retry_profile_body_keys": ["id"],
            "retry_workspaces_http_status": 200,
            "retry_workspaces_body_keys": ["data"],
            "error_stage": None,
        }


class FakeOpenClawAuthenticator:
    def __init__(self):
        self.calls = []

    def authenticate(self, account, password):
        from openclaw_video.openclaw_auth import OpenClawAuthenticationError, OpenClawPasswordIdentity

        self.calls.append((account, password))
        if account != "login-account" or password != "login-password":
            raise OpenClawAuthenticationError("login failed")
        return OpenClawPasswordIdentity(
            profile={"id": "account-a"},
            workspaces={"data": [{"id": "tenant-a", "current": True}]},
        )


class FakeGateway:
    def __init__(self):
        self.requests = []

    async def chat(self, request):
        self.requests.append(request)
        # Extract original user message (persona prefix is stripped for predictable reply).
        user_part = request.content.split("用户消息：")[-1].strip() if "用户消息：" in request.content else request.content
        content = f"reply to {user_part}"
        return GatewayChatResult(content=content, raw={"content": content})


def video_link_read_check_fixture():
    return {
        "schema_version": "openclaw-video-link-read-check.v1",
        "status": "PASS",
        "checked_at": "2026-06-07T00:00:00+00:00",
        "input_url_sha256": "a" * 64,
        "canonical_url_sha256": "b" * 64,
        "source_url_sha256": None,
        "share_url_sha256": None,
        "canonical_host": "www.douyin.com",
        "redirect_hop_count": 1,
        "redirect_chain_hosts": ["v.douyin.com", "www.douyin.com"],
        "resolved_ip_count": 1,
        "resolver": "douyin_chong.UniversalVideoResolver",
        "video_id_present": True,
        "video_id_sha256": "c" * 64,
        "direct_video_candidate_count": 2,
        "direct_video_host": "v3-dy-o.zjcdn.com",
        "playwm_host": "v26-dy.ixigua.com",
        "content_type_present": True,
        "content_type": "video/mp4",
        "duration_seconds": 12.345,
        "size_bytes": 2_621_440,
        "video_url_source": "direct",
        "limits": {
            "max_duration_seconds": 60,
            "max_download_bytes": 512 * 1024 * 1024,
            "duration_known": True,
            "size_known": True,
            "duration_ok": True,
            "size_ok": True,
            "eligible_for_model_analysis": True,
        },
        "elapsed_ms": 123,
        "raw_url_recorded": False,
        "direct_video_url_recorded": False,
        "cookies_recorded": False,
        "headers_recorded": False,
        "tokens_recorded": False,
        "model_invoked": False,
    }


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class BridgeAppTests(unittest.TestCase):
    def setUp(self):
        from openclaw_video.bridge_app import create_app

        self.sessions = InMemorySessionStore()
        self.jobs = InMemoryJobStore()
        self.env_patch = mock.patch.dict(
            os.environ,
            {"BRIDGE_ENABLE_TEST_IDENTITY_HEADERS": "1", "BRIDGE_TEST_IDENTITY_SECRET": "test-mode-secret"},
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client = TestClient(
            create_app(
                dify=FakeDifyClient(),
                session_store=self.sessions,
                job_store=self.jobs,
                identity_secret="test-secret",
            )
        )

    def auth(self, account="account-a", tenant="tenant-a"):
        return {
            "x-openclaw-test-identity-secret": "test-mode-secret",
            "x-test-account": account,
            "x-test-tenant": tenant,
        }

    def create_session(self, account="account-a", tenant="tenant-a"):
        response = self.client.post(
            "/openclaw-api/sessions",
            json={"title": "Video analysis"},
            headers=self.auth(account, tenant),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["session"]

    def test_healthz_does_not_require_login(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["component"], "openclaw-bridge")
        self.assertNotIn("token", response.text.lower())
        self.assertNotIn("cookie", response.text.lower())

    def test_create_session_message_persists_video_url_without_job(self):
        session = self.create_session()
        response = self.client.post(
            f"/openclaw-api/sessions/{session['id']}/messages",
            json={
                "role": "user",
                "content": "请分析这个视频。\nhttps://b23.tv/ieNCg9V",
                "video_url": "https://b23.tv/ieNCg9V",
            },
            headers=self.auth(),
        )
        self.assertEqual(response.status_code, 201, response.text)
        message = response.json()["message"]
        self.assertEqual(message["role"], "user")
        self.assertEqual(message["video_url"], "https://b23.tv/ieNCg9V")
        self.assertIsNone(message["job_id"])
        self.assertTrue(message["created_at"])
        messages = self.client.get(
            f"/openclaw-api/sessions/{session['id']}/messages",
            headers=self.auth(),
        )
        self.assertEqual(messages.status_code, 200, messages.text)
        self.assertEqual(messages.json()["messages"][0]["video_url"], "https://b23.tv/ieNCg9V")
        self.assertEqual(self.jobs.count_active_jobs(self.sessions.get_session(session["id"]).owner_principal_id), 0)

    def test_create_session_message_requires_owner_and_user_role(self):
        session = self.create_session(account="account-a")
        cross_user = self.client.post(
            f"/openclaw-api/sessions/{session['id']}/messages",
            json={"role": "user", "content": "hello"},
            headers=self.auth("account-b"),
        )
        self.assertEqual(cross_user.status_code, 404)
        assistant = self.client.post(
            f"/openclaw-api/sessions/{session['id']}/messages",
            json={"role": "assistant", "content": "not allowed"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(assistant.status_code, 400)

    def _lab_shell_and_bundle(self, base):
        shell = self.client.get(base + "/openclaw-lab/")
        self.assertEqual(shell.status_code, 200, shell.text)
        import re as _re
        m = _re.search(r'src="\./(assets/[^"]+\.js)"', shell.text)
        self.assertIsNotNone(m, "built JS asset not referenced in shell")
        bundle = self.client.get(base + "/openclaw-lab/" + m.group(1))
        self.assertEqual(bundle.status_code, 200, "bundle asset must be served")
        return shell, bundle.text

    def test_openclaw_lab_page_is_served_without_gateway_secret_surface(self):
        shell, bundle = self._lab_shell_and_bundle("")
        self.assertIn("text/html", shell.headers["content-type"])
        # productized shell markup + automation selectors (served HTML)
        for s in [
            "OpenClaw 短视频智能分析", "让短视频链接直接进入可追踪的分析对话",
            'id="openLogin"', 'id="landingPage"', 'id="chatApp"', 'id="sessionList"',
            'id="prompt"', 'id="output"', "登录后进入分析对话", "无需再登录 Dify 网页",
            "历史对话", "新建对话", "诊断与结果明细", "视频分析", "开发详情：脱敏响应", "验证工具",
        ]:
            with self.subTest(shell=s):
                self.assertIn(s, shell.text)
        # productized JS string literals survive bundling (Chinese UI + security self-test scenarios + API path segments)
        for s in [
            "读取链接", "视频链接读取", "未调用模型", "自检", "安全检查", "登录后验收",
            "security_test", "post_login_acceptance", "non_allowlisted_domain",
            "localhost_blocked", "cloud_metadata_blocked", "random_job_404",
            "tiny_upload_terminal", "messages_visible_to_owner",
            "https://example.com/not-douyin", "169.254.169.254",
            "/chat", "/sessions", "/auth/login", "/me", "/jobs", "/uploads",
            "/video-link/read-check", "/identity/diagnostics",
        ]:
            with self.subTest(bundle=s):
                self.assertIn(s, bundle)
        # no gateway / browser-storage secret surface in either the shell or the bundle
        for forbidden in ["localStorage", "OPENCLAW_GATEWAY_TOKEN", "openclaw-gateway:18789", "Authorization", "Cookie", "HUAHUO-access"]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, shell.text)
                self.assertNotIn(forbidden, bundle)
    def test_openclaw_lab_without_trailing_slash_is_served(self):
        response = self.client.get("/openclaw-lab")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("OpenClaw 短视频智能分析", response.text)

    def test_ai_scoped_openclaw_lab_uses_ai_api_prefix_without_secret_surface(self):
        shell, bundle = self._lab_shell_and_bundle("/ai")
        self.assertIn("OpenClaw 短视频智能分析", shell.text)
        self.assertIn("登录后进入分析对话", shell.text)
        # the api-prefix literals live in the bundle (ascii string literals survive minification)
        self.assertIn("/api/openclaw-api", bundle)
        self.assertIn("/console/api/openclaw-api", bundle)
        self.assertIn("/openclaw-api", bundle)
        for forbidden in ["localStorage", "OPENCLAW_GATEWAY_TOKEN", "Authorization", "Cookie"]:
            self.assertNotIn(forbidden, shell.text)
            self.assertNotIn(forbidden, bundle)
    def test_me_does_not_expose_raw_dify_ids(self):
        response = self.client.get("/openclaw-api/me", headers=self.auth())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], True)
        self.assertIn("principal_id", body)
        self.assertIn("versions", body)
        self.assertEqual(body["versions"]["result_schema_version"], "openclaw-video-result.v1")
        self.assertEqual(body["versions"]["openclaw_version"], "2026.3.13")
        self.assertIn("limits", body)
        self.assertIn("access", body)
        self.assertNotIn("tenant_id", body)
        self.assertNotIn("account_id", body)
        self.assertNotIn("tenant-a", response.text)
        self.assertNotIn("account-a", response.text)

    def test_login_required_for_me(self):
        response = self.client.get("/openclaw-api/me")
        self.assertEqual(response.status_code, 401)

    def test_prefs_roundtrip_and_owner_isolation(self):
        self.assertEqual(self.client.get("/openclaw-api/prefs").status_code, 401)
        self.assertEqual(self.client.get("/openclaw-api/prefs", headers=self.auth("account-a")).json()["prefs"], {})
        put = self.client.put(
            "/openclaw-api/prefs",
            json={"prefs": {"theme": "dark", "sessions": {"s1": {"title": "改名"}}}},
            headers=self.auth("account-a"),
        )
        self.assertEqual(put.status_code, 200, put.text)
        got = self.client.get("/openclaw-api/prefs", headers=self.auth("account-a")).json()["prefs"]
        self.assertEqual(got["theme"], "dark")
        self.assertEqual(got["sessions"]["s1"]["title"], "改名")
        self.assertEqual(self.client.get("/openclaw-api/prefs", headers=self.auth("account-b")).json()["prefs"], {})
        self.assertEqual(
            self.client.put("/openclaw-api/prefs", json={"prefs": "nope"}, headers=self.auth("account-a")).status_code,
            400,
        )

    def test_dify_cookie_or_header_does_not_bypass_openclaw_login_by_default(self):
        from openclaw_video.bridge_app import create_app

        client = TestClient(
            create_app(
                dify=FakeDifyClient(),
                session_store=InMemorySessionStore(),
                job_store=InMemoryJobStore(),
                identity_secret="test-secret",
            )
        )

        response = client.get(
            "/openclaw-api/me",
            headers={
                "x-test-account": "account-a",
                "x-test-tenant": "tenant-a",
                "Authorization": "Bearer dify-web-token",
                "Cookie": "access_token=dify-web-token",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("dify-web-token", response.text)

    def test_identity_diagnostics_reports_missing_login_without_secrets(self):
        response = self.client.get("/openclaw-api/identity/diagnostics")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], False)
        self.assertEqual(body["login_material_present"], False)
        self.assertEqual(body["openclaw_session_present"], False)
        self.assertIsNone(body["auth_mode"])
        self.assertEqual(body["huahuo_access_token_present"], False)
        self.assertEqual(body["huahuo_app_uuid_present"], False)
        self.assertEqual(body["profile_ok"], False)
        self.assertEqual(body["workspace_ok"], False)
        self.assertEqual(body["access_ok"], False)
        self.assertEqual(body["failure_stage"], "profile")
        self.assertIsNone(body["principal_id"])
        self.assertNotIn("cookie", response.text.lower())
        self.assertNotIn("authorization", response.text.lower())

    def test_identity_diagnostics_returns_hashed_principal_only(self):
        response = self.client.get(
            "/openclaw-api/identity/diagnostics",
            headers={**self.auth("account-a", "tenant-a"), "Cookie": "dify=secret"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], True)
        self.assertEqual(body["login_material_present"], True)
        self.assertEqual(body["openclaw_session_present"], False)
        self.assertEqual(body["auth_mode"], "test_identity_headers")
        self.assertEqual(body["huahuo_access_token_present"], False)
        self.assertEqual(body["huahuo_app_uuid_present"], False)
        self.assertEqual(body["profile_ok"], True)
        self.assertEqual(body["workspace_ok"], True)
        self.assertEqual(body["access_ok"], True)
        self.assertEqual(body["current_workspace_count"], 1)
        self.assertEqual(len(body["principal_id"]), 64)
        self.assertIsNone(body["failure_stage"])
        self.assertNotIn("account-a", response.text)
        self.assertNotIn("tenant-a", response.text)
        self.assertNotIn("secret", response.text)

    def test_identity_diagnostics_fails_closed_for_multiple_current_workspaces(self):
        response = self.client.get(
            "/openclaw-api/identity/diagnostics",
            headers={**self.auth("account-a", "tenant-a"), "x-test-multiple-current": "1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], False)
        self.assertEqual(body["profile_ok"], True)
        self.assertEqual(body["workspace_ok"], False)
        self.assertEqual(body["access_ok"], False)
        self.assertEqual(body["current_workspace_count"], 2)
        self.assertEqual(body["failure_stage"], "workspace")
        self.assertIsNone(body["principal_id"])

    def test_runtime_test_identity_headers_are_disabled_by_default(self):
        from openclaw_video.bridge_app import create_app

        with mock.patch.dict(os.environ, {}, clear=True):
            client = TestClient(
                create_app(
                    dify=DenyingDifyClient(),
                    session_store=InMemorySessionStore(),
                    job_store=InMemoryJobStore(),
                    identity_secret="test-secret",
                )
            )
        response = client.get(
            "/openclaw-api/identity/diagnostics",
            headers={
                "x-test-account": "account-a",
                "x-test-tenant": "tenant-a",
                "x-openclaw-test-identity-secret": "test-mode-secret",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["authenticated"], False)
        self.assertEqual(body["failure_stage"], "profile")

    def test_runtime_test_identity_headers_require_matching_secret(self):
        from openclaw_video.bridge_app import create_app

        with mock.patch.dict(
            os.environ,
            {"BRIDGE_ENABLE_TEST_IDENTITY_HEADERS": "1", "BRIDGE_TEST_IDENTITY_SECRET": "test-mode-secret"},
        ):
            client = TestClient(
                create_app(
                    dify=DenyingDifyClient(),
                    session_store=InMemorySessionStore(),
                    job_store=InMemoryJobStore(),
                    identity_secret="test-secret",
                )
            )
        response = client.get("/openclaw-api/identity/diagnostics", headers={"x-test-account": "account-a"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["authenticated"], False)

        response = client.get(
            "/openclaw-api/identity/diagnostics",
            headers={
                "x-test-account": "account-a",
                "x-test-tenant": "tenant-a",
                "x-openclaw-test-identity-secret": "wrong-secret",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["authenticated"], False)

        response = client.get(
            "/openclaw-api/identity/diagnostics",
            headers={
                "x-test-account": "account-a",
                "x-test-tenant": "tenant-a",
                "x-openclaw-test-identity-secret": "test-mode-secret",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], True)
        self.assertEqual(body["profile_ok"], True)
        self.assertEqual(body["workspace_ok"], True)
        self.assertEqual(body["access_ok"], True)
        self.assertEqual(body["auth_mode"], "test_identity_headers")
        self.assertEqual(len(body["principal_id"]), 64)
        self.assertNotIn("account-a", response.text)
        self.assertNotIn("tenant-a", response.text)
        self.assertNotIn("test-mode-secret", response.text)

    def test_openclaw_password_login_sets_http_only_session_cookie(self):
        from openclaw_video.bridge_app import create_app

        authenticator = FakeOpenClawAuthenticator()
        client = TestClient(
            create_app(
                dify=DenyingDifyClient(),
                session_store=InMemorySessionStore(),
                job_store=InMemoryJobStore(),
                openclaw_authenticator=authenticator,
                identity_secret="test-secret",
            )
        )
        login = client.post(
            "/openclaw-api/auth/login",
            json={"account": "login-account", "password": "login-password"},
            headers={"x-forwarded-proto": "https"},
        )

        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(login.json()["authenticated"], True)
        self.assertEqual(len(login.json()["principal_id"]), 64)
        set_cookie = login.headers.get("set-cookie", "")
        self.assertIn("openclaw_session=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("Secure", set_cookie)
        self.assertIn("SameSite=lax", set_cookie)
        self.assertNotIn("login-password", login.text)
        self.assertNotIn("login-account", login.text)

        client = TestClient(
            create_app(
                dify=DenyingDifyClient(),
                session_store=InMemorySessionStore(),
                job_store=InMemoryJobStore(),
                openclaw_authenticator=authenticator,
                identity_secret="test-secret",
            )
        )
        login = client.post(
            "/openclaw-api/auth/login",
            json={"account": "login-account", "password": "login-password"},
        )
        self.assertEqual(login.status_code, 200, login.text)

        me = client.get("/openclaw-api/me")
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["authenticated"], True)
        diagnostics = client.get("/openclaw-api/identity/diagnostics")
        self.assertEqual(diagnostics.status_code, 200, diagnostics.text)
        body = diagnostics.json()
        self.assertEqual(body["authenticated"], True)
        self.assertEqual(body["openclaw_session_present"], True)
        self.assertEqual(body["auth_mode"], "openclaw_session")
        self.assertIsNone(body["provider_probe"])
        self.assertNotIn("account-a", diagnostics.text)
        self.assertNotIn("tenant-a", diagnostics.text)

    def test_openclaw_password_login_failure_does_not_create_session_or_echo_values(self):
        from openclaw_video.bridge_app import create_app

        client = TestClient(
            create_app(
                dify=DenyingDifyClient(),
                session_store=InMemorySessionStore(),
                job_store=InMemoryJobStore(),
                openclaw_authenticator=FakeOpenClawAuthenticator(),
                identity_secret="test-secret",
            )
        )
        response = client.post(
            "/openclaw-api/auth/login",
            json={"account": "login-account", "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("openclaw_session=", response.headers.get("set-cookie", ""))
        self.assertNotIn("login-account", response.text)
        self.assertNotIn("wrong-password", response.text)
        me = client.get("/openclaw-api/me")
        self.assertEqual(me.status_code, 401)

    def test_openclaw_logout_clears_session_cookie(self):
        from openclaw_video.bridge_app import create_app

        client = TestClient(
            create_app(
                dify=DenyingDifyClient(),
                session_store=InMemorySessionStore(),
                job_store=InMemoryJobStore(),
                openclaw_authenticator=FakeOpenClawAuthenticator(),
                identity_secret="test-secret",
            )
        )
        login = client.post(
            "/openclaw-api/auth/login",
            json={"account": "login-account", "password": "login-password"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(client.get("/openclaw-api/me").status_code, 200)

        logout = client.post("/openclaw-api/auth/logout", json={})
        self.assertEqual(logout.status_code, 200, logout.text)
        self.assertIn("openclaw_session=", logout.headers.get("set-cookie", ""))
        self.assertEqual(client.get("/openclaw-api/me").status_code, 401)

    def test_huahuo_front_identity_provider_accepts_frontend_token_without_raw_ids(self):
        from openclaw_video.bridge_app import create_app

        with mock.patch.dict(os.environ, {"OPENCLAW_ENABLE_DIFY_PROVIDER_IDENTITY": "1"}):
            client = TestClient(
                create_app(
                    dify=FakeHuahuoClient(),
                    session_store=InMemorySessionStore(),
                    job_store=InMemoryJobStore(),
                    identity_secret="test-secret",
                )
            )
        response = client.get("/openclaw-api/me", headers={"X-Huahuo-Access-Token": "HUAHUO-access"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], True)
        self.assertEqual(len(body["principal_id"]), 64)
        self.assertNotIn("front-user-a", response.text)
        self.assertNotIn("huahuo-front", response.text)
        self.assertNotIn("HUAHUO-access", response.text)

    def test_huahuo_identity_diagnostics_reports_presence_without_values(self):
        from openclaw_video.bridge_app import create_app

        with mock.patch.dict(os.environ, {"OPENCLAW_ENABLE_DIFY_PROVIDER_IDENTITY": "1"}):
            client = TestClient(
                create_app(
                    dify=FakeHuahuoClient(),
                    session_store=InMemorySessionStore(),
                    job_store=InMemoryJobStore(),
                    identity_secret="test-secret",
                )
            )
        response = client.get(
            "/openclaw-api/identity/diagnostics",
            headers={
                "X-Huahuo-Access-Token": "HUAHUO-access",
                "X-Huahuo-App-UUID": "front-app-uuid",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], True)
        self.assertEqual(body["huahuo_access_token_present"], True)
        self.assertEqual(body["huahuo_app_uuid_present"], True)
        self.assertEqual(body["provider_probe"]["provider"], "huahuo_front")
        self.assertEqual(body["provider_probe"]["profile_data_keys"], ["id", "loginName"])
        self.assertNotIn("HUAHUO-access", response.text)
        self.assertNotIn("front-app-uuid", response.text)
        self.assertNotIn("accessToken", response.text)
        self.assertNotIn("refreshToken", response.text)

    def test_huahuo_identity_diagnostics_accepts_cookie_only_without_echoing_cookie(self):
        from openclaw_video.bridge_app import create_app

        with mock.patch.dict(os.environ, {"OPENCLAW_ENABLE_DIFY_PROVIDER_IDENTITY": "1"}):
            client = TestClient(
                create_app(
                    dify=FakeHuahuoClient(),
                    session_store=InMemorySessionStore(),
                    job_store=InMemoryJobStore(),
                    identity_secret="test-secret",
                )
            )
        response = client.get("/openclaw-api/identity/diagnostics", headers={"Cookie": "huahuo_session=secret"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], True)
        self.assertEqual(body["login_material_present"], True)
        self.assertEqual(body["huahuo_access_token_present"], False)
        self.assertEqual(body["provider_probe"]["identity_headers_present"], True)
        self.assertNotIn("huahuo_session=secret", response.text)
        self.assertNotIn("Cookie", response.text)

    def test_ai_scoped_api_alias_uses_same_auth_and_response_shape(self):
        response = self.client.get("/ai/openclaw-api/me", headers=self.auth())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], True)
        self.assertEqual(len(body["principal_id"]), 64)
        self.assertNotIn("account-a", response.text)
        self.assertNotIn("tenant-a", response.text)

    def test_api_scoped_api_alias_uses_same_auth_and_response_shape(self):
        response = self.client.get("/api/openclaw-api/me", headers=self.auth())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], True)
        self.assertEqual(len(body["principal_id"]), 64)
        self.assertNotIn("account-a", response.text)
        self.assertNotIn("tenant-a", response.text)

    def test_console_api_scoped_alias_uses_same_auth_and_response_shape(self):
        response = self.client.get("/console/api/openclaw-api/me", headers=self.auth())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], True)
        self.assertEqual(len(body["principal_id"]), 64)
        self.assertNotIn("account-a", response.text)
        self.assertNotIn("tenant-a", response.text)

    def test_dify_refresh_cookies_are_forwarded_without_echoing_values(self):
        from openclaw_video.bridge_app import create_app

        with mock.patch.dict(os.environ, {"OPENCLAW_ENABLE_DIFY_PROVIDER_IDENTITY": "1"}):
            client = TestClient(
                create_app(
                    dify=RefreshingDifyClient(),
                    session_store=InMemorySessionStore(),
                    job_store=InMemoryJobStore(),
                    identity_secret="test-secret",
                )
            )
        response = client.get(
            "/console/api/openclaw-api/me",
            headers={"Cookie": "refresh_token=stale-refresh"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["authenticated"], True)
        set_cookie = response.headers.get("set-cookie", "")
        self.assertIn("access_token=fresh-access", set_cookie)
        self.assertIn("refresh_token=fresh-refresh", set_cookie)
        self.assertNotIn("fresh-access", response.text)
        self.assertNotIn("fresh-refresh", response.text)
        self.assertNotIn("stale-refresh", response.text)

    def test_identity_diagnostics_can_resolve_after_dify_refresh(self):
        from openclaw_video.bridge_app import create_app

        with mock.patch.dict(os.environ, {"OPENCLAW_ENABLE_DIFY_PROVIDER_IDENTITY": "1"}):
            client = TestClient(
                create_app(
                    dify=RefreshingDifyClient(),
                    session_store=InMemorySessionStore(),
                    job_store=InMemoryJobStore(),
                    identity_secret="test-secret",
                )
            )
        response = client.get(
            "/console/api/openclaw-api/identity/diagnostics",
            headers={"Cookie": "refresh_token=stale-refresh"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], True)
        self.assertEqual(body["profile_ok"], True)
        self.assertEqual(body["workspace_ok"], True)
        self.assertEqual(body["provider_probe"]["refresh_attempted"], True)
        self.assertNotIn("fresh-access", response.text)
        self.assertNotIn("fresh-refresh", response.text)
        self.assertNotIn("stale-refresh", response.text)

    def test_huahuo_identity_diagnostics_probe_is_safe_when_profile_fails(self):
        from openclaw_video.bridge_app import create_app

        with mock.patch.dict(os.environ, {"OPENCLAW_ENABLE_DIFY_PROVIDER_IDENTITY": "1"}):
            client = TestClient(
                create_app(
                    dify=FailingProbeHuahuoClient(),
                    session_store=InMemorySessionStore(),
                    job_store=InMemoryJobStore(),
                    identity_secret="test-secret",
                )
            )
        response = client.get(
            "/openclaw-api/identity/diagnostics",
            headers={
                "X-Huahuo-Access-Token": "HUAHUO-access",
                "X-Huahuo-App-UUID": "front-app-uuid",
                "X-Huahuo-Refresh-Token": "refresh-secret",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], False)
        self.assertEqual(body["failure_stage"], "profile")
        self.assertEqual(body["provider_probe"]["refresh_attempted"], True)
        self.assertEqual(body["provider_probe"]["error_stage"], "refresh_payload")
        self.assertNotIn("HUAHUO-access", response.text)
        self.assertNotIn("front-app-uuid", response.text)
        self.assertNotIn("refresh-secret", response.text)
        self.assertNotIn("Authorization", response.text)
        self.assertNotIn("Cookie", response.text)

    def test_create_and_list_sessions_for_owner_only(self):
        session_a = self.create_session("account-a")
        self.create_session("account-b")
        response = self.client.get("/openclaw-api/sessions", headers=self.auth("account-a"))
        self.assertEqual(response.status_code, 200, response.text)
        sessions = response.json()["sessions"]
        self.assertEqual([item["id"] for item in sessions], [session_a["id"]])

    def test_create_job_returns_202_and_owner_can_read(self):
        session = self.create_session("account-a")
        response = self.client.post(
            "/openclaw-api/jobs",
            json={
                "session_id": session["id"],
                "video_url": "https://v.douyin.com/abc",
                "content": "analyze this",
            },
            headers=self.auth("account-a"),
        )
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()["job"]
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["session_id"], session["id"])
        read_response = self.client.get(f"/openclaw-api/jobs/{job['job_id']}", headers=self.auth("account-a"))
        self.assertEqual(read_response.status_code, 200, read_response.text)
        self.assertEqual(read_response.json()["job"]["job_id"], job["job_id"])

    def test_video_link_read_check_requires_login_and_does_not_create_job(self):
        fixture = video_link_read_check_fixture()
        raw_url = "https://v.douyin.com/abc"
        with mock.patch("openclaw_video.bridge_app.probe_video_link", return_value=fixture) as probe:
            unauthenticated = self.client.post(
                "/openclaw-api/video-link/read-check",
                json={"video_url": raw_url},
            )
            self.assertEqual(unauthenticated.status_code, 401)
            self.assertEqual(probe.call_count, 0)

            response = self.client.post(
                "/openclaw-api/video-link/read-check",
                json={"video_url": raw_url},
                headers=self.auth("account-a"),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), fixture)
        self.assertEqual(len(self.jobs._jobs), 0)
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(probe.call_args.args[0], raw_url)
        self.assertFalse(response.json()["model_invoked"])
        self.assertFalse(response.json()["raw_url_recorded"])
        self.assertFalse(response.json()["direct_video_url_recorded"])
        self.assertNotIn(raw_url, response.text)
        self.assertNotIn("token=", response.text)

    def test_video_link_read_check_validates_body_and_sanitizes_failures(self):
        from openclaw_video.url_guard import UrlRejected
        from openclaw_video.video_link_probe import VideoLinkProbeError

        missing = self.client.post(
            "/openclaw-api/video-link/read-check",
            json={},
            headers=self.auth("account-a"),
        )
        self.assertEqual(missing.status_code, 400)
        self.assertIn("video_url is required", missing.text)

        raw_url = "https://v.douyin.com/abc?secret=value"
        with mock.patch(
            "openclaw_video.bridge_app.probe_video_link",
            side_effect=UrlRejected("host is not in the Douyin allowlist"),
        ):
            rejected = self.client.post(
                "/openclaw-api/video-link/read-check",
                json={"video_url": raw_url},
                headers=self.auth("account-a"),
            )
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertIn("host is not in the Douyin allowlist", rejected.text)
        self.assertNotIn(raw_url, rejected.text)
        self.assertNotIn("secret=value", rejected.text)

        with mock.patch(
            "openclaw_video.bridge_app.probe_video_link",
            side_effect=VideoLinkProbeError("douyin_chong resolver failed"),
        ):
            failed = self.client.post(
                "/openclaw-api/video-link/read-check",
                json={"video_url": raw_url},
                headers=self.auth("account-a"),
            )
        self.assertEqual(failed.status_code, 502, failed.text)
        self.assertIn("douyin_chong resolver failed", failed.text)
        self.assertNotIn(raw_url, failed.text)

    def test_upload_job_returns_202_and_records_private_upload_uri(self):
        session = self.create_session("account-a")
        with TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"BRIDGE_UPLOAD_DIR": tmp, "MAX_UPLOAD_BYTES": "64"},
        ):
            response = self.client.post(
                "/openclaw-api/uploads",
                data={"session_id": session["id"], "content": "analyze upload"},
                files={"video": ("sample clip.mp4", b"video bytes", "video/mp4")},
                headers=self.auth("account-a"),
            )
            self.assertEqual(response.status_code, 202, response.text)
            body = response.json()
            job = body["job"]
            upload = body["upload"]
            self.assertEqual(job["status"], "queued")
            self.assertEqual(job["session_id"], session["id"])
            self.assertTrue(job["video_url_canonical"].startswith("upload://"))
            self.assertEqual(upload["filename"], "sample_clip.mp4")
            self.assertEqual(upload["size_bytes"], len(b"video bytes"))
            self.assertEqual(len(upload["sha256"]), 64)
            self.assertTrue((Path(tmp) / job["video_url_canonical"].split("/", 3)[2] / upload["filename"]).is_file())

        messages = self.client.get(
            f"/openclaw-api/sessions/{session['id']}/messages",
            headers=self.auth("account-a"),
        )
        self.assertEqual(messages.status_code, 200, messages.text)
        self.assertEqual(messages.json()["messages"][0]["video_url"], job["video_url_canonical"])

    def test_upload_job_requires_login_and_supported_extension(self):
        session = self.create_session("account-a")
        with TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"BRIDGE_UPLOAD_DIR": tmp}):
            unauthenticated = self.client.post(
                "/openclaw-api/uploads",
                data={"session_id": session["id"]},
                files={"video": ("sample.mp4", b"video", "video/mp4")},
            )
            self.assertEqual(unauthenticated.status_code, 401)

            invalid = self.client.post(
                "/openclaw-api/uploads",
                data={"session_id": session["id"]},
                files={"video": ("sample.txt", b"not video", "text/plain")},
                headers=self.auth("account-a"),
            )
            self.assertEqual(invalid.status_code, 400, invalid.text)
            self.assertIn("unsupported video file type", invalid.text)

            oversized = self.client.post(
                "/openclaw-api/uploads",
                data={"session_id": session["id"]},
                files={"video": ("sample.mp4", b"123456", "video/mp4")},
                headers=self.auth("account-a"),
            )
            self.assertEqual(oversized.status_code, 202, oversized.text)

        with TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"BRIDGE_UPLOAD_DIR": tmp, "MAX_UPLOAD_BYTES": "4"},
        ):
            too_big = self.client.post(
                "/openclaw-api/uploads",
                data={"session_id": session["id"]},
                files={"video": ("sample.mp4", b"123456", "video/mp4")},
                headers=self.auth("account-a"),
            )
            self.assertEqual(too_big.status_code, 400, too_big.text)
            self.assertIn("uploaded video exceeds size limit", too_big.text)

    def test_allowlist_uses_hashed_tenant_and_account_without_exposing_raw_ids(self):
        from openclaw_video.bridge_app import create_app

        tenant_hash = hmac_sha256_hex("test-secret", "tenant:tenant-a")
        account_hash = hmac_sha256_hex("test-secret", "account:account-a")
        with mock.patch.dict(
            os.environ,
            {
                "OPENCLAW_TENANT_ALLOWLIST_HASHES": tenant_hash,
                "OPENCLAW_ACCOUNT_ALLOWLIST_HASHES": account_hash,
            },
        ):
            client = TestClient(
                create_app(
                    dify=FakeDifyClient(),
                    session_store=InMemorySessionStore(),
                    job_store=InMemoryJobStore(),
                    identity_secret="test-secret",
                )
            )

        allowed = client.get("/openclaw-api/me", headers=self.auth("account-a", "tenant-a"))
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(allowed.json()["access"]["tenant_allowlist_enabled"], True)
        self.assertEqual(allowed.json()["access"]["account_allowlist_enabled"], True)
        self.assertNotIn("tenant-a", allowed.text)
        self.assertNotIn("account-a", allowed.text)

        wrong_tenant = client.get("/openclaw-api/me", headers=self.auth("account-a", "tenant-b"))
        self.assertEqual(wrong_tenant.status_code, 403)
        self.assertNotIn("tenant-b", wrong_tenant.text)
        self.assertNotIn("account-a", wrong_tenant.text)

        diagnostics = client.get(
            "/openclaw-api/identity/diagnostics",
            headers=self.auth("account-a", "tenant-b"),
        )
        self.assertEqual(diagnostics.status_code, 200, diagnostics.text)
        body = diagnostics.json()
        self.assertEqual(body["profile_ok"], True)
        self.assertEqual(body["workspace_ok"], True)
        self.assertEqual(body["access_ok"], False)
        self.assertEqual(body["failure_stage"], "access")
        self.assertIsNone(body["principal_id"])
        self.assertNotIn("tenant-b", diagnostics.text)
        self.assertNotIn("account-a", diagnostics.text)

    def test_job_submission_respects_active_job_limit(self):
        from openclaw_video.bridge_app import create_app

        with mock.patch.dict(os.environ, {"OPENCLAW_USER_ACTIVE_JOB_LIMIT": "1"}):
            jobs = InMemoryJobStore()
            client = TestClient(
                create_app(
                    dify=FakeDifyClient(),
                    session_store=InMemorySessionStore(),
                    job_store=jobs,
                    identity_secret="test-secret",
                )
            )
        session = client.post(
            "/openclaw-api/sessions",
            json={"title": "Video analysis"},
            headers=self.auth("account-a"),
        ).json()["session"]
        first = client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/one"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(first.status_code, 202, first.text)
        second = client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/two"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(second.status_code, 429)
        self.assertIn("active job limit exceeded", second.text)

        jobs.fail_job(first.json()["job"]["job_id"], "test_done")
        after_terminal = client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/three"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(after_terminal.status_code, 202, after_terminal.text)

    def test_idempotent_job_retry_returns_existing_job_before_active_limit(self):
        from openclaw_video.bridge_app import create_app

        with mock.patch.dict(os.environ, {"OPENCLAW_USER_ACTIVE_JOB_LIMIT": "1"}):
            client = TestClient(
                create_app(
                    dify=FakeDifyClient(),
                    session_store=InMemorySessionStore(),
                    job_store=InMemoryJobStore(),
                    identity_secret="test-secret",
                )
            )
        session = client.post(
            "/openclaw-api/sessions",
            json={"title": "Video analysis"},
            headers=self.auth("account-a"),
        ).json()["session"]
        payload = {
            "session_id": session["id"],
            "video_url": "https://v.douyin.com/one",
            "idempotency_key": "retry-safe",
        }
        first = client.post("/openclaw-api/jobs", json=payload, headers=self.auth("account-a"))
        self.assertEqual(first.status_code, 202, first.text)
        retry = client.post("/openclaw-api/jobs", json=payload, headers=self.auth("account-a"))
        self.assertEqual(retry.status_code, 202, retry.text)
        self.assertEqual(first.json()["job"]["job_id"], retry.json()["job"]["job_id"])
        messages = client.get(
            f"/openclaw-api/sessions/{session['id']}/messages",
            headers=self.auth("account-a"),
        )
        self.assertEqual(len(messages.json()["messages"]), 1)

    def test_upload_job_limit_rejects_before_storing_file(self):
        from openclaw_video.bridge_app import create_app

        with TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"OPENCLAW_USER_ACTIVE_JOB_LIMIT": "1", "BRIDGE_UPLOAD_DIR": tmp},
        ):
            client = TestClient(
                create_app(
                    dify=FakeDifyClient(),
                    session_store=InMemorySessionStore(),
                    job_store=InMemoryJobStore(),
                    identity_secret="test-secret",
                )
            )
            session = client.post(
                "/openclaw-api/sessions",
                json={"title": "Video analysis"},
                headers=self.auth("account-a"),
            ).json()["session"]
            first = client.post(
                "/openclaw-api/uploads",
                data={"session_id": session["id"], "content": "upload"},
                files={"video": ("first.mp4", b"video", "video/mp4")},
                headers=self.auth("account-a"),
            )
            self.assertEqual(first.status_code, 202, first.text)
            second = client.post(
                "/openclaw-api/uploads",
                data={"session_id": session["id"], "content": "upload"},
                files={"video": ("second.mp4", b"video", "video/mp4")},
                headers=self.auth("account-a"),
            )
            self.assertEqual(second.status_code, 429, second.text)
            stored_files = [item.name for item in Path(tmp).rglob("*.mp4")]
            self.assertEqual(stored_files, ["first.mp4"])

    def test_retention_cleanup_removes_expired_job_result_message_and_upload(self):
        from openclaw_video.bridge_app import create_app

        sessions = InMemorySessionStore()
        jobs = InMemoryJobStore()
        with TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "OPENCLAW_DATA_RETENTION_DAYS": "1",
                "BRIDGE_UPLOAD_DIR": tmp,
                "MAX_UPLOAD_BYTES": "64",
            },
        ):
            client = TestClient(
                create_app(
                    dify=FakeDifyClient(),
                    session_store=sessions,
                    job_store=jobs,
                    identity_secret="test-secret",
                )
            )
            session = client.post(
                "/openclaw-api/sessions",
                json={"title": "Video analysis"},
                headers=self.auth("account-a"),
            ).json()["session"]
            upload_response = client.post(
                "/openclaw-api/uploads",
                data={"session_id": session["id"], "content": "upload"},
                files={"video": ("old.mp4", b"video bytes", "video/mp4")},
                headers=self.auth("account-a"),
            )
            self.assertEqual(upload_response.status_code, 202, upload_response.text)
            job = upload_response.json()["job"]
            upload_path = Path(tmp) / job["video_url_canonical"].split("/", 3)[2] / "old.mp4"
            self.assertTrue(upload_path.is_file())
            jobs.complete_job(
                job["job_id"],
                {
                    "schema_version": "openclaw-video-result.v1",
                    "source": {"video_url_canonical": job["video_url_canonical"], "platform": "upload"},
                    "summary": "old",
                    "signals": {},
                    "raw_tool_result": {},
                    "created_at": "2026-06-06T00:00:00Z",
                },
                "openclaw-video-result.v1",
            )
            jobs.get_job(job["job_id"]).finished_at = datetime.now(UTC) - timedelta(days=2)

            cleanup = client.post("/openclaw-api/retention/cleanup", headers=self.auth("account-a"))

            self.assertEqual(cleanup.status_code, 200, cleanup.text)
            body = cleanup.json()
            self.assertEqual(body["status"], "ok")
            self.assertEqual(body["retention_days"], 1)
            self.assertEqual(body["deleted_jobs"], 1)
            self.assertEqual(body["deleted_results"], 1)
            self.assertEqual(body["deleted_messages"], 1)
            self.assertEqual(body["deleted_uploads"], 1)
            self.assertFalse(upload_path.exists())
            messages = client.get(
                f"/openclaw-api/sessions/{session['id']}/messages",
                headers=self.auth("account-a"),
            )
            self.assertEqual(messages.json()["messages"], [])
            read_job = client.get(f"/openclaw-api/jobs/{job['job_id']}", headers=self.auth("account-a"))
            self.assertEqual(read_job.status_code, 404)

    def test_job_submission_respects_per_user_rate_limit(self):
        from openclaw_video.bridge_app import create_app

        with mock.patch.dict(os.environ, {"OPENCLAW_USER_RATE_LIMIT_PER_MINUTE": "1"}):
            client = TestClient(
                create_app(
                    dify=FakeDifyClient(),
                    session_store=InMemorySessionStore(),
                    job_store=InMemoryJobStore(),
                    identity_secret="test-secret",
                )
            )
        session = client.post(
            "/openclaw-api/sessions",
            json={"title": "Video analysis"},
            headers=self.auth("account-a"),
        ).json()["session"]
        first = client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/one"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(first.status_code, 202, first.text)
        second = client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/two"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(second.status_code, 429)
        self.assertIn("job submission rate limit exceeded", second.text)

    def test_owner_can_read_result_and_cross_user_gets_404(self):
        session = self.create_session("account-a")
        job_response = self.client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/abc"},
            headers=self.auth("account-a"),
        )
        job_id = job_response.json()["job"]["job_id"]
        result = {
            "schema_version": "openclaw-video-result.v1",
            "source": {
                "video_url_canonical": "https://v.douyin.com/abc",
                "platform": "douyin",
                "duration_seconds": 1,
            },
            "summary": "ok",
            "signals": {"hook": "ok"},
            "raw_tool_result": {"ok": True},
            "created_at": "2026-06-06T00:00:00Z",
        }
        self.jobs.complete_job(job_id, result, "openclaw-video-result.v1")
        read = self.client.get(f"/openclaw-api/jobs/{job_id}/result", headers=self.auth("account-a"))
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["result"]["result"]["summary"], "ok")
        other = self.client.get(f"/openclaw-api/jobs/{job_id}/result", headers=self.auth("account-b"))
        self.assertEqual(other.status_code, 404)

    def test_job_events_stream_returns_current_job_snapshot(self):
        session = self.create_session("account-a")
        response = self.client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/abc"},
            headers=self.auth("account-a"),
        )
        job_id = response.json()["job"]["job_id"]
        self.jobs.complete_job(job_id, {"ok": True}, "schema")
        with self.client.stream(
            "GET",
            f"/openclaw-api/jobs/{job_id}/events",
            headers=self.auth("account-a"),
        ) as stream:
            self.assertEqual(stream.status_code, 200)
            self.assertEqual(stream.headers["content-type"].split(";")[0], "text/event-stream")
            body = "".join(stream.iter_text())
        self.assertIn("event: job", body)
        self.assertIn('"status":"succeeded"', body)
        self.assertIn("event: done", body)

    def test_cross_user_cannot_read_job_events(self):
        session = self.create_session("account-a")
        response = self.client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/abc"},
            headers=self.auth("account-a"),
        )
        job_id = response.json()["job"]["job_id"]
        stream = self.client.get(f"/openclaw-api/jobs/{job_id}/events", headers=self.auth("account-b"))
        self.assertEqual(stream.status_code, 404)

    def test_cross_user_cannot_read_session_messages_or_job(self):
        session = self.create_session("account-a")
        job_response = self.client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/abc"},
            headers=self.auth("account-a"),
        )
        job_id = job_response.json()["job"]["job_id"]
        messages = self.client.get(
            f"/openclaw-api/sessions/{session['id']}/messages",
            headers=self.auth("account-b"),
        )
        self.assertEqual(messages.status_code, 404)
        job = self.client.get(f"/openclaw-api/jobs/{job_id}", headers=self.auth("account-b"))
        self.assertEqual(job.status_code, 404)

    def test_tenant_switch_changes_principal_scope(self):
        session = self.create_session("account-a", "tenant-a")
        response = self.client.get(
            f"/openclaw-api/sessions/{session['id']}/messages",
            headers=self.auth("account-a", "tenant-b"),
        )
        self.assertEqual(response.status_code, 404)

    def test_chat_without_gateway_adapter_returns_501_without_writing_messages(self):
        session = self.create_session("account-a")
        response = self.client.post(
            "/openclaw-api/chat",
            json={"session_id": session["id"], "content": "hello"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(response.status_code, 501)
        messages = self.client.get(
            f"/openclaw-api/sessions/{session['id']}/messages",
            headers=self.auth("account-a"),
        )
        self.assertEqual(messages.status_code, 200, messages.text)
        self.assertEqual(messages.json()["messages"], [])

    def test_chat_gateway_adapter_gets_routing_user_not_dify_ids(self):
        from openclaw_video.bridge_app import create_app

        gateway = FakeGateway()
        client = TestClient(
            create_app(
                dify=FakeDifyClient(),
                session_store=InMemorySessionStore(),
                job_store=InMemoryJobStore(),
                gateway=gateway,
                identity_secret="test-secret",
            )
        )
        session_response = client.post(
            "/openclaw-api/sessions",
            json={"title": "Chat"},
            headers=self.auth("account-a", "tenant-a"),
        )
        session = session_response.json()["session"]
        response = client.post(
            "/openclaw-api/chat",
            json={"session_id": session["id"], "content": "hello"},
            headers=self.auth("account-a", "tenant-a"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["message"]["role"], "assistant")
        self.assertEqual(body["message"]["content"], "reply to hello")
        self.assertEqual(len(gateway.requests), 1)
        request = gateway.requests[0]
        self.assertEqual(request.session_id, session["id"])
        # First turn: content has the persona prefix + original message.
        self.assertIn("hello", request.content)
        self.assertIn("短视频", request.content)
        self.assertEqual(request.history, ())
        self.assertNotIn("tenant-a", request.routing_user)
        self.assertNotIn("account-a", request.routing_user)
        self.assertNotIn("tenant-a", request.to_payload().values())
        self.assertNotIn("account-a", request.to_payload().values())

    def test_chat_gateway_history_excludes_current_message(self):
        from openclaw_video.bridge_app import create_app

        gateway = FakeGateway()
        session_store = InMemorySessionStore()
        client = TestClient(
            create_app(
                dify=FakeDifyClient(),
                session_store=session_store,
                job_store=InMemoryJobStore(),
                gateway=gateway,
                identity_secret="test-secret",
            )
        )
        session = client.post(
            "/openclaw-api/sessions",
            json={"title": "Chat"},
            headers=self.auth("account-a"),
        ).json()["session"]
        first = client.post(
            "/openclaw-api/chat",
            json={"session_id": session["id"], "content": "first"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(first.status_code, 200, first.text)
        second = client.post(
            "/openclaw-api/chat",
            json={"session_id": session["id"], "content": "second"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(gateway.requests[1].history[0]["role"], "user")
        self.assertEqual(gateway.requests[1].history[0]["content"], "first")
        self.assertEqual(gateway.requests[1].history[1]["role"], "assistant")
        self.assertEqual(gateway.requests[1].history[1]["content"], "reply to first")
        self.assertNotIn("second", [item["content"] for item in gateway.requests[1].history])

    # --- M2 续: conversation state machine + branch routing -------------

    def _chat_client(self, gateway):
        from openclaw_video.bridge_app import create_app

        return TestClient(
            create_app(
                dify=FakeDifyClient(),
                session_store=self.sessions,
                job_store=self.jobs,
                gateway=gateway,
                identity_secret="test-secret",
            )
        )

    def _analysis_result(self, summary):
        return {
            "schema_version": "openclaw-video-result.v1",
            "source": {"video_url_canonical": "https://v.douyin.com/abc", "platform": "douyin", "duration_seconds": 12},
            "summary": summary,
            "signals": {"hook": "ok"},
            "raw_tool_result": {"ok": True},
            "created_at": "2026-06-06T00:00:00Z",
        }

    def test_chat_collecting_intent_uses_fixed_reply_without_agent(self):
        gateway = FakeGateway()
        client = self._chat_client(gateway)
        session = client.post("/openclaw-api/sessions", json={"title": "c"}, headers=self.auth("account-a")).json()["session"]
        r = client.post(
            "/openclaw-api/chat",
            json={"session_id": session["id"], "content": "我想做短视频"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("赛道", r.json()["message"]["content"])
        self.assertEqual(len(gateway.requests), 0)  # fixed reply, agent not called
        self.assertNotIn("_intent", r.json())  # schema contract: no extra field

    def test_chat_waiting_for_video_fixed_reply_for_analysis_intent(self):
        gateway = FakeGateway()
        client = self._chat_client(gateway)
        session = client.post("/openclaw-api/sessions", json={"title": "c"}, headers=self.auth("account-a")).json()["session"]
        # First casual turn -> new -> agent answers.
        client.post("/openclaw-api/chat", json={"session_id": session["id"], "content": "你好"}, headers=self.auth("account-a"))
        self.assertEqual(len(gateway.requests), 1)
        # Now "analyze a video" with no link -> waiting_for_video fixed guidance, no agent call.
        r = client.post(
            "/openclaw-api/chat",
            json={"session_id": session["id"], "content": "帮我分析一个视频"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("抖音", r.json()["message"]["content"])
        self.assertIn("上传", r.json()["message"]["content"])
        self.assertEqual(len(gateway.requests), 1)  # unchanged: no agent call this turn

    def test_chat_follow_up_injects_real_analysis_summary(self):
        gateway = FakeGateway()
        client = self._chat_client(gateway)
        session = client.post("/openclaw-api/sessions", json={"title": "c"}, headers=self.auth("account-a")).json()["session"]
        job = client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/abc"},
            headers=self.auth("account-a"),
        ).json()["job"]
        self.jobs.complete_job(job["job_id"], self._analysis_result("开头三秒用了悬念但选题偏窄"), "openclaw-video-result.v1")
        r = client.post(
            "/openclaw-api/chat",
            json={"session_id": session["id"], "content": "开头怎么改"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(gateway.requests)
        sent = gateway.requests[-1].content
        self.assertIn("开头三秒用了悬念但选题偏窄", sent)  # real summary injected
        self.assertIn("严格基于它回答", sent)

    def test_chat_error_recovering_fixed_reply_on_failed_job(self):
        gateway = FakeGateway()
        client = self._chat_client(gateway)
        session = client.post("/openclaw-api/sessions", json={"title": "c"}, headers=self.auth("account-a")).json()["session"]
        job = client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/abc"},
            headers=self.auth("account-a"),
        ).json()["job"]
        self.jobs.fail_job(job["job_id"], "tool_timeout")
        r = client.post(
            "/openclaw-api/chat",
            json={"session_id": session["id"], "content": "怎么样了"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("没有在限定时间内完成", r.json()["message"]["content"])
        self.assertEqual(len(gateway.requests), 0)  # error path is fixed copy, no agent

    def test_chat_response_has_no_intent_field(self):
        gateway = FakeGateway()
        client = self._chat_client(gateway)
        session = client.post("/openclaw-api/sessions", json={"title": "c"}, headers=self.auth("account-a")).json()["session"]
        r = client.post(
            "/openclaw-api/chat",
            json={"session_id": session["id"], "content": "你好"},
            headers=self.auth("account-a"),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(set(r.json().keys()), {"message", "session"})

    def test_cross_user_cannot_chat_with_other_users_session(self):
        from openclaw_video.bridge_app import create_app

        gateway = FakeGateway()
        client = TestClient(
            create_app(
                dify=FakeDifyClient(),
                session_store=InMemorySessionStore(),
                job_store=InMemoryJobStore(),
                gateway=gateway,
                identity_secret="test-secret",
            )
        )
        session = client.post(
            "/openclaw-api/sessions",
            json={"title": "Chat"},
            headers=self.auth("account-a"),
        ).json()["session"]
        response = client.post(
            "/openclaw-api/chat",
            json={"session_id": session["id"], "content": "hello"},
            headers=self.auth("account-b"),
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(gateway.requests, [])


if __name__ == "__main__":
    unittest.main()
