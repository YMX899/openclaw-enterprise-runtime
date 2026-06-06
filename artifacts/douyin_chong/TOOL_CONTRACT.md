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

This exact shape still must be proven with the real candidate source exported
into the worker image and with real model credentials in an isolated Linux
Docker host before any server deployment.

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

## Real Sample Evidence Runner

Before the artifact can become production verified, run one real model-backed
sample in an isolated environment with an explicit runtime secret file:

```bash
python scripts/run_douyin_real_sample.py \
  --input-url '<douyin-single-video-url>' \
  --env-file /path/to/douyin_chong.env \
  --adapter-bin openclaw-douyin-adapter \
  --output-dir tmp/douyin-real-samples/<run-id>
```

The runner deliberately records only sanitized evidence:

```text
input_url_sha256
input_url_host
env_file_present = true/false
secret_file_contents_recorded = false
adapter return code
elapsed seconds
stdout/stderr character counts only
result schema version
summary length
result JSON SHA256
result JSON size
Linux child max_rss_kb when available
```

It must not print or commit the runtime secret file, raw headers, cookies,
Authorization values, CSRF values, or full model output. The generated output
directory is under `tmp/` by default and is ignored by git.

After the sanitized evidence has been reviewed, promote it into the committed
production-readiness evidence path only through the promotion script:

```bash
python scripts/promote_douyin_real_sample_evidence.py \
  --source tmp/douyin-real-samples/<run-id>/sanitized-run.json
```

The promotion script fails closed if the sample did not succeed, if the runtime
secret file was missing, if stdout/stderr contents were recorded, if a raw URL is
present, or if the result hash/schema evidence is missing. It also strips local
temporary output paths before writing:

```text
artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json
```
