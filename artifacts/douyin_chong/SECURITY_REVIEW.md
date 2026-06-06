# douyin_chong Security Review

Status: minimal candidate source vendored, not model-verified.

## Candidate Location

```text
D:\DESK\视频解析\tik\douyin_chong
```

The sibling project contains `.env`, `.env.local` and `.douyin_storage_state*`
files. These are treated as sensitive runtime material and must not be read,
copied, committed, uploaded, logged or deployed by Codex.

A minimal V1 source subset has been vendored under
`openclaw-video/vendor/douyin_chong`, limited to config/models and
`clients/{ark_video,douyin,tiktok,resolver}`. Browser login-state utilities,
batch profile exporters, generated exports, caches and runtime outputs are not
included.

## Current Safety Decisions

- V1 single-video worker must use the sidecar adapter
  `openclaw-douyin-adapter`; direct execution of the candidate CLI is not a
  production-approved interface.
- The adapter requires `--env-file` and will not rely on the candidate default
  `.env` path.
- The wrapper still invokes the adapter through a fixed argument list and
  `shell=False`.
- The worker mounts `./secrets/douyin_chong.env` read-only at
  `/run/secrets/douyin_chong_env`; the secret file is git-ignored.
- The candidate profile/batch paths may use browser storage state and are not
  approved for V1 production.

## Remaining Security Gates

- Prove the vendored minimal candidate source with a real model-backed
  single-video run under Linux Docker.
- Pin dependencies and produce an archive SHA256 or image digest.
- Prove the adapter works with real runtime credentials without logging secrets.
- Prove SSRF, redirect, duration, size, frame, timeout and temp cleanup gates in
  an isolated Linux Docker host.
- Decide OpenClaw `2026.3.13` npm audit/security exception separately.

Status: unresolved. Production use is No-Go until this file is completed.

## Required Review Areas

- SSRF resistance.
- redirect revalidation.
- DNS rebinding handling.
- maximum download size.
- maximum video duration.
- maximum frame count.
- network egress destinations.
- temporary file cleanup.
- non-root execution.
- read-only root filesystem compatibility.
- CPU, memory and PID limits.
- no Docker socket.
- no Dify credentials.
- no shell command construction from user input.
- JSON schema validation.

## Approval

```text
security_owner:
engineering_owner:
decision_date:
decision:
```
