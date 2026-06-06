# Phase 4 Huahuo Front Identity Plan - 2026-06-07

## Correction

The real user-facing Dify/Huahuo web surface for this project is:

```text
https://www.huahuoai.com/ai/?id=4
```

The Dify console URL below is an administration surface and must not be used as the main user-web regression evidence:

```text
https://ai001.huahuoai.com/app/d44c1add-5043-4b33-b513-1d4f6ec3b4f0/configuration
```

## Browser Evidence

Chrome logged-in user-web test passed:

- Page: `https://www.huahuoai.com/ai/?id=4`
- Test message: `浏览器回归测试：请回复“收到”。`
- Result: message appeared in a new conversation and the bot produced a visible reply.
- Console-level page check: no visible page error was observed during the interaction.

OpenClaw Lab public-port test:

- `https://ai001.huahuoai.com:18443/openclaw-lab/` loads.
- `https://www.huahuoai.com:18443/openclaw-lab/` loads.
- Both currently show `Login Required` because Huahuo frontend login uses `localStorage` tokens on `www.huahuoai.com`, not cookies shared with `ai001.huahuoai.com:18443`.

## Identity Finding

Huahuo frontend stores:

```text
Access-Token
Refresh-Token
APP-UUID
```

in browser `localStorage`.

The frontend builds:

```text
Authorization: Bearer base64(appVersion=1.0.1&appType=WEB&appUuid=...&appTime=...&appSign=...&token=Access-Token)
```

and calls:

```text
GET /api/front/user/queryUserInfo
```

Unauthenticated direct access to this endpoint returns `401`, which is suitable for Bridge login validation.

## Implementation Direction

Bridge now supports a new identity provider:

```text
BRIDGE_IDENTITY_PROVIDER=huahuo_front
HUAHUO_FRONT_BASE=https://www.huahuoai.com
HUAHUO_FRONT_TENANT_ID=huahuo-front
```

Lab page behavior:

- If served under `https://www.huahuoai.com/openclaw-lab/`, it can read the existing Huahuo `Access-Token` from same-origin `localStorage`.
- It sends only `X-Huahuo-Access-Token` to Bridge.
- Bridge converts that token to the same signed Huahuo Authorization shape and calls `/api/front/user/queryUserInfo`.
- Bridge derives an HMAC principal and never returns the raw Huahuo user id.
- Gateway token and model key are still not exposed to the browser.

## Routing Direction

Keep the independent `18443` route for isolated smoke tests.

Add same-origin `443` prefixes only for real logged-in user tests:

```text
/openclaw-lab/
/openclaw-api/
```

The same-origin installer uses a marked OpenResty block and can be rolled back by removing only that block. It must not alter `/ai`, login, chat, or other Huahuo/Dify paths.

## Current Gate

Development gate is relaxed for velocity, but each deployment must still prove:

- Huahuo user web `/ai/?id=4` still sends and receives messages.
- OpenClaw Lab same-origin page authenticates with the current Huahuo login.
- Upload job can be created from Chrome using a local sample video.
- Dify/Huahuo original user web remains functional after OpenClaw deployment.
- OpenClaw route rollback does not restart or rebuild original Dify/Huahuo services.

