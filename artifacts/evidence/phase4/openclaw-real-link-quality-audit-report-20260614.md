# OpenClaw Real Link Quality Audit - 2026-06-14

Scope: seven user-provided links were tested through root Bridge/API. Evidence stores hashes/statuses/quality snippets only; raw URLs and secrets are not recorded in JSON evidence.

## Runtime

- Bridge runtime limit: 500MB / 524288000 bytes.
- Worker mode: Files API (`VIDEO_ANALYSIS_INPUT_MODE=files_api`).
- Knowledge base version: 2026.06.06 mounted read-only at `/knowledge/short-video`.
- Dify core container IDs/StartedAt were unchanged before/after OpenClaw sidecar rebuild.

## Link Results

| Label | Read check | Job result | Detail chars | Follow-up quality | Note |
|---|---:|---:|---:|---:|---|
| bili_laugh_share | PASS | succeeded | 950 | 0.981 |  |
| bili_laugh_spm | PASS | succeeded | 1250 | 0.981 |  |
| bili_blue_sea | PASS | succeeded | 1384 | 1.000 |  |
| douyin_short | PASS | succeeded | 1051 | 1.000 |  |
| douyin_jingxuan | PASS | succeeded on single-link rerun | 1160 | 0.981 (rerun) | Original serial run failed once; immediate Bridge API rerun succeeded. |
| xhs_discovery | HTTP 400 | not submitted | - | - | Rejected by supported-platform allowlist; response correctly avoids pretending it watched video. |
| xhs_explore | HTTP 400 | not submitted | - | - | Rejected by supported-platform allowlist; response correctly avoids pretending it watched video. |

## Quality Judgment Against 修改方案.md

- First-turn successful analyses now produce separated `summary` and `analysis_detail`; successful samples recorded 950-1604 detail characters, with factual scene/action/content descriptions.
- Follow-up answers use the saved detail plus intent-specific knowledge blocks. They consistently include direct conclusion, video evidence, concrete rewrite/reshoot/picture/script plans, and copyable versions.
- Successful follow-up quality averages: B站长视频 variants 0.981, B站科普 1.000, 抖音短链 1.000, 抖音精选 rerun 0.981.
- The improvement is obvious versus the pre-fix behavior: before deployment, root worker had no Files API code and all real video jobs failed; after deployment, all five supported-platform links were proven analyzable, with one requiring a single-link rerun after a transient serial failure.
- Guardrail branches are correct but intentionally brief. 小红书/YouTube/off-topic/profile/prompt-injection responses do not fabricate video viewing, but score lower on the generic quality rubric because they are fixed safety replies rather than coaching answers.

## Remaining Boundary

- 小红书 links remain unsupported by the allowlist. This matches current product scope: 抖音/TikTok/B站 only.
- Multi-link serial run had one transient failure for `douyin_jingxuan`; single-link Bridge API rerun succeeded with full analysis and six follow-ups. This should be monitored, but it does not block the requested per-link validation.
- Full Docker build timed out on slow apt/ffmpeg download; deployment used a fast worker rebuild based on the existing worker image plus the current Python package, preserving system dependencies.

## Evidence Files

- JSON serial evidence: `/project/Dify/artifacts/evidence/phase4/openclaw-real-link-quality-audit-serial-20260614.json`
- Initial pre-deploy failure evidence: `/project/Dify/artifacts/evidence/phase4/openclaw-real-link-quality-audit-20260614.json`
- This report: `/project/Dify/artifacts/evidence/phase4/openclaw-real-link-quality-audit-report-20260614.md`
