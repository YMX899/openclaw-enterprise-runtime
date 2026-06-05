# Video Tool Inventory

Audit time: 2026-06-06 01:29 Asia/Shanghai  
Scope: root server and local workspace inventory for `douyin_chong` or equivalent video analysis tool.

## Summary

No deployable video analysis tool was found.

This blocks the video-analysis worker and prevents Phase 1 from producing a deployable system. The current documents mention a command shape similar to `python -m douyin_chong`, but the actual code, dependencies, input contract, output contract, and runtime profile were not found.

## Server Search Results

Search roots:

```text
/app/bin
/opt
/app
```

Search patterns:

```text
*douyin*
*chong*
*tik*
*video*analysis*
*video_analy*
```

Result:

```text
No matching server paths found.
```

Docker images:

```text
No image repository/tag matching douyin, chong, tik, video, or analysis found.
```

Docker containers:

```text
No container name or image matching douyin, chong, tik, video, or analysis found.
```

## Local Workspace Search Results

Workspace:

```text
D:\DESK\Dify
```

Planning documents mention:

```text
douyin_chong
python -m douyin_chong --limit 1 --fps 4 --max-tokens 12000 --workers 1
OpenClaw subprocess call
Ark multimodal analysis
video analysis worker
```

No deployable local `douyin_chong` package, video analysis source tree, Dockerfile, or requirements file was found in this workspace.

## Required Artifact Gate for Phase 1

The following must be provided before worker implementation can continue:

```text
video analysis source directory or repository
tool version or Git commit
runtime language and version
dependency manifest
Dockerfile or build instructions
exact command-line entrypoint
accepted input parameters
valid URL forms
output directory structure
machine-readable JSON output schema
Markdown output format, if any
error codes
timeout behavior
temporary file behavior
cleanup behavior
average runtime
worst-case runtime
CPU usage
memory usage
disk usage
network access requirements
API key requirements, with names only and no secret values
```

## Worker Contract Required

The worker must expose a fixed, service-controlled interface, not arbitrary shell execution.

Recommended worker input:

```json
{
  "job_id": "uuid",
  "owner_principal_id": "hmac-id",
  "bridge_session_id": "uuid",
  "video_url": "https://www.douyin.com/video/...",
  "analysis_mode": "user_video",
  "limits": {
    "fps": 4,
    "max_tokens": 12000,
    "timeout_seconds": 900,
    "max_download_bytes": 524288000,
    "max_duration_seconds": 600
  }
}
```

Recommended worker output:

```json
{
  "job_id": "uuid",
  "status": "succeeded",
  "result_schema_version": "v1",
  "raw_markdown": "...",
  "structured": {
    "summary": "...",
    "hook_analysis": "...",
    "content_structure": "...",
    "visual_analysis": "...",
    "actionable_revisions": []
  },
  "artifacts": {
    "frames": [],
    "metadata_path": null
  }
}
```

Failure output:

```json
{
  "job_id": "uuid",
  "status": "failed",
  "error_code": "DOUYIN_PARSE_FAILED",
  "safe_user_message": "这个链接暂时无法解析，请换成抖音单条视频页链接。",
  "internal_error_ref": "log-ref-without-secret"
}
```

## Required Security Controls

Before the worker runs on the root server:

```text
Run as non-root user.
Use fixed command wrapper.
Never pass user input to shell without strict validation.
Whitelist supported domains.
Re-check URL after redirects.
Reject private, loopback, link-local, multicast, and cloud metadata IP ranges.
Set max download size.
Set max video duration.
Set max extracted frames.
Set task timeout.
Set container memory/CPU/PID limits.
Do not mount Docker socket.
Do not mount Dify data directories.
Do not connect to Dify RDS.
Do not connect to Dify Redis.
Clean temporary files after completion.
Validate output against JSON Schema.
Do not log API keys, cookies, tokens, or full request headers.
```

## Current Go / No-Go

```text
Phase 0 inventory: GO
Phase 1 worker image build: BLOCKED
Phase 2 server-side worker deployment: NO-GO
Video job end-to-end test: NO-GO
```

Reason:

```text
No video analysis artifact was found.
```

