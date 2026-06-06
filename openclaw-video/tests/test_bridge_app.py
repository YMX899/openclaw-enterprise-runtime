import os
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


class FakeGateway:
    def __init__(self):
        self.requests = []

    async def chat(self, request):
        self.requests.append(request)
        return GatewayChatResult(content=f"reply to {request.content}", raw={"content": f"reply to {request.content}"})


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class BridgeAppTests(unittest.TestCase):
    def setUp(self):
        from openclaw_video.bridge_app import create_app

        self.sessions = InMemorySessionStore()
        self.jobs = InMemoryJobStore()
        self.client = TestClient(
            create_app(
                dify=FakeDifyClient(),
                session_store=self.sessions,
                job_store=self.jobs,
                identity_secret="test-secret",
            )
        )

    def auth(self, account="account-a", tenant="tenant-a"):
        return {"x-test-account": account, "x-test-tenant": tenant}

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

    def test_openclaw_lab_page_is_served_without_gateway_secret_surface(self):
        response = self.client.get("/openclaw-lab/")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("OpenClaw Lab", response.text)
        self.assertIn("Access-Token", response.text)
        self.assertIn("APP-UUID", response.text)
        self.assertIn("Refresh-Token", response.text)
        self.assertIn("X-Huahuo-Access-Token", response.text)
        self.assertIn("X-Huahuo-App-UUID", response.text)
        self.assertIn("X-Huahuo-Refresh-Token", response.text)
        self.assertIn("const apiPrefix", response.text)
        self.assertIn("'/openclaw-api'", response.text)
        self.assertIn("'/api/openclaw-api'", response.text)
        self.assertIn("'/console/api/openclaw-api'", response.text)
        self.assertIn("apiPrefix + '/me'", response.text)
        self.assertIn("apiPrefix + '/identity/diagnostics'", response.text)
        self.assertIn("apiPrefix + '/jobs'", response.text)
        self.assertIn("apiPrefix + '/uploads'", response.text)
        self.assertIn("apiPrefix + '/jobs/' + encodeURIComponent(currentJobId) + '/result", response.text)
        self.assertIn("Upload Video", response.text)
        self.assertIn("Tiny Upload", response.text)
        self.assertIn("FormData", response.text)
        self.assertIn("upload_smoke", response.text)
        self.assertIn("Self Test", response.text)
        self.assertIn("Security Test", response.text)
        self.assertIn("Post-Login Acceptance", response.text)
        self.assertIn("security_test", response.text)
        self.assertIn("post_login_acceptance", response.text)
        self.assertIn("runPostLoginAcceptance", response.text)
        self.assertIn("https://example.com/not-douyin", response.text)
        self.assertIn("http://127.0.0.1:8081/apps", response.text)
        self.assertIn("http://169.254.169.254/latest/meta-data/", response.text)
        self.assertIn("non_allowlisted_domain", response.text)
        self.assertIn("localhost_blocked", response.text)
        self.assertIn("cloud_metadata_blocked", response.text)
        self.assertIn("random_job_404", response.text)
        self.assertIn("random_result_404", response.text)
        self.assertIn("random_session_404", response.text)
        self.assertIn("tiny_upload_terminal", response.text)
        self.assertIn("tiny_upload_result", response.text)
        self.assertIn("messages_visible_to_owner", response.text)
        self.assertNotIn("OPENCLAW_GATEWAY_TOKEN", response.text)
        self.assertNotIn("openclaw-gateway:18789", response.text)
        self.assertNotIn("Authorization", response.text)
        self.assertNotIn("Cookie", response.text)
        self.assertNotIn("HUAHUO-access", response.text)

    def test_openclaw_lab_without_trailing_slash_is_served(self):
        response = self.client.get("/openclaw-lab")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("OpenClaw Lab", response.text)

    def test_ai_scoped_openclaw_lab_uses_ai_api_prefix_without_secret_surface(self):
        response = self.client.get("/ai/openclaw-lab/")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("OpenClaw Lab", response.text)
        self.assertIn("/api/openclaw-api", response.text)
        self.assertIn("/console/api/openclaw-api", response.text)
        self.assertIn("/openclaw-api", response.text)
        self.assertNotIn("OPENCLAW_GATEWAY_TOKEN", response.text)
        self.assertNotIn("Authorization", response.text)
        self.assertNotIn("Cookie", response.text)

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

    def test_identity_diagnostics_reports_missing_login_without_secrets(self):
        response = self.client.get("/openclaw-api/identity/diagnostics")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], False)
        self.assertEqual(body["login_material_present"], False)
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
        self.assertEqual(len(body["principal_id"]), 64)
        self.assertNotIn("account-a", response.text)
        self.assertNotIn("tenant-a", response.text)
        self.assertNotIn("test-mode-secret", response.text)

    def test_huahuo_front_identity_provider_accepts_frontend_token_without_raw_ids(self):
        from openclaw_video.bridge_app import create_app

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

    def test_huahuo_identity_diagnostics_probe_is_safe_when_profile_fails(self):
        from openclaw_video.bridge_app import create_app

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
        self.assertEqual(request.content, "hello")
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
