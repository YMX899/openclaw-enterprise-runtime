# Dify Public Baseline

Audit time: 2026-06-06 01:30 Asia/Shanghai  
Target public host: `https://ai001.huahuoai.com`  
Mode: Phase 0 real browser and non-mutating HTTP checks.

## Summary

The Dify sign-in page is reachable from the local Chrome browser. Unauthenticated `/apps` redirects to `/signin`, which is expected. A direct browser navigation to `/console/api/account/profile` was blocked by the browser client as `net::ERR_BLOCKED_BY_CLIENT`; internal Dify API checks still show unauthenticated profile requests return `401`, which is expected.

Server-side `curl` from the root server to the same public HTTPS host returned `403 Forbidden` from OpenResty, while the user's Chrome browser could load the sign-in page. This confirms that real browser testing must be part of every future acceptance and rollback run; server-side curl alone is not a reliable substitute for public browser behavior.

## Real Chrome Browser Baseline

Browser route:

```text
https://ai001.huahuoai.com/signin
```

Observed:

```text
title: Dify
url: https://ai001.huahuoai.com/signin
visible page: Dify login page
browser console errors/warnings: none captured
```

Visible DOM markers:

```text
Dify logo
登录 Dify
👋 欢迎！请登录以开始使用。
邮箱 input
密码 input
忘记密码？
登录 button disabled before credentials
设置管理员账户 link
© 2026 LangGenius, Inc. All rights reserved.
```

Browser route:

```text
https://ai001.huahuoai.com/apps
```

Observed:

```text
finalUrl: https://ai001.huahuoai.com/signin
title: Dify
visible page: Dify login page
```

Interpretation:

- Without an authenticated Dify session, `/apps` redirects to `/signin`.
- This matches expected unauthenticated behavior and should be used as the pre-login baseline.

Browser route:

```text
https://ai001.huahuoai.com/console/api/account/profile
```

Observed from direct tab navigation:

```text
net::ERR_BLOCKED_BY_CLIENT
```

Interpretation:

- The browser automation layer blocked direct navigation to the API route.
- Do not use this browser navigation failure as a Dify failure signal.
- Internal API checks still confirm profile returns `401` without login.

Screenshot note:

- A screenshot capture attempt timed out at the browser automation layer.
- DOM and title/URL checks succeeded.
- Future acceptance runs should save screenshots using a more stable browser capture path or manual screenshot if the automation capture remains slow.

## Internal Dify Nginx Baseline

From the root server against internal Dify Nginx:

```text
http://127.0.0.1:8081
  -> 307 Temporary Redirect
  -> location: /apps

http://127.0.0.1:8081/apps
  -> 200 OK
  -> Content-Type: text/html; charset=utf-8
  -> X-Powered-By: Next.js

http://127.0.0.1:8081/signin
  -> 200 OK
  -> Content-Type: text/html; charset=utf-8
  -> X-Powered-By: Next.js

http://127.0.0.1:8081/console/api/account/profile
  -> 401 UNAUTHORIZED
  -> message: Invalid Authorization token
  -> X-Version: 1.11.2
  -> X-Env: PRODUCTION
```

From inside `docker-api-1`:

```text
http://127.0.0.1:5001/console/api/account/profile
  -> 401 UNAUTHORIZED
  -> message: Invalid Authorization token
  -> X-Version: 1.11.2
  -> X-Env: PRODUCTION
```

Interpretation:

- Dify internal web and API routing are functional for unauthenticated baseline checks.
- `401` for profile without login is correct.

## Public Host Curl Baseline from Server

From the root server:

```text
https://ai001.huahuoai.com/signin
  -> 403 Forbidden
  -> Server: openresty

https://ai001.huahuoai.com/apps
  -> 403 Forbidden
  -> Server: openresty

https://ai001.huahuoai.com/console/api/account/profile
  -> 403 Forbidden
  -> Server: openresty

https://ai001.huahuoai.com/api
  -> 403 Forbidden
  -> Server: openresty

https://ai001.huahuoai.com/v1
  -> 403 Forbidden
  -> Server: openresty
```

Interpretation:

- Public HTTPS checks from the server itself do not match real Chrome browser behavior.
- This may be due to OpenResty request filtering, source IP, missing browser headers, or other access controls.
- Future acceptance must use real browser checks for public UX.

## Authenticated Baseline Status

Authenticated baseline was not completed because no Dify login credentials were provided and no request was made to submit credentials.

Required before any future OpenClaw route is exposed:

```text
1. Log in to Dify in a real browser.
2. Open /apps.
3. Open at least one existing app.
4. Send a normal existing app message.
5. Confirm reply behavior.
6. Refresh the page.
7. Open existing history or app entry.
8. Sign out.
9. Record screenshots and error-log summaries without Cookie/Token/request-header capture.
```

## Go / No-Go

```text
Unauthenticated real browser Dify baseline: PASS
Internal Dify Nginx/API unauthenticated baseline: PASS
Server-side public curl baseline: NOT REPRESENTATIVE, returns 403
Authenticated Dify app baseline: BLOCKED, credentials/session not provided
```

Future OpenClaw public route work must not proceed past Phase 2 until authenticated real-browser Dify baseline is complete.

