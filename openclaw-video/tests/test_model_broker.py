from datetime import UTC, datetime, timedelta
import unittest

from openclaw_video.model_broker import (
    NoApiKeyAvailable,
    hash_api_key,
    is_rate_limit_error,
    parse_api_key_list,
    select_api_key,
    ModelProviderConfig,
)


class FakeBrokerStore:
    def __init__(self):
        self.cooldowns = {}
        self.selected = []
        self.rate_limited = []

    def list_api_key_cooldowns(self, provider, key_hashes):
        return {key_hash: self.cooldowns[key_hash] for key_hash in key_hashes if key_hash in self.cooldowns}

    def mark_api_key_selected(self, provider, key_hash):
        self.selected.append((provider, key_hash))

    def mark_api_key_rate_limited(self, provider, key_hash, cooldown_seconds):
        self.rate_limited.append((provider, key_hash, cooldown_seconds))


class ModelBrokerTests(unittest.TestCase):
    def test_parse_api_key_list_dedupes_without_exposing_values(self):
        self.assertEqual(parse_api_key_list("k1,k2 k1; k3"), ("k1", "k2", "k3"))

    def test_select_api_key_skips_cooling_key(self):
        store = FakeBrokerStore()
        key1 = hash_api_key("key-1")
        store.cooldowns[key1] = {"cooldown_until": datetime.now(UTC) + timedelta(minutes=1)}
        cfg = ModelProviderConfig(
            provider="bailian",
            api_keys=("key-1", "key-2"),
            base_url="https://example/v1",
            model="model",
        )

        selected = select_api_key(cfg, store)

        self.assertEqual(selected.api_key, "key-2")
        self.assertEqual(store.selected, [("bailian", hash_api_key("key-2"))])

    def test_select_api_key_rejects_all_cooling_keys(self):
        store = FakeBrokerStore()
        now = datetime.now(UTC) + timedelta(minutes=1)
        store.cooldowns[hash_api_key("key-1")] = {"cooldown_until": now}
        cfg = ModelProviderConfig(
            provider="bailian",
            api_keys=("key-1",),
            base_url="https://example/v1",
            model="model",
        )

        with self.assertRaises(NoApiKeyAvailable):
            select_api_key(cfg, store)

    def test_rate_limit_detection(self):
        self.assertTrue(is_rate_limit_error("Responses API video analysis failed: HTTP 429"))
        self.assertTrue(is_rate_limit_error("rate_limit exceeded"))
        self.assertFalse(is_rate_limit_error("bad request"))


if __name__ == "__main__":
    unittest.main()
