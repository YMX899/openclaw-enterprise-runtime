# douyin_chong Tool Contract

Status: candidate adapter draft. A local candidate Python package has been
found, but it is not production verified.

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

In the sidecar compose draft, `<douyin_chong_binary>` is:

```text
/usr/local/bin/openclaw-douyin-adapter
```

The adapter adds an explicit secret file argument only when configured:

```text
--env-file /run/secrets/douyin_chong_env
```

The adapter imports the candidate Python package from `DOUYIN_CHONG_PYTHONPATH`
and must not read the candidate project's default `.env`, `.env.local`, browser
storage state, cookies, token files or runtime outputs. Runtime credentials must
be mounted as a read-only secret file and must not be committed.

This exact shape is validated as the current link-read runtime path. The worker
accepts a user-provided video link, validates and canonicalizes the URL, and
uses the resolver to find direct video URL candidates. A Douyin account login or
browser storage state is not part of the runtime contract.

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

## Current Real Analysis Evidence

`REAL_SAMPLE_EVIDENCE.json` is no longer required by the production readiness
gate after the 2026-06-07 link-read scheme change. The old standalone
real-sample runner has been removed so future work does not reintroduce the
retired sample gate. Refresh real model-backed evidence through the deployed
OpenClaw page/API when an explicit test video URL is available.

Committed evidence should record only sanitized metadata:

```text
input_url_sha256
input_url_host
root release
worker image/container identity
elapsed seconds
result schema version
summary length
result JSON SHA256
result JSON size
model_invoked = true
secret_file_contents_recorded = false
stdout/stderr contents recorded = false
```

It must not print or commit the runtime secret file, raw headers, cookies,
Authorization values, CSRF values, or full model output. The generated output
must stay under `tmp/` unless it is sanitized first. Do not promote evidence
into a committed `REAL_SAMPLE_EVIDENCE.json` gate file; the current production
path is the OpenClaw-owned login plus video link-read workflow.
