# Ubuntu 22.04 Dify Browser Baseline

Audit time: 2026-06-06 19:15 Asia/Shanghai
Target host: `ubuntu22.04`
Base URL: `http://192.168.206.130:8088`
Mode: non-mutating Dify baseline after Phase 1.5 isolated OpenClaw validation.

## Server Facts

```text
Dify Nginx container: dify_v1110_a8be-nginx-1
Nginx port mapping: 0.0.0.0:8088 -> 80/tcp
Dify Web container: dify_v1110_a8be-web-1
Dify API container: dify_v1110_a8be-api-1
Dify version: 1.11.2
Dify network: dify_v1110_a8be_default
```

All checks below avoided reading cookies, authorization headers, CSRF tokens,
full `.env` files, database connection strings, Redis credentials, private
keys, and model API keys.

## Server-Side HTTP Baseline

From `ubuntu22.04` against `127.0.0.1:8088`:

```text
GET / -> 307 redirect to /apps
GET /signin -> 200, body bytes 23226
GET /apps -> 200, body bytes 50506
GET /console/api/account/profile -> 401, body bytes 78
```

Recent Dify log error scan:

```text
dify_v1110_a8be-nginx-1: no recent error/exception/traceback/5xx summary
dify_v1110_a8be-web-1: no recent error/exception/traceback/5xx summary
dify_v1110_a8be-api-1: no recent error/exception/traceback/5xx summary
```

## Real Chrome Browser Baseline

Route:

```text
http://192.168.206.130:8088/signin
```

Observed:

```text
finalUrl: http://192.168.206.130:8088/signin
title: Dify
visible page: Dify login page
browser console errors: none captured
```

Visible DOM markers:

```text
简体中文
登录 Dify
欢迎
邮箱
密码
忘记密码？
登录
设置管理员账户
© 2026 LangGenius, Inc. All rights reserved.
```

Route:

```text
http://192.168.206.130:8088/apps
```

Observed:

```text
finalUrl: http://192.168.206.130:8088/signin
title: Dify
visible page: Dify login page
browser console errors: none captured
```

Interpretation:

```text
Unauthenticated /apps redirects to /signin in the real browser, which is acceptable for this Dify policy.
```

Route:

```text
http://192.168.206.130:8088/console/api/account/profile
```

Observed from direct Chrome navigation:

```text
net::ERR_BLOCKED_BY_CLIENT
```

Interpretation:

```text
The Chrome automation layer blocks direct API-path navigation. This is not treated as a Dify failure.
Server-side HTTP baseline confirms the unauthenticated profile endpoint returns 401, which is expected.
```

## Post-Phase 1.5 Cleanup

After the OpenClaw Phase 1.5 validation run:

```text
OpenClaw sidecar containers: none remaining
Test listeners on 18181/18789/5432: none remaining
Dify containers: still running
OpenClaw compose down --remove-orphans --volumes: PASS
```

## Status

```text
Ubuntu 22.04 unauthenticated real-browser Dify baseline: PASS
Ubuntu 22.04 server-side Dify HTTP/API baseline: PASS
Authenticated Dify app conversation baseline: NOT RUN
```

Authenticated Dify app testing remains required before any production public
OpenClaw route exposure. It requires a real logged-in Dify session, opening an
existing app, sending a normal message, confirming reply behavior, refreshing
the page, and checking history/entry navigation without recording cookies,
tokens, CSRF values, or full request headers.
