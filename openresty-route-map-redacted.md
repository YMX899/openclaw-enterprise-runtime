# OpenResty Route Map Redacted

Audit time: 2026-06-06 01:29 Asia/Shanghai  
Container: `openresty-prod`  
Mode: read-only route summary. TLS private key contents and full configuration bodies were not read into this file.

## Container Baseline

```text
container: openresty-prod
image: openresty/openresty:1.29.2.5-0-alpine
network: host
public listeners observed: 0.0.0.0:80, 0.0.0.0:443
```

Syntax check:

```text
nginx: the configuration file /usr/local/openresty/nginx/conf/nginx.conf syntax is ok
nginx: configuration file /usr/local/openresty/nginx/conf/nginx.conf test is successful
```

## Mounts

```text
/app/config/openresty/conf -> /usr/local/openresty/nginx/conf type=bind
/app/logs/openresty       -> /app/logs/openresty type=bind
/app/apps/html            -> /app/apps/html type=bind
/app/data/cache           -> /app/data/cache type=bind
/app/data/upload          -> /app/data/upload type=bind
/app/test/logs/openresty  -> /app/test/logs/openresty type=bind
/app/test/apps/html       -> /app/test/apps/html type=bind
/app/test/data/cache      -> /app/test/data/cache type=bind
/app/test/data/upload     -> /app/test/data/upload type=bind
/etc/localtime            -> /etc/localtime type=bind
```

## Include Structure

Observed from redacted runtime summary:

```text
nginx.conf includes ./conf.d/*.conf
nginx.conf includes ./conf.d/*.main
```

Config root files:

```text
/app/config/openresty/conf/nginx.conf
/app/config/openresty/conf/fastcgi.conf
/app/config/openresty/conf/conf.d/default.conf
/app/config/openresty/conf/conf.d/adm.huahuoai.com.conf
/app/config/openresty/conf/conf.d/ai001.huahuoai.com.conf
/app/config/openresty/conf/conf.d/huahuoai.com.conf
/app/config/openresty/conf/conf.d/test.conf
/app/config/openresty/conf/conf.d/test.huahuoai.com.common
/app/config/openresty/conf/conf.d/testadm.huahuoai.com.common
/app/config/openresty/conf/conf.d/upstream.conf
```

Selected SHA256 values:

```text
cd6c8b1e07101d718d075b180a4cdf77a94d9e7925b1dae1b2ce226f42ed69ec  /app/config/openresty/conf/nginx.conf
6541ee6f5bbc777c7cf72ba5a078341e58af43d82ba5bbde6fad980f253653ce  /app/config/openresty/conf/conf.d/ai001.huahuoai.com.conf
3990336ee67ac22497c200231c23f18963dad25288ce70bae610b5ad927b8c19  /app/config/openresty/conf/conf.d/upstream.conf
```

## Public Dify Host Route

Observed route summary:

```text
server_name ai001.huahuoai.com
listen 443 ssl
location ^~ /
proxy_pass http://dify-master/
```

Upstream summary:

```text
upstream dify-master
```

Earlier inspection established Dify internal Nginx is on host `127.0.0.1:8081` via `docker-nginx-1`. The `dify-master` upstream must be treated as the current public Dify entry path and preserved.

## Other Hostnames Observed

```text
adm.huahuoai.com
ai001.huahuoai.com
huahuoai.com
www.huahuoai.com
test.huahuoai.com
testadm.huahuoai.com
```

No OpenClaw route was observed in the redacted route summary.

## Future OpenClaw Route Recommendation

Do not modify Dify compose or Dify Nginx for V1.

Future route should be isolated to two prefixes under the existing public host:

```text
/openclaw-lab/
/openclaw-api/
```

Target shape:

```text
openresty-prod
  /openclaw-lab/ -> http://127.0.0.1:18181
  /openclaw-api/ -> http://127.0.0.1:18181
```

Important constraints:

- Add through a separate include file, not by hand-editing broad route blocks.
- Keep original Dify routes unchanged.
- Confirm exact OpenResty include order before adding any route.
- Confirm slash behavior for `proxy_pass` in a staging or dry-run config test before reload.
- Do not reload OpenResty until OpenClaw Bridge is bound to `127.0.0.1:18181` and Dify public baseline is captured.
- Do not expose OpenClaw Gateway directly.

## Future Rollback Requirements

Before future route changes:

```text
1. Save SHA256 of all touched config files.
2. Copy the original config to a timestamped backup path.
3. Add OpenClaw route in a small dedicated include.
4. Run syntax check.
5. Run public browser Dify baseline before reload.
6. Reload only after approval.
7. If rollback is needed, remove the OpenClaw include and reload OpenResty.
8. Confirm /signin, /apps, and an existing Dify app flow from a real browser.
```

Current status:

```text
OpenResty route-map discovery: PASS
OpenClaw route present: NO
Safe to add route now: NO, OpenClaw/Bridge artifacts are missing
```

## Refresh 2026-06-06 10:38 Asia/Shanghai

Mode: read-only Docker inspect through `ssh-skill`; full OpenResty config,
certificate private keys and secret material were not read.

Mount summary:

```text
/app/data/upload       -> /app/data/upload                    type=bind rw=True
/app/data/cache        -> /app/data/cache                     type=bind rw=True
/app/test/data/upload  -> /app/test/data/upload               type=bind rw=True
/app/test/apps/html    -> /app/test/apps/html                 type=bind rw=True
/app/logs/openresty    -> /app/logs/openresty                 type=bind rw=True
/app/apps/html         -> /app/apps/html                      type=bind rw=True
/app/test/logs/openresty -> /app/test/logs/openresty          type=bind rw=True
/etc/localtime         -> /etc/localtime                      type=bind rw=False
/app/config/openresty/conf -> /usr/local/openresty/nginx/conf type=bind rw=True
/app/test/data/cache   -> /app/test/data/cache                type=bind rw=True
```

No OpenClaw route was added. Safe-to-add-route remains `NO` because the
Bridge/OpenClaw sidecar has not passed isolated Linux Docker and real-browser
Dify baseline gates.
