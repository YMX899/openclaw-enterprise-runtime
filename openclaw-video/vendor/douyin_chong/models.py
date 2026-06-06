from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class KnowledgeTask:
    index: int
    source_url: str
    instruction_text: str
    source_block: str


@dataclass(frozen=True)
class VideoSource:
    source_url: str
    video_id: str
    share_url: str
    playwm_url: str
    video_url: str
    author: str
    desc: str
    duration_ms: Optional[int]
    content_type: Optional[str]
    size_mb: Optional[float]
    video_url_source: str


@dataclass(frozen=True)
class CompletionResult:
    output_text: str
    raw_response: dict[str, Any]
    usage: Optional[dict[str, Any]]
    status_code: Optional[int]
    attempted_video_urls: tuple[str, ...] = ()
    error_type: str = ""
    error_message: str = ""
    api_error_code: str = ""
    api_error_type: str = ""
    api_error_message: str = ""
    request_id: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.output_text.strip()) and not self.error_type


@dataclass(frozen=True)
class KnowledgeResult:
    task: KnowledgeTask
    video: Optional[VideoSource]
    prompt: str
    completion: CompletionResult

    @property
    def ok(self) -> bool:
        return self.video is not None and self.completion.ok


@dataclass(frozen=True)
class CategoryExport:
    category_slug: str
    category_name: str
    product_slug: str
    product_name: str
    output_path: Path
    index_path: Path
    category_index_path: Path
    task_count: int
    document_count: int
    cumulative_task_count: int
    category_document_count: int
    category_task_count: int
    category_product_count: int


@dataclass(frozen=True)
class KnowledgeBuildReport:
    source_file: Path
    total_task_count: int
    unique_task_count: int
    executed_results: tuple[KnowledgeResult, ...]
    skipped_existing_tasks: tuple[KnowledgeTask, ...]
    skipped_duplicate_tasks: tuple[KnowledgeTask, ...]
    run_id: str
    history_file: Path
    run_log_path: Path
    output_markdown_path: Path
    category_exports: tuple[CategoryExport, ...]
    snapshot_path: Path

    @property
    def executed_count(self) -> int:
        return len(self.executed_results)

    @property
    def success_count(self) -> int:
        return sum(1 for result in self.executed_results if result.ok)

    @property
    def failure_count(self) -> int:
        return sum(1 for result in self.executed_results if not result.ok)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped_existing_tasks) + len(self.skipped_duplicate_tasks)

    @property
    def output_markdown_paths(self) -> tuple[Path, ...]:
        return tuple(item.output_path for item in self.category_exports)
