from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import os
import re
import time
from typing import Iterator, Protocol


DEFAULT_BAILIAN_PROVIDER = "bailian-openai-compatible"
DEFAULT_BAILIAN_OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_BAILIAN_MODEL = "qwen-vl-max-latest"
DEFAULT_API_KEY_COOLDOWN_SECONDS = 60
DEFAULT_VIDEO_MODEL_LANE = "video_model_request"
DEFAULT_VIDEO_MODEL_MAX_CONCURRENT = 200
DEFAULT_VIDEO_MODEL_LANE_LEASE_SECONDS = 900


class ModelBrokerError(RuntimeError):
    pass


class NoApiKeyAvailable(ModelBrokerError):
    pass


class LaneLeaseUnavailable(ModelBrokerError):
    pass


class BrokerStore(Protocol):
    def list_api_key_cooldowns(self, provider: str, key_hashes: list[str]) -> dict[str, dict]: ...

    def mark_api_key_selected(self, provider: str, key_hash: str) -> None: ...

    def mark_api_key_rate_limited(self, provider: str, key_hash: str, cooldown_seconds: int) -> None: ...

    def acquire_lane_lease(
        self,
        lane: str,
        *,
        worker_id: str,
        max_concurrent: int,
        lease_seconds: int,
    ) -> tuple[str, int] | None: ...

    def release_lane_lease(self, lane: str, lease_id: str) -> None: ...


@dataclass(frozen=True)
class ModelProviderConfig:
    provider: str
    api_keys: tuple[str, ...]
    base_url: str
    model: str
    cooldown_seconds: int = DEFAULT_API_KEY_COOLDOWN_SECONDS


@dataclass(frozen=True)
class SelectedApiKey:
    provider: str
    api_key: str
    key_hash: str
    key_index: int
    base_url: str
    model: str


@dataclass(frozen=True)
class LaneLease:
    lane: str
    lease_id: str
    slot_index: int


def hash_api_key(api_key: str) -> str:
    return sha256(api_key.strip().encode("utf-8")).hexdigest()


def short_key_hash(api_key_or_hash: str) -> str:
    value = api_key_or_hash.strip()
    if re.fullmatch(r"[0-9a-f]{64}", value):
        return value[:12]
    return hash_api_key(value)[:12]


def parse_api_key_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    values: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[\s,;]+", raw):
        key = item.strip()
        if not key:
            continue
        digest = hash_api_key(key)
        if digest in seen:
            continue
        seen.add(digest)
        values.append(key)
    return tuple(values)


def positive_int_env(name: str, default: int, env: dict[str, str] | None = None) -> int:
    source = env if env is not None else os.environ
    raw = source.get(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def load_bailian_config(env: dict[str, str] | None = None) -> ModelProviderConfig | None:
    source = env if env is not None else os.environ
    keys = parse_api_key_list(source.get("BAILIAN_API_KEYS") or source.get("BAILIAN_API_KEY"))
    if not keys:
        return None
    provider = (source.get("BAILIAN_PROVIDER") or DEFAULT_BAILIAN_PROVIDER).strip()
    base_url = (source.get("BAILIAN_OPENAI_BASE_URL") or DEFAULT_BAILIAN_OPENAI_BASE_URL).strip()
    model = (source.get("BAILIAN_MODEL") or DEFAULT_BAILIAN_MODEL).strip()
    cooldown = positive_int_env("BAILIAN_API_KEY_COOLDOWN_SECONDS", DEFAULT_API_KEY_COOLDOWN_SECONDS, source)
    return ModelProviderConfig(
        provider=provider,
        api_keys=keys,
        base_url=base_url,
        model=model,
        cooldown_seconds=cooldown,
    )


def is_rate_limit_error(error: BaseException | str) -> bool:
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "http 429",
            "status 429",
            "status_code=429",
            "too many requests",
            "rate_limit",
            "ratelimit",
            "throttl",
            "quota",
            "serveroverloaded",
        )
    )


def _cooled_down(row: dict | None, now: datetime) -> bool:
    if not row:
        return False
    cooldown_until = row.get("cooldown_until")
    if cooldown_until is None:
        return False
    if isinstance(cooldown_until, datetime):
        return cooldown_until > now
    try:
        parsed = datetime.fromisoformat(str(cooldown_until))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed > now


def select_api_key(config: ModelProviderConfig, store: BrokerStore) -> SelectedApiKey:
    keys = list(config.api_keys)
    key_hashes = [hash_api_key(key) for key in keys]
    cooldowns = store.list_api_key_cooldowns(config.provider, key_hashes)
    now = datetime.now(UTC)
    ordered = sorted(
        enumerate(keys),
        key=lambda item: (
            1 if _cooled_down(cooldowns.get(key_hashes[item[0]]), now) else 0,
            str(cooldowns.get(key_hashes[item[0]], {}).get("last_selected_at") or ""),
            item[0],
        ),
    )
    for index, key in ordered:
        digest = key_hashes[index]
        if _cooled_down(cooldowns.get(digest), now):
            continue
        store.mark_api_key_selected(config.provider, digest)
        return SelectedApiKey(
            provider=config.provider,
            api_key=key,
            key_hash=digest,
            key_index=index,
            base_url=config.base_url,
            model=config.model,
        )
    raise NoApiKeyAvailable(f"all API keys are cooling down for provider {config.provider}")


@contextmanager
def acquire_lane(
    store: BrokerStore,
    lane: str = DEFAULT_VIDEO_MODEL_LANE,
    *,
    worker_id: str,
    max_concurrent: int = DEFAULT_VIDEO_MODEL_MAX_CONCURRENT,
    lease_seconds: int = DEFAULT_VIDEO_MODEL_LANE_LEASE_SECONDS,
    wait_timeout_seconds: int = 60,
    poll_seconds: float = 0.5,
) -> Iterator[LaneLease]:
    deadline = time.monotonic() + max(1, wait_timeout_seconds)
    acquired: tuple[str, int] | None = None
    while time.monotonic() <= deadline:
        acquired = store.acquire_lane_lease(
            lane,
            worker_id=worker_id,
            max_concurrent=max_concurrent,
            lease_seconds=lease_seconds,
        )
        if acquired:
            break
        time.sleep(max(0.05, poll_seconds))
    if not acquired:
        raise LaneLeaseUnavailable(f"lane {lane} has no available lease")
    lease_id, slot_index = acquired
    try:
        yield LaneLease(lane=lane, lease_id=lease_id, slot_index=slot_index)
    finally:
        store.release_lane_lease(lane, lease_id)
