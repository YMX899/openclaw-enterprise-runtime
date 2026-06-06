import base64
from urllib.parse import parse_qs
import unittest

from openclaw_video.dify_client import (
    HUAHUO_APP_UUID_HEADER,
    HUAHUO_ACCESS_TOKEN_HEADER,
    HUAHUO_REFRESH_TOKEN_HEADER,
    HuahuoFrontClient,
    huahuo_authorization_header,
    huahuo_identity_headers,
    identity_headers,
)

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class DifyClientTests(unittest.TestCase):
    def test_identity_headers_only_forward_dify_login_material(self):
        selected = identity_headers(
            {
                "Authorization": "Bearer dify",
                "Cookie": "session=1",
                "X-CSRF-Token": "csrf",
                "User-Agent": "browser",
                "OpenClaw-Gateway-Token": "gateway-secret",
            }
        )
        self.assertEqual(selected["Authorization"], "Bearer dify")
        self.assertEqual(selected["Cookie"], "session=1")
        self.assertEqual(selected["X-CSRF-Token"], "csrf")
        self.assertNotIn("User-Agent", selected)
        self.assertNotIn("OpenClaw-Gateway-Token", selected)

    def test_huahuo_authorization_header_matches_frontend_signing_shape(self):
        header = huahuo_authorization_header("HUAHUO-access", app_uuid="abc123", app_time_ms=123456)

        self.assertTrue(header.startswith("Bearer "))
        payload = base64.b64decode(header.removeprefix("Bearer ")).decode("utf-8")
        parsed = parse_qs(payload)
        self.assertEqual(parsed["appVersion"], ["1.0.1"])
        self.assertEqual(parsed["appType"], ["WEB"])
        self.assertEqual(parsed["appUuid"], ["abc123"])
        self.assertEqual(parsed["appTime"], ["123456"])
        self.assertEqual(parsed["token"], ["HUAHUO-access"])
        self.assertEqual(len(parsed["appSign"][0]), 32)

    def test_huahuo_identity_headers_accept_explicit_front_token_only(self):
        selected = huahuo_identity_headers(
            {
                HUAHUO_ACCESS_TOKEN_HEADER: "HUAHUO-access",
                HUAHUO_APP_UUID_HEADER: "front-app-uuid",
                "Cookie": "session=1",
                "OpenClaw-Gateway-Token": "gateway-secret",
            }
        )

        self.assertEqual(set(selected), {"Authorization"})
        self.assertTrue(selected["Authorization"].startswith("Bearer "))
        self.assertNotIn("HUAHUO-access", selected["Authorization"])
        payload = base64.b64decode(selected["Authorization"].removeprefix("Bearer ")).decode("utf-8")
        parsed = parse_qs(payload)
        self.assertEqual(parsed["appUuid"], ["front-app-uuid"])
        self.assertNotIn("Cookie", selected)
        self.assertNotIn("OpenClaw-Gateway-Token", selected)

    def test_huahuo_identity_headers_allows_signed_bearer_without_cookie(self):
        selected = huahuo_identity_headers({"Authorization": "Bearer signed"})
        self.assertEqual(selected, {"Authorization": "Bearer signed"})

    @unittest.skipIf(httpx is None, "httpx is not installed")
    def test_huahuo_client_refreshes_expired_front_access_token(self):
        requests = []

        def handler(request):
            requests.append((request.method, str(request.url), request.headers.get("Authorization", "")))
            if request.url.path == "/api/front/user/queryUserInfo" and len(requests) == 1:
                return httpx.Response(401, json={"status": -1, "message": "expired"})
            if request.url.path == "/api/updateToken":
                return httpx.Response(
                    200,
                    json={"status": 1, "data": {"accessToken": "fresh-access", "refreshToken": "fresh-refresh"}},
                )
            if request.url.path == "/api/front/user/queryUserInfo":
                payload = request.headers.get("Authorization", "")
                decoded = base64.b64decode(payload.removeprefix("Bearer ")).decode("utf-8")
                self.assertIn("token=fresh-access", decoded)
                return httpx.Response(200, json={"status": 1, "data": {"id": 19}})
            return httpx.Response(404)

        client = HuahuoFrontClient(
            "https://www.huahuoai.com",
            transport=httpx.MockTransport(handler),
        )
        headers = {
            HUAHUO_ACCESS_TOKEN_HEADER: "expired-access",
            HUAHUO_REFRESH_TOKEN_HEADER: "refresh-token",
            HUAHUO_APP_UUID_HEADER: "front-app-uuid",
        }

        import asyncio

        profile = asyncio.run(client.profile(headers))

        self.assertEqual(profile, {"id": "huahuo:19"})
        self.assertEqual([method for method, _, _ in requests], ["GET", "POST", "GET"])
        self.assertNotIn("refresh-token", "".join(item[2] for item in requests))

    @unittest.skipIf(httpx is None, "httpx is not installed")
    def test_huahuo_client_refreshes_business_status_login_expiry(self):
        requests = []

        def handler(request):
            requests.append((request.method, str(request.url), request.headers.get("Authorization", "")))
            if request.url.path == "/api/front/user/queryUserInfo" and len(requests) == 1:
                return httpx.Response(200, json={"status": 401, "message": "login expired"})
            if request.url.path == "/api/updateToken":
                return httpx.Response(
                    200,
                    json={"status": 1, "data": {"accessToken": "fresh-access", "refreshToken": "fresh-refresh"}},
                )
            if request.url.path == "/api/front/user/queryUserInfo":
                payload = request.headers.get("Authorization", "")
                decoded = base64.b64decode(payload.removeprefix("Bearer ")).decode("utf-8")
                self.assertIn("token=fresh-access", decoded)
                return httpx.Response(200, json={"status": 1, "data": {"id": 20}})
            return httpx.Response(404)

        client = HuahuoFrontClient(
            "https://www.huahuoai.com",
            transport=httpx.MockTransport(handler),
        )
        headers = {
            HUAHUO_ACCESS_TOKEN_HEADER: "expired-access",
            HUAHUO_REFRESH_TOKEN_HEADER: "refresh-token",
            HUAHUO_APP_UUID_HEADER: "front-app-uuid",
        }

        import asyncio

        profile = asyncio.run(client.profile(headers))

        self.assertEqual(profile, {"id": "huahuo:20"})
        self.assertEqual([method for method, _, _ in requests], ["GET", "POST", "GET"])
        self.assertNotIn("refresh-token", "".join(item[2] for item in requests))

    @unittest.skipIf(httpx is None, "httpx is not installed")
    def test_huahuo_safe_identity_probe_reports_only_safe_metadata(self):
        query_count = 0

        def handler(request):
            nonlocal query_count
            if request.url.path == "/api/front/user/queryUserInfo":
                query_count += 1
                if query_count == 1:
                    return httpx.Response(200, json={"status": 401, "message": "login expired"})
                return httpx.Response(
                    200,
                    json={
                        "status": 1,
                        "data": {
                            "id": 20,
                            "loginName": "safe-name",
                            "mobile": "hidden",
                        },
                    },
                )
            if request.url.path == "/api/updateToken":
                return httpx.Response(
                    200,
                    json={"status": 1, "data": {"accessToken": "fresh-access", "refreshToken": "fresh-refresh"}},
                )
            return httpx.Response(404)

        client = HuahuoFrontClient(
            "https://www.huahuoai.com",
            transport=httpx.MockTransport(handler),
        )
        headers = {
            HUAHUO_ACCESS_TOKEN_HEADER: "expired-access",
            HUAHUO_REFRESH_TOKEN_HEADER: "refresh-token",
            HUAHUO_APP_UUID_HEADER: "front-app-uuid",
        }

        import asyncio

        probe = asyncio.run(client.safe_identity_probe(headers))

        self.assertEqual(probe["provider"], "huahuo_front")
        self.assertEqual(probe["profile_http_status"], 200)
        self.assertEqual(probe["profile_business_status"], 401)
        self.assertEqual(probe["refresh_attempted"], True)
        self.assertEqual(probe["refresh_business_status"], 1)
        self.assertEqual(probe["refresh_issued_access_token"], True)
        self.assertEqual(probe["retry_http_status"], 200)
        self.assertEqual(probe["retry_business_status"], 1)
        self.assertEqual(probe["retry_data_keys"], ["id", "loginName", "mobile"])
        rendered = repr(probe)
        self.assertNotIn("expired-access", rendered)
        self.assertNotIn("refresh-token", rendered)
        self.assertNotIn("fresh-access", rendered)
        self.assertNotIn("fresh-refresh", rendered)
        self.assertNotIn("safe-name", rendered)
        self.assertNotIn("hidden", rendered)


if __name__ == "__main__":
    unittest.main()
