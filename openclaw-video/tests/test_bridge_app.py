import unittest

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - exercised when optional deps are absent
    TestClient = None

from openclaw_video.job_store import InMemoryJobStore
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
        return {"data": [{"id": tenant_id, "current": True}]}


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
        self.assertIn("/openclaw-api/me", response.text)
        self.assertIn("/openclaw-api/jobs", response.text)
        self.assertNotIn("OPENCLAW_GATEWAY_TOKEN", response.text)
        self.assertNotIn("openclaw-gateway:18789", response.text)
        self.assertNotIn("Authorization", response.text)
        self.assertNotIn("Cookie", response.text)

    def test_openclaw_lab_without_trailing_slash_is_served(self):
        response = self.client.get("/openclaw-lab")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("OpenClaw Lab", response.text)

    def test_me_does_not_expose_raw_dify_ids(self):
        response = self.client.get("/openclaw-api/me", headers=self.auth())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["authenticated"], True)
        self.assertIn("principal_id", body)
        self.assertNotIn("tenant_id", body)
        self.assertNotIn("account_id", body)

    def test_login_required_for_me(self):
        response = self.client.get("/openclaw-api/me")
        self.assertEqual(response.status_code, 401)

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
