from __future__ import annotations

from dataclasses import dataclass
import json
import time
from pathlib import Path
from typing import Any

import requests


DEFAULT_ARK_API_BASE = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_ARK_RESPONSES_MODEL = "doubao-seed-2-0-lite-260428"


class ArkFilesError(RuntimeError):
    pass


class ArkFileProcessingError(ArkFilesError):
    pass


class ArkResponsesError(ArkFilesError):
    pass


@dataclass(frozen=True)
class ArkFilesClient:
    api_key: str
    base_url: str = DEFAULT_ARK_API_BASE
    timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ArkFilesError("ARK_API_KEY is required")

    @property
    def _base(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def upload_user_data_file(self, path: Path, mime_type: str) -> dict[str, Any]:
        if not path.is_file():
            raise ArkFilesError("video file does not exist")
        with path.open("rb") as handle:
            response = requests.post(
                f"{self._base}/files",
                headers=self._headers,
                data={"purpose": "user_data"},
                files={"file": (path.name, handle, mime_type)},
                timeout=self.timeout_seconds,
            )
        return self._json_or_error(response, "Files API upload failed")

    def retrieve_file(self, file_id: str) -> dict[str, Any]:
        response = requests.get(
            f"{self._base}/files/{file_id}",
            headers=self._headers,
            timeout=self.timeout_seconds,
        )
        return self._json_or_error(response, "Files API retrieve failed")

    def wait_file_active(
        self,
        file_id: str,
        *,
        timeout_seconds: int = 300,
        poll_interval_seconds: float = 2.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        last_file: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            file_info = self.retrieve_file(file_id)
            last_file = file_info
            status = str(file_info.get("status") or "").lower()
            if status == "active":
                return file_info
            if status in {"failed", "error", "expired", "deleted"}:
                raise ArkFileProcessingError(f"Files API file status is {status}")
            if status and status != "processing":
                raise ArkFileProcessingError(f"Files API file status is {status}")
            time.sleep(poll_interval_seconds)
        status = str((last_file or {}).get("status") or "processing")
        raise TimeoutError(f"waiting for Files API file to become active timed out: {status}")

    def create_video_response(
        self,
        *,
        model: str,
        file_id: str,
        prompt: str,
        max_tokens: int = 12000,
        temperature: float = 0.1,
        fps: float | None = None,
    ) -> dict[str, Any]:
        video_block: dict[str, Any] = {"type": "input_video", "file_id": file_id}
        if fps is not None:
            if fps <= 0:
                raise ArkFilesError("fps must be positive")
            video_block["fps"] = fps
        response = requests.post(
            f"{self._base}/responses",
            headers={**self._headers, "Content-Type": "application/json"},
            json={
                "model": model,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            video_block,
                        ],
                    }
                ],
                "max_output_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=self.timeout_seconds,
        )
        return self._json_or_error(response, "Responses API video analysis failed")

    @staticmethod
    def extract_output_text(payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        output = payload.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            joined = "\n".join(part.strip() for part in parts if part.strip()).strip()
            if joined:
                return joined
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                return content.strip()
        return ""

    @staticmethod
    def _json_or_error(response: requests.Response, message: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ArkFilesError(f"{message}: HTTP {response.status_code}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            detail = ""
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("code") or "")
                else:
                    detail = str(payload.get("message") or "")
            suffix = f": {detail[:300]}" if detail else ""
            raise ArkFilesError(f"{message}: HTTP {response.status_code}{suffix}")
        if not isinstance(payload, dict):
            raise ArkFilesError(f"{message}: response must be an object")
        return payload
