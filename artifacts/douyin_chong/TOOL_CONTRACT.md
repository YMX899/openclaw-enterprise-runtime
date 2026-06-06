# douyin_chong Tool Contract

Status: draft placeholder. The real tool contract is not supplied.

## Planned Invocation Shape

The local wrapper currently allows only a fixed no-shell invocation:

```text
<douyin_chong_binary>
  --input-url <canonical_video_url>
  --output-json <temporary_result_json>
  --max-bytes <max_download_bytes>
  --max-duration-seconds <max_video_duration_seconds>
  --max-frames <max_video_frames>
  --no-shell
```

This exact shape must be confirmed against the real artifact. If the real tool
uses different arguments, update the wrapper and tests before any server
deployment.

## Required Result Shape

The committed result schema is:

```text
openclaw-video/schemas/video-analysis-result.schema.json
```

Minimum fields:

```text
schema_version = openclaw-video-result.v1
source.platform = douyin
source.video_url_canonical
summary
signals
created_at
```

## Required Error Contract

The real tool must map failures into safe user-facing codes:

```text
url_rejected
download_failed
duration_limit_exceeded
content_type_rejected
tool_timeout
tool_failed
result_schema_invalid
temporary_storage_exhausted
```

Internal stack traces, cookies, tokens, local filesystem paths and raw request
headers must not be returned to users.
