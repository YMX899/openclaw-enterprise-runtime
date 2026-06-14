import os
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization

from openclaw_video.openclaw_gateway import (
    DisabledGatewayClient,
    GatewayChatRequest,
    GatewayError,
    GatewayNotConfigured,
    OpenClawDeviceIdentity,
    OpenClawGatewayWsClient,
    build_device_auth_payload_v3,
    _extract_chat_event_content,
)


TEST_ED25519_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIE5gskg9Tcq0wde1pk0yB4r9LA5SsTWcim9p9lH7mkHg
-----END PRIVATE KEY-----
"""


class GatewayClientTests(unittest.TestCase):
    def setUp(self):
        try:
            self.identity = OpenClawDeviceIdentity.from_private_key_pem(TEST_ED25519_PRIVATE_KEY)
        except GatewayNotConfigured as exc:
            self.skipTest(str(exc))

    def test_build_device_auth_payload_v3_matches_openclaw_order(self):
        payload = build_device_auth_payload_v3(
            device_id="device",
            client_id="gateway-client",
            client_mode="backend",
            role="operator",
            scopes=("operator.read", "operator.write"),
            signed_at_ms=123,
            token="secret",
            nonce="nonce",
            platform="Node",
            device_family="Bridge",
        )
        self.assertEqual(
            payload,
            "v3|device|gateway-client|backend|operator|operator.read,operator.write|123|secret|nonce|node|bridge",
        )

    def test_default_scopes_are_read_write_not_admin(self):
        client = OpenClawGatewayWsClient("ws://openclaw-gateway:18789", "secret", self.identity)
        params = client.connect_params(nonce="nonce", signed_at_ms=123)
        self.assertEqual(params["client"]["id"], "gateway-client")
        self.assertEqual(params["client"]["mode"], "backend")
        self.assertEqual(params["role"], "operator")
        self.assertEqual(params["scopes"], ["operator.read", "operator.write"])
        self.assertNotIn("operator.admin", params["scopes"])
        self.assertEqual(params["device"]["id"], self.identity.device_id)
        self.assertEqual(params["device"]["publicKey"], self.identity.public_key_raw_base64url)
        self.assertIn("signature", params["device"])

    def test_openssh_ed25519_private_key_is_supported(self):
        pem_key = serialization.load_pem_private_key(TEST_ED25519_PRIVATE_KEY.encode("utf-8"), password=None)
        openssh_private_key = pem_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        identity = OpenClawDeviceIdentity.from_private_key_pem(openssh_private_key)

        self.assertEqual(identity.device_id, self.identity.device_id)
        self.assertEqual(identity.public_key_raw_base64url, self.identity.public_key_raw_base64url)
        self.assertTrue(identity.sign("payload"))

    def test_chat_send_uses_hmac_routing_user_as_agent_session_key(self):
        client = OpenClawGatewayWsClient("ws://openclaw-gateway:18789", "secret", self.identity)
        request = GatewayChatRequest(
            routing_user="hmac-routing-user",
            session_id="bridge-session",
            message_id="message-id",
            content="hello",
            history=(),
        )
        params = client.chat_send_params(request)
        self.assertEqual(params["sessionKey"], "agent:main:hmac-routing-user")
        self.assertEqual(params["message"], "hello")
        self.assertEqual(params["idempotencyKey"], "message-id")
        self.assertEqual(params["deliver"], False)
        self.assertNotIn("routing_user", params)
        self.assertNotIn("bridge-session", params.values())

    def test_environment_factory_fails_closed_when_device_key_missing(self):
        previous = os.environ.copy()
        try:
            os.environ["OPENCLAW_GATEWAY_URL"] = "ws://openclaw-gateway:18789"
            os.environ["OPENCLAW_GATEWAY_TOKEN"] = "secret"
            os.environ.pop("OPENCLAW_GATEWAY_DEVICE_KEY_FILE", None)
            self.assertIsInstance(OpenClawGatewayWsClient.from_environment(), DisabledGatewayClient)
        finally:
            os.environ.clear()
            os.environ.update(previous)

    def test_environment_factory_reads_token_and_device_key_from_files(self):
        previous = os.environ.copy()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                token_path = os.path.join(tmp, "gateway.token")
                key_path = os.path.join(tmp, "bridge.key")
                with open(token_path, "w", encoding="utf-8") as handle:
                    handle.write("secret\n")
                with open(key_path, "w", encoding="utf-8") as handle:
                    handle.write(TEST_ED25519_PRIVATE_KEY)
                os.environ.clear()
                os.environ["OPENCLAW_GATEWAY_URL"] = "ws://openclaw-gateway:18789"
                os.environ["OPENCLAW_GATEWAY_TOKEN_FILE"] = token_path
                os.environ["OPENCLAW_GATEWAY_DEVICE_KEY_FILE"] = key_path
                client = OpenClawGatewayWsClient.from_environment()
                self.assertIsInstance(client, OpenClawGatewayWsClient)
                self.assertEqual(client.url, "ws://openclaw-gateway:18789")
                self.assertEqual(client.token, "secret")
        finally:
            os.environ.clear()
            os.environ.update(previous)

    def test_environment_factory_honors_timeout_override(self):
        previous = os.environ.copy()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                token_path = os.path.join(tmp, "gateway.token")
                key_path = os.path.join(tmp, "bridge.key")
                with open(token_path, "w", encoding="utf-8") as handle:
                    handle.write("secret\n")
                with open(key_path, "w", encoding="utf-8") as handle:
                    handle.write(TEST_ED25519_PRIVATE_KEY)
                os.environ.clear()
                os.environ["OPENCLAW_GATEWAY_URL"] = "ws://openclaw-gateway:18789"
                os.environ["OPENCLAW_GATEWAY_TOKEN_FILE"] = token_path
                os.environ["OPENCLAW_GATEWAY_DEVICE_KEY_FILE"] = key_path
                # default is generous (long coaching generations)
                self.assertEqual(OpenClawGatewayWsClient.from_environment().timeout_seconds, 240.0)
                os.environ["OPENCLAW_GATEWAY_TIMEOUT_SECONDS"] = "180"
                self.assertEqual(OpenClawGatewayWsClient.from_environment().timeout_seconds, 180.0)
        finally:
            os.environ.clear()
            os.environ.update(previous)

    def test_invalid_or_missing_ed25519_key_is_not_configured(self):
        with self.assertRaises((GatewayNotConfigured, GatewayError, ValueError)):
            OpenClawDeviceIdentity.from_private_key_pem("")

    def test_agent_failure_text_is_treated_as_gateway_error(self):
        frame = {
            "payload": {
                "state": "final",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": 'Agent failed before reply: No API key found. Auth store: C:\\secret\\auth.json',
                        }
                    ]
                },
            }
        }
        with self.assertRaises(GatewayError):
            _extract_chat_event_content(frame)


if __name__ == "__main__":
    unittest.main()
