from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_KNOWLEDGE_PATH = Path(__file__).resolve().parents[1] / "source-book" / "knowledge.md"
DEFAULT_MODEL = "doubao-seed-2-0-pro"
DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
DEFAULT_MEDIAKIT_BASE_URL = "https://amk-ark.cn-beijing.volces.com/api/v1"


def _parse_env_assignment(line: str) -> Optional[tuple[str, str]]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def load_env_file(path: Path = DEFAULT_ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        assignment = _parse_env_assignment(raw_line)
        if assignment is None:
            continue
        key, value = assignment
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class AppConfig:
    env_path: Path
    knowledge_path: Path
    model: str
    mode: str
    max_workers: int
    fps: float
    max_tokens: int
    connect_timeout: float
    read_timeout: float
    max_retries: int
    ark_api_key: str
    mediakit_api_key: Optional[str]
    ark_base_url: str
    mediakit_base_url: str

    @property
    def api_key(self) -> str:
        if self.mode == "ark":
            return self.ark_api_key
        if not self.mediakit_api_key:
            raise ValueError("MEDIAKIT_API_KEY is required when mode=mediakit.")
        return f"{self.ark_api_key}/{self.mediakit_api_key}"

    @property
    def base_url(self) -> str:
        if self.mode == "ark":
            return self.ark_base_url
        return self.mediakit_base_url

    @classmethod
    def from_env(
        cls,
        *,
        env_path: Path = DEFAULT_ENV_PATH,
        knowledge_path: Path = DEFAULT_KNOWLEDGE_PATH,
        model: Optional[str] = None,
        mode: str = "ark",
        max_workers: int = 1,
        fps: float = 5.0,
        max_tokens: int = 128000,
        connect_timeout: float = 60.0,
        read_timeout: float = 1800.0,
        max_retries: int = 2,
    ) -> "AppConfig":
        load_env_file(env_path)
        ark_api_key = os.getenv("ARK_API_KEY", "").strip()
        if not ark_api_key:
            raise ValueError(f"Missing ARK_API_KEY in {env_path}.")
        mediakit_api_key = os.getenv("MEDIAKIT_API_KEY", "").strip() or None
        if mode == "mediakit" and not mediakit_api_key:
            raise ValueError(f"Missing MEDIAKIT_API_KEY in {env_path} for mediakit mode.")
        resolved_model = (
            model
            or os.getenv("MODEL")
            or os.getenv("ARK_MODEL")
            or DEFAULT_MODEL
        ).strip()
        return cls(
            env_path=env_path,
            knowledge_path=knowledge_path,
            model=resolved_model,
            mode=mode,
            max_workers=max(1, int(max_workers)),
            fps=fps,
            max_tokens=max_tokens,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            max_retries=max_retries,
            ark_api_key=ark_api_key,
            mediakit_api_key=mediakit_api_key,
            ark_base_url=os.getenv("ARK_BASE_URL", DEFAULT_ARK_BASE_URL).strip(),
            mediakit_base_url=os.getenv(
                "MEDIAKIT_BASE_URL", DEFAULT_MEDIAKIT_BASE_URL
            ).strip(),
        )
