# douyin_chong Artifact Manifest

Status: minimal candidate source vendored, not model-verified. This file is a
production gate, not a deployment approval.

A local candidate Python package was found at:

```text
D:\DESK\视频解析\tik\douyin_chong
```

The candidate is not yet production verified. It depends on explicit Ark model
credentials and its default commands read a project `.env`; Codex did not read,
copy, commit or deploy that `.env`, `.env.local`, `.douyin_storage_state*`, or
any browser/session state files. The production worker must use only a runtime
secret file mounted at `/run/secrets/douyin_chong_env`.

Current local non-secret checks:

```text
python -m douyin_chong --help                              OK
python -m douyin_chong.video_action_extract --help         OK
python -m douyin_chong.video_fashion_extract --help        OK
python -m compileall -q douyin_chong                       OK
dependency imports: httpx, requests, volcenginesdkarkruntime, PIL, cv2, playwright OK
```

Clean source intake:

```text
vendored path: openclaw-video/vendor/douyin_chong
source scope:
  douyin_chong/__init__.py
  douyin_chong/config.py
  douyin_chong/models.py
  douyin_chong/clients/__init__.py
  douyin_chong/clients/ark_video.py
  douyin_chong/clients/douyin.py
  douyin_chong/clients/resolver.py
  douyin_chong/clients/tiktok.py
excluded:
  .env, .env.local, .douyin_storage_state*.json, __pycache__, *.pyc, *.log,
  JSON/HTML capture outputs, Playwright login-state utilities, batch profile
  exporters, cover/image workflows, generated exports and history stores.
adapter import check: OK through DOUYIN_CHONG_PYTHONPATH=/app/vendor
source hash manifest: openclaw-video/vendor/douyin_chong/SOURCE_SHA256SUMS
```

Candidate git state:

```text
repository: D:\DESK\视频解析\tik
HEAD: 53ba64e
branch: main
note: candidate worktree is dirty; generated/runtime files and untracked
      storage state are present and must not be copied into this repository.
```

The OpenClaw sidecar now includes an adapter entry point:

```text
openclaw-douyin-adapter
```

This adapter requires:

```text
--input-url
--output-json
--max-bytes
--max-duration-seconds
--max-frames
--env-file
--no-shell
```

It imports the candidate package through `DOUYIN_CHONG_PYTHONPATH=/app/vendor`,
enforces duration, size and frame limits from candidate metadata, calls the
candidate Ark video analyzer, and writes the committed `openclaw-video-result.v1`
JSON schema. The clean candidate source is mounted read-only at
`/app/vendor/douyin_chong`.

## Required Evidence Before Phase 2

- real model-backed execution through the vendored minimal source using only
  the explicit runtime secret file.
- verification that the vendored minimal source is sufficient for the V1
  single-video path under Linux Docker.
- archive or image digest for the exported candidate after Linux Docker
  validation. The vendored source subset already has
  `SOURCE_SHA256SUMS`, but that is not a deployable image digest.
- license and production-use permission.
- runtime language and version.
- dependency lockfile or pinned requirements.
- exact adapter command entrypoint.
- required runtime secret file format without revealing secret values.
- confirmation that browser state, cookies, proxy credentials and Dify secrets
  are not required for the V1 single-video path.
- expected network destinations.
- input schema.
- output JSON schema.
- error code contract.
- average runtime per video.
- maximum runtime per video.
- CPU, memory and disk profile.
- temporary file path.
- cleanup behavior.
- sample success output.
- sample failed output.
- isolated Linux Docker validation through `scripts/verify_phase1_5_gates.sh`
  without skipping Docker.

The committed helper for producing sanitized real-sample evidence is:

```text
scripts/run_douyin_real_sample.py
```

This helper is not itself production approval. It is a controlled way to
produce the missing real model-backed sample, schema, timing and resource
evidence without recording secrets.

## Production Constraints

- The tool must run in a dedicated non-root worker container.
- The worker must not mount the Docker socket.
- The worker must not mount Dify directories.
- The worker must not receive Dify RDS, Redis, Cookie, or Gateway secrets.
- Invocation must use a fixed argument list with no shell string assembly.
- Output must be validated against the committed JSON schema.
