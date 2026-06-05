# Short Video Knowledge Base Artifact

Status: Phase 1 offline artifact. This is not a production deployment approval.

## Version

```text
artifact: knowledge-base-short-video
version: 2026.06.06
source_workspace_commit: 0a8cf11
mount_path: /knowledge/short-video
mount_mode: read-only
```

## Purpose

This artifact packages the short-video domain knowledge used by the OpenClaw x
Dify sidecar. It must be mounted read-only and treated as shared product
knowledge, not as per-user memory.

## Files

| File | SHA256 |
|---|---|
| `爆款短视频制作与分析知识库.md` | `9ae56c361bd5873a972ade5d463916b0e341c15aeba34f2baccbf928c2f7556c` |
| `爆款视频制作流程.pdf` | `edfd870697adaa440c756cdee6fefe885936f595f421e87bba1e112bb479d0cf` |
| `爆火视屏回答模版.txt` | `cf58338f9963f3c9f339a953671c9b13ac86bbb4741798f6cd12461108c0fcb1` |
| `短视频画面设计方法论.md` | `9f0410853b9b28a05755a6e854b99100cb5ecfc429fc02a5bec0308613715791` |

The authoritative checksum list is `SHA256SUMS`.

## Deployment Contract

- Mount this exact directory at `/knowledge/short-video:ro`.
- Runtime services must not write to this directory.
- User memory, sessions, jobs and results must stay in Bridge-owned storage and
  must not be written into this artifact.
- Any content update must create a new version directory and a new git commit.
- The running UI/API should expose the knowledge-base version before controlled
  trial so test evidence can prove which artifact was used.

## Verification

Windows workstation:

```powershell
.\scripts\verify_knowledge_base_artifact.ps1
```

Linux or isolated Docker host:

```bash
scripts/verify_knowledge_base_artifact.sh
```

No secrets, cookies, tokens, model keys, Dify database credentials or Redis
credentials are required for this verification.
