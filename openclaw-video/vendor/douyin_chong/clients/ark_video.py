from __future__ import annotations

import threading
import time
from typing import Any, Optional

import httpx
from volcenginesdkarkruntime import Ark

from ..config import AppConfig
from ..models import CompletionResult


class ArkVideoClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._thread_local = threading.local()
        self._burst_retry_delays = (8.0, 20.0, 45.0)

    def _get_client(self) -> Ark:
        client = getattr(self._thread_local, "client", None)
        if client is None:
            client = Ark(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                timeout=httpx.Timeout(
                    connect=self.config.connect_timeout,
                    read=self.config.read_timeout,
                    write=self.config.read_timeout,
                    pool=self.config.read_timeout,
                ),
                max_retries=self.config.max_retries,
            )
            self._thread_local.client = client
        return client

    def analyze(self, *, video_urls: list[str], prompt: str) -> CompletionResult:
        last_result: Optional[CompletionResult] = None
        attempted_video_urls: list[str] = []
        client = self._get_client()

        for video_url in video_urls:
            if not video_url or video_url in attempted_video_urls:
                continue
            attempted_video_urls.append(video_url)
            for burst_retry_index in range(len(self._burst_retry_delays) + 1):
                try:
                    response = client.chat.completions.create(
                        model=self.config.model,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {
                                        "type": "video_url",
                                        "video_url": {
                                            "url": video_url,
                                            "fps": self.config.fps,
                                        },
                                    },
                                ],
                            }
                        ],
                        stream=False,
                        max_tokens=self.config.max_tokens,
                    )
                    raw_response = response.model_dump(mode="json")
                    return CompletionResult(
                        output_text=self._extract_output_text(raw_response),
                        raw_response=raw_response,
                        usage=raw_response.get("usage"),
                        status_code=200,
                        attempted_video_urls=tuple(attempted_video_urls),
                        request_id=str(raw_response.get("id", "")),
                    )
                except Exception as exc:  # SDK raises dedicated runtime exceptions at runtime.
                    body = getattr(exc, "body", None)
                    raw_response = body if isinstance(body, dict) else {}
                    last_result = CompletionResult(
                        output_text="",
                        raw_response=raw_response,
                        usage=None,
                        status_code=getattr(exc, "status_code", None),
                        attempted_video_urls=tuple(attempted_video_urls),
                        error_type=type(exc).__name__,
                        error_message=self._extract_error_message(exc, body),
                        api_error_code=str(getattr(exc, "code", "") or ""),
                        api_error_type=str(getattr(exc, "type", "") or ""),
                        api_error_message=self._extract_api_error_message(exc, body),
                        request_id=str(getattr(exc, "request_id", "") or ""),
                    )
                    if self._should_retry_after_backoff(last_result, burst_retry_index):
                        time.sleep(self._burst_retry_delays[burst_retry_index])
                        continue
                    if not self._should_retry_with_next_url(last_result):
                        return last_result
                    break

        if last_result is not None:
            return last_result
        return CompletionResult(
            output_text="",
            raw_response={},
            usage=None,
            status_code=None,
            attempted_video_urls=tuple(attempted_video_urls),
            error_type="NoVideoUrlError",
            error_message="No usable video URLs were available for analysis.",
            api_error_message="No usable video URLs were available for analysis.",
        )

    @staticmethod
    def _extract_output_text(raw_response: dict[str, Any]) -> str:
        choices = raw_response.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message", {})
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        return content.strip() if isinstance(content, str) else ""

    @staticmethod
    def _extract_api_error_message(exc: Exception, body: Optional[Any]) -> str:
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                return str(error.get("message", "") or "")
        return str(exc)

    @staticmethod
    def _extract_error_message(exc: Exception, body: Optional[Any]) -> str:
        message = ArkVideoClient._extract_api_error_message(exc, body)
        return message or str(exc)

    @staticmethod
    def _should_retry_with_next_url(result: CompletionResult) -> bool:
        if result.status_code != 400:
            return False
        if result.api_error_code != "InvalidParameter":
            return False
        message = result.api_error_message.lower()
        return "timeout occurred while processing video" in message

    def _should_retry_after_backoff(
        self,
        result: CompletionResult,
        burst_retry_index: int,
    ) -> bool:
        if burst_retry_index >= len(self._burst_retry_delays):
            return False
        if result.status_code != 429:
            return False
        code = result.api_error_code
        error_type = result.api_error_type.lower()
        message = result.api_error_message.lower()
        return (
            code in {"RequestBurstTooFast", "TooManyRequests"}
            or "toomanyrequests" in error_type
            or "request burst" in message
            or "slow down traffic growth" in message
        )
