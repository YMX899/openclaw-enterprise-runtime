# OpenClaw Video Sidecar

Status: Phase 1 offline artifact draft. Do not deploy to production until all
gates in `../phase1-artifact-gates.md` pass.

This directory defines the sidecar architecture for an independent
`/openclaw-lab/` page and `/openclaw-api/` API in front of OpenClaw `2026.3.13`.
It is intentionally separate from Dify Web and Dify compose.

## Components

- `openclaw-bridge`: browser-facing static page and API.
- `bridge-postgres`: product database for users, sessions, jobs and results.
- `openclaw-gateway`: private OpenClaw Gateway running OpenClaw `2026.3.13`.
- `video-analysis-worker`: asynchronous worker calling a fixed `douyin_chong`
  wrapper.

Only `openclaw-bridge` is allowed to join Dify's `docker_default` network, and
only to call Dify API identity endpoints. Gateway, worker and Postgres stay on a
private sidecar network and expose no public host ports.

## Current Gate

The source here is not production-ready until these external artifacts are
supplied and verified:

- actual `douyin_chong` binary/source/image.
- exact OpenClaw Gateway API contract for version `2026.3.13`.
- explicit security decision for npm audit findings affecting
  `openclaw@2026.3.13`.
- real Dify authenticated browser baseline.
- final ChatGPT web review captured in git.

## Local Unit Tests

The unit tests cover the pure safety logic and do not require server access:

```powershell
python -m unittest discover openclaw-video/tests
```

## Production Principle

No OpenClaw service may be deployed until this repository is clean, artifacts are
committed, generated image digests are recorded, and rollback has been tested in
a non-production or no-op mode.

