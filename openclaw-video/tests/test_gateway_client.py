import unittest

from openclaw_video.openclaw_gateway import GatewayError, OpenClawGatewayClient


class GatewayClientTests(unittest.TestCase):
    def test_token_required(self):
        client = OpenClawGatewayClient("http://openclaw-gateway:18789", "")
        with self.assertRaises(GatewayError):
            client._headers()

    def test_token_header_is_private_to_gateway_client(self):
        client = OpenClawGatewayClient("http://openclaw-gateway:18789", "secret")
        self.assertEqual(client._headers()["Authorization"], "Bearer secret")


if __name__ == "__main__":
    unittest.main()

