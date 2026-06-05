# ChatGPT Architecture Review Capture

Date: 2026-06-06 Asia/Shanghai

Source: Chrome tab `OpenClaw架构审查意见`

Mode: user-provided ChatGPT web session. Captured only rendered page text. No
cookies, request headers, tokens, browser storage, or secrets were read or
recorded.

## Captured Review Status

The completed first architecture review was captured from the ChatGPT page.

The follow-up prompt asking for an "执行前最终 Go/No-Go 复审" was visible on the
page, but the page still showed "正在思考" after waiting. A later fresh ChatGPT
conversation completed that final review; see `chatgpt-final-go-nogo-review.md`.

## Main Review Conclusions

ChatGPT's completed architecture review agrees with the current project gates:

- The business direction is conditionally reasonable, but the current state is
  not ready for direct production deployment.
- Dify should remain responsible for login and existing applications.
- Bridge should be the only browser-facing trusted adapter for identity, ACL,
  session projection, job state, and secret isolation.
- OpenClaw should remain private behind Bridge. Gateway tokens must not reach
  browser JavaScript or browser Network requests.
- `/channels/dify-web/*` must not be treated as a proven OpenClaw standard API;
  it is an adapter surface to implement or replace with a locked Gateway API
  contract.
- V1 should use `/openclaw-lab/` and `/openclaw-api/` as an independent
  same-origin sidecar, not direct Dify Web modification.
- Bridge V1 should not connect to Dify RDS. It should derive identity by calling
  Dify `profile` and `workspaces` APIs through the existing login state.
- Video analysis must be asynchronous job execution with polling recovery; SSE
  can be an enhancement but not the persistence mechanism.
- Initial worker concurrency should be `1` until real pressure tests prove Dify
  has enough resource margin.
- The existing `docker-web-1 unhealthy` state must be recorded as a baseline or
  fixed separately; it cannot be ignored.
- Because OpenClaw 3.13 artifacts, the Gateway API contract, and the real
  `douyin_chong` tool are not fully locked, production deployment remains
  No-Go.

## Production No-Go Gates Confirmed By Review

The review explicitly treats the following as blockers before production or
public route rollout:

- OpenClaw code/image/version/API contract must be locked.
- The actual video analysis tool must be located, versioned, tested, and given a
  fixed JSON schema and error contract.
- Bridge must pass user and tenant isolation tests.
- Gateway must not be publicly exposed.
- Browser must never receive Gateway tokens.
- Dify public login, `/apps`, existing app pages, and existing app message flow
  must pass real browser baseline and load regression tests.
- OpenResty route changes must be independently reversible without restarting
  Dify.
- Rollback must be rehearsed and must not require Dify container restart or
  rebuild.

## Current Implication

```text
Continue Phase 1 offline implementation: GO
Repeat Phase 0 read-only/public baseline checks when needed: GO
Deploy sidecar to server: NO-GO
Add public OpenResty route: NO-GO
Modify Dify Web or Dify compose: NO-GO
Claim "100% deployable without Dify impact": NO-GO until gates pass
```

