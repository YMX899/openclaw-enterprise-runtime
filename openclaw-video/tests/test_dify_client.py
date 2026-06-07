import base64
from urllib.parse import parse_qs
import unittest

from openclaw_video.dify_client import (
    HUAHUO_APP_UUID_HEADER,
    HUAHUO_ACCESS_TOKEN_HEADER,
    HUAHUO_REFRESH_TOKEN_HEADER,
    DifyClient,
    HuahuoFrontClient,
    dify_identity_material_present,
    huahuo_cookie_headers,
    huahuo_authorization_header,
    huahuo_identity_headers,
    huahuo_identity_material_present,
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
                "Host": "ai001.huahuoai.com",
                "X-CSRF-Token": "csrf",
                "X-Forwarded-Proto": "https",
                "User-Agent": "browser",
                "OpenClaw-Gateway-Token": "gateway-secret",
            }
        )
        self.assertEqual(selected["Authorization"], "Bearer dify")
        self.assertEqual(selected["Cookie"], "session=1")
        self.assertEqual(selected["Host"], "ai001.huahuoai.com")
        self.assertEqual(selected["Origin"], "https://ai001.huahuoai.com")
        self.assertEqual(selected["Referer"], "https://ai001.huahuoai.com/")
        self.assertEqual(selected["X-CSRF-Token"], "csrf")
        self.assertEqual(selected["X-Forwarded-Proto"], "https")
        self.assertNotIn("User-Agent", selected)
        self.assertNotIn("OpenClaw-Gateway-Token", selected)
        self.assertTrue(dify_identity_material_present({"Cookie": "access_token=secret"}))
        self.assertFalse(dify_identity_material_present({"User-Agent": "browser"}))

    def test_identity_headers_derives_dify_authorization_from_access_token_cookie(self):
        selected = identity_headers(
            {
                "Cookie": "locale=en; access_token=dify-cookie-access; refresh_token=dify-refresh",
                "Host": "ai001.huahuoai.com",
            }
        )

        self.assertEqual(selected["Authorization"], "Bearer dify-cookie-access")
        self.assertEqual(selected["Cookie"], "locale=en; access_token=dify-cookie-access; refresh_token=dify-refresh")
        self.assertEqual(selected["Origin"], "https://ai001.huahuoai.com")
        self.assertEqual(selected["Referer"], "https://ai001.huahuoai.com/")

    def test_identity_headers_prefers_explicit_authorization_over_cookie_token(self):
        selected = identity_headers(
            {
                "Authorization": "Bearer explicit",
                "Cookie": "access_token=dify-cookie-access",
            }
        )

        self.assertEqual(selected["Authorization"], "Bearer explicit")

    @unittest.skipIf(httpx is None, "httpx is not installed")
    def test_dify_safe_identity_probe_reports_only_safe_metadata(self):
        requests = []

        def handler(request):
            requests.append(
                (
                    request.method,
                    str(request.url),
                    request.headers.get("Cookie", ""),
                    request.headers.get("Authorization", ""),
                )
            )
            if request.url.path == "/console/api/account/profile":
                return httpx.Response(401, json={"code": "unauthorized"})
            if request.url.path == "/console/api/workspaces":
                return httpx.Response(401, json={"code": "unauthorized"})
            return httpx.Response(404)

        client = DifyClient(
            "https://ai001.huahuoai.com",
            transport=httpx.MockTransport(handler),
        )

        import asyncio

        probe = asyncio.run(
            client.safe_identity_probe(
                {
                    "Cookie": "__Host-access_token=secret; csrf_token=csrf",
                    "Authorization": "Bearer token-secret",
                    "X-CSRF-Token": "csrf-secret",
                }
            )
        )

        self.assertEqual(probe["provider"], "dify")
        self.assertEqual(probe["identity_headers_present"], True)
        self.assertEqual(probe["cookie_names"], ["__Host-access_token", "csrf_token"])
        self.assertEqual(probe["authorization_present"], True)
        self.assertEqual(probe["authorization_generated_from_cookie"], False)
        self.assertEqual(probe["csrf_header_present"], True)
        self.assertEqual(probe["profile_http_status"], 401)
        self.assertEqual(probe["workspaces_http_status"], 401)
        rendered = repr(probe)
        self.assertNotIn("secret", rendered)
        self.assertTrue(all(cookie == "__Host-access_token=secret; csrf_token=csrf" for _, _, cookie, _ in requests))

    @unittest.skipIf(httpx is None, "httpx is not installed")
    def test_dify_safe_identity_probe_reports_generated_authorization_without_value(self):
        requests = []

        def handler(request):
            requests.append((request.url.path, request.headers.get("Authorization", "")))
            return httpx.Response(401, json={"code": "unauthorized"})

        client = DifyClient(
            "https://ai001.huahuoai.com",
            transport=httpx.MockTransport(handler),
        )

        import asyncio

        probe = asyncio.run(client.safe_identity_probe({"Cookie": "access_token=cookie-secret"}))

        self.assertEqual(probe["authorization_present"], False)
        self.assertEqual(probe["authorization_generated_from_cookie"], True)
        self.assertEqual(probe["cookie_names"], ["access_token"])
        self.assertNotIn("cookie-secret", repr(probe))
        self.assertTrue(all(auth == "Bearer cookie-secret" for _, auth in requests))

    @unittest.skipIf(httpx is None, "httpx is not installed")
    def test_dify_resolve_identity_refreshes_cookie_session_and_returns_set_cookie(self):
        requests = []

        def handler(request):
            requests.append((request.method, request.url.path, request.headers.get("Authorization", "")))
            if request.url.path == "/console/api/account/profile" and len(requests) == 1:
                return httpx.Response(401, json={"code": "unauthorized"})
            if request.url.path == "/console/api/refresh-token":
                return httpx.Response(
                    200,
                    json={"result": "success"},
                    headers=[
                        ("Set-Cookie", "access_token=fresh-access; Path=/; HttpOnly"),
                        ("Set-Cookie", "refresh_token=fresh-refresh; Path=/; HttpOnly"),
                        ("Set-Cookie", "csrf_token=fresh-csrf; Path=/"),
                    ],
                )
            if request.url.path == "/console/api/account/profile":
                self.assertEqual(request.headers.get("Authorization"), "Bearer fresh-access")
                return httpx.Response(200, json={"id": "account-a"})
            if request.url.path == "/console/api/workspaces":
                self.assertEqual(request.headers.get("Authorization"), "Bearer fresh-access")
                return httpx.Response(200, json={"data": [{"id": "tenant-a", "current": True}]})
            return httpx.Response(404)

        client = DifyClient(
            "https://ai001.huahuoai.com",
            transport=httpx.MockTransport(handler),
        )

        import asyncio

        context = asyncio.run(client.resolve_identity({"Cookie": "refresh_token=refresh-secret"}))

        self.assertEqual(context.profile, {"id": "account-a"})
        self.assertEqual(context.workspaces, {"data": [{"id": "tenant-a", "current": True}]})
        self.assertEqual(context.refreshed, True)
        self.assertEqual(len(context.set_cookie_headers), 3)
        self.assertIn(("POST", "/console/api/refresh-token", ""), requests)

    @unittest.skipIf(httpx is None, "httpx is not installed")
    def test_dify_safe_identity_probe_reports_refresh_shape_without_values(self):
        profile_calls = 0

        def handler(request):
            nonlocal profile_calls
            if request.url.path == "/console/api/account/profile":
                profile_calls += 1
                if profile_calls == 1:
                    return httpx.Response(401, json={"code": "unauthorized"})
                return httpx.Response(200, json={"id": "account-a", "email": "hidden"})
            if request.url.path == "/console/api/workspaces" and profile_calls < 2:
                return httpx.Response(401, json={"code": "unauthorized"})
            if request.url.path == "/console/api/workspaces":
                return httpx.Response(200, json={"data": [{"id": "tenant-a", "current": True}]})
            if request.url.path == "/console/api/refresh-token":
                return httpx.Response(
                    200,
                    json={"result": "success"},
                    headers=[
                        ("Set-Cookie", "access_token=fresh-access; Path=/; HttpOnly"),
                        ("Set-Cookie", "refresh_token=fresh-refresh; Path=/; HttpOnly"),
                        ("Set-Cookie", "csrf_token=fresh-csrf; Path=/"),
                    ],
                )
            return httpx.Response(404)

        client = DifyClient(
            "https://ai001.huahuoai.com",
            transport=httpx.MockTransport(handler),
        )

        import asyncio

        probe = asyncio.run(client.safe_identity_probe({"Cookie": "refresh_token=refresh-secret"}))

        self.assertEqual(probe["refresh_attempted"], True)
        self.assertEqual(probe["refresh_http_status"], 200)
        self.assertEqual(probe["refresh_set_cookie_names"], ["access_token", "csrf_token", "refresh_token"])
        self.assertEqual(probe["retry_profile_http_status"], 200)
        self.assertEqual(probe["retry_workspaces_http_status"], 200)
        rendered = repr(probe)
        self.assertNotIn("refresh-secret", rendered)
        self.assertNotIn("fresh-access", rendered)
        self.assertNotIn("fresh-refresh", rendered)
        self.assertNotIn("fresh-csrf", rendered)

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

    def test_huahuo_cookie_headers_are_available_for_same_site_identity_only(self):
        selected = huahuo_cookie_headers(
            {
                "Cookie": "huahuo_session=secret",
                "OpenClaw-Gateway-Token": "gateway-secret",
                "User-Agent": "browser",
            }
        )

        self.assertEqual(selected, {"Cookie": "huahuo_session=secret"})
        self.assertTrue(huahuo_identity_material_present({"Cookie": "huahuo_session=secret"}))
        self.assertFalse(huahuo_identity_material_present({"User-Agent": "browser"}))

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

    @unittest.skipIf(httpx is None, "httpx is not installed")
    def test_huahuo_client_can_use_cookie_only_identity_without_recording_cookie(self):
        requests = []

        def handler(request):
            requests.append((request.method, str(request.url), request.headers.get("Cookie", "")))
            if request.url.path == "/api/front/user/queryUserInfo":
                return httpx.Response(200, json={"status": 1, "data": {"id": 21, "loginName": "cookie-user"}})
            return httpx.Response(404)

        client = HuahuoFrontClient(
            "https://www.huahuoai.com",
            transport=httpx.MockTransport(handler),
        )

        import asyncio

        profile = asyncio.run(client.profile({"Cookie": "huahuo_session=secret"}))
        probe = asyncio.run(client.safe_identity_probe({"Cookie": "huahuo_session=secret"}))

        self.assertEqual(profile, {"id": "huahuo:21"})
        self.assertEqual(probe["identity_headers_present"], True)
        self.assertEqual(probe["profile_data_keys"], ["id", "loginName"])
        rendered = repr(probe)
        self.assertNotIn("huahuo_session=secret", rendered)
        self.assertTrue(all(cookie == "huahuo_session=secret" for _, _, cookie in requests))


if __name__ == "__main__":
    unittest.main()
