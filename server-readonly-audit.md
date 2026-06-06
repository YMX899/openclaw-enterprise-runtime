# Server Read-only Audit

Audit time: 2026-06-06 01:29 Asia/Shanghai  
Target SSH alias: root  
Host observed: AI-01  
Mode: Phase 0 only, read-only inspection. No deployment, restart, reload, install, or server file modification was performed.

## Executive Summary

The root server can continue Phase 0 planning and audit work, but it is not ready for OpenClaw deployment.

Key findings:

- Existing Dify 1.11.2 stack is running and reachable through the internal Dify Nginx on `127.0.0.1:8081`.
- Existing public Dify sign-in page is reachable from a real Chrome browser at `https://ai001.huahuoai.com/signin`.
- `docker-web-1` is reported as unhealthy because its healthcheck calls `pg_isready`, which is not available inside the container. The web page itself is reachable, so this must be recorded as a historical baseline or corrected in a separate Dify maintenance change.
- No OpenClaw code, image, container, Bridge service, or video analysis tool was found on the server.
- The current available memory is about 4.0 GiB and there is no swap. Video analysis must not be deployed without resource-limited worker testing.
- No Phase 1/2/3 deployment work should start until OpenClaw and video-tool artifacts are supplied and verified.

## System Baseline

```text
date: 2026-06-06T01:29:29+08:00
kernel: Linux AI-01 6.8.0-57-generic #59-Ubuntu SMP PREEMPT_DYNAMIC Sat Mar 15 17:40:59 UTC 2025 x86_64
os: Ubuntu 24.04.2 LTS
docker server: 28.1.1
docker compose: v2.35.1
cpu cores: 8
uptime: 378 days, 9:56
load average: 1.43, 2.28, 2.01
```

Memory:

```text
total: 14 GiB
used: 10 GiB
free: 997 MiB
available: 4.0 GiB
swap: 0 B
```

Storage:

```text
/app filesystem: /dev/vdb
size: 500G
used: 63G
available: 438G
use: 13%
```

## Container Resource Baseline

```text
NAME                         CPU %   MEM USAGE / LIMIT     PIDS
openresty-prod               0.00%   30.27MiB / 14.72GiB   2
docker-nginx-1               0.00%   9.859MiB / 14.72GiB   10
docker-api-1                 0.67%   4.326GiB / 14.72GiB   61
docker-worker-1              0.15%   296.8MiB / 14.72GiB   10
docker-worker_beat-1         0.00%   263.5MiB / 14.72GiB   17
docker-web-1                 2.51%   341.1MiB / 14.72GiB   34
docker-plugin_daemon-1       0.49%   1.236GiB / 14.72GiB   77
docker-sandbox-1             0.00%   506.7MiB / 14.72GiB   12
docker-ssrf_proxy-1          0.01%   18.11MiB / 14.72GiB   9
weaviate-weaviate-master-1   2.78%   161.6MiB / 14.72GiB   15
huahuo-ai-test               0.01%   341.7MiB / 14.72GiB   6
huahuo-web-test              0.06%   528.3MiB / 14.72GiB   46
huahuo-web-prod              0.05%   802.7MiB / 14.72GiB   46
mysql                        0.24%   708.6MiB / 14.72GiB   54
```

Resource note:

- `docker-api-1` is the largest memory consumer at about 4.326 GiB.
- Server has no swap.
- Any video-analysis worker must start with `worker_concurrency=1`, explicit CPU/memory/PID limits, and Dify parallel baseline testing.

## Dify Compose Baseline

Dify root:

```text
/app/bin/dify/dify-1.11.2/docker
```

Compose services:

```text
init_permissions
api
web
nginx
plugin_daemon
worker_beat
sandbox
ssrf_proxy
worker
```

Compose images:

```text
ubuntu/squid:latest
langgenius/dify-plugin-daemon:0.5.2-local
nginx:latest
langgenius/dify-web:1.11.2
langgenius/dify-api:1.11.2
langgenius/dify-sandbox:0.2.12
busybox:latest
```

Running Dify-related containers:

```text
docker-api-1             langgenius/dify-api:1.11.2                  Up 5 months
docker-nginx-1           nginx:latest                                Up 5 months
docker-plugin_daemon-1   langgenius/dify-plugin-daemon:0.5.2-local   Up 5 months
docker-sandbox-1         langgenius/dify-sandbox:0.2.12              Up 5 months (healthy)
docker-ssrf_proxy-1      ubuntu/squid:latest                         Up 5 months
docker-web-1             langgenius/dify-web:1.11.2                  Up 5 months (unhealthy)
docker-worker-1          langgenius/dify-api:1.11.2                  Up 5 months
docker-worker_beat-1     langgenius/dify-api:1.11.2                  Up 5 months
```

## Network Baseline

Containers in `docker_default`:

```text
docker-api-1
docker-nginx-1
docker-plugin_daemon-1
docker-ssrf_proxy-1
docker-web-1
docker-worker-1
docker-worker_beat-1
```

Selected aliases:

```text
docker-api-1   docker_default aliases=[docker-api-1 api]
docker-api-1   docker_ssrf_proxy_network aliases=[docker-api-1 api]
docker-web-1   docker_default aliases=[docker-web-1 web]
docker-nginx-1 docker_default aliases=[docker-nginx-1 nginx]
```

Implications:

- Future `openclaw-bridge` may join `docker_default` to reach `api:5001`.
- Future OpenClaw Gateway, worker, and Bridge Postgres should not join `docker_default` unless specifically required.
- OpenClaw Gateway and database ports must not be exposed to public interfaces.

## Port Baseline

Relevant listeners:

```text
0.0.0.0:80     openresty
0.0.0.0:443    openresty
0.0.0.0:8081   docker-proxy -> docker-nginx-1
0.0.0.0:8443   docker-proxy -> docker-nginx-1
0.0.0.0:5003   docker-proxy -> docker-plugin_daemon-1
0.0.0.0:5001   gunicorn / Dify API
```

OpenClaw reserved ports checked in the plan:

```text
18180: not observed in the filtered listener output
18181: not observed in the filtered listener output
18789: not observed in the filtered listener output
5432: not observed in the filtered listener output
6379: not observed in the filtered listener output
```

Recommended future Bridge binding:

```text
127.0.0.1:18181 -> openclaw-bridge:3000
```

Do not bind OpenClaw Gateway or Postgres to `0.0.0.0`.

## Dify Web Healthcheck Baseline

Healthcheck command:

```json
["CMD","pg_isready","-h","db_postgres","-U","dify","-d","dify"]
```

Recent health log exits:

```text
2026-06-06 01:28:53 +0800 -> exit=-1
2026-06-06 01:29:00 +0800 -> exit=-1
2026-06-06 01:29:08 +0800 -> exit=-1
2026-06-06 01:29:16 +0800 -> exit=-1
2026-06-06 01:29:23 +0800 -> exit=-1
```

Interpretation:

- `docker-web-1` is unhealthy because the healthcheck uses `pg_isready`.
- The deployed Dify uses cloud PostgreSQL RDS rather than the default local `db_postgres`; this healthcheck is stale for the current deployment shape.
- Browser and internal HTTP checks show the Dify web page is reachable.
- This is a historical baseline issue and must not be blamed on OpenClaw later.
- Do not fix it as part of OpenClaw Phase 0. If corrected later, handle as a separate Dify maintenance task.

## Dify Nginx Template Baseline

Template path:

```text
/app/bin/dify/dify-1.11.2/docker/nginx/conf.d/default.conf.template
```

## Read-only Refresh 2026-06-06 12:13 Asia/Shanghai

Mode: `ssh-skill` read-only commands only. No deployment, restart, reload,
install, file edit, `.env` read, full environment dump or secret output was
performed.

System and resource baseline:

```text
date: 2026-06-06T12:13:27+08:00
host: AI-01
kernel: Linux AI-01 6.8.0-57-generic #59-Ubuntu SMP PREEMPT_DYNAMIC Sat Mar 15 17:40:59 UTC 2025 x86_64
docker server: 28.1.1
docker compose: v2.35.1
cpu cores: 8
uptime: 378 days, 20:40
load average: 1.21, 1.16, 1.14
memory: 14Gi total, 11Gi used, 976Mi free, 3.7Gi available
swap: 0B
/app: 500G size, 63G used, 438G available, 13% used
```

Container resource baseline:

```text
openresty-prod               0.00% CPU   47.69MiB / 14.72GiB   2 PIDs
docker-nginx-1               0.00% CPU   11.33MiB / 14.72GiB   10 PIDs
docker-api-1                 0.70% CPU   4.308GiB / 14.72GiB   61 PIDs
docker-worker-1              0.13% CPU   296.8MiB / 14.72GiB   10 PIDs
docker-worker_beat-1         0.00% CPU   263.5MiB / 14.72GiB   17 PIDs
docker-web-1                 0.37% CPU   395.7MiB / 14.72GiB   34 PIDs
docker-plugin_daemon-1       0.50% CPU   1.216GiB / 14.72GiB   77 PIDs
docker-sandbox-1             0.00% CPU   448.5MiB / 14.72GiB   12 PIDs
docker-ssrf_proxy-1          0.02% CPU   18.76MiB / 14.72GiB   9 PIDs
weaviate-weaviate-master-1   3.09% CPU   194.8MiB / 14.72GiB   15 PIDs
huahuo-ai-test               0.01% CPU   336.1MiB / 14.72GiB   6 PIDs
huahuo-web-test              0.06% CPU   528.2MiB / 14.72GiB   46 PIDs
huahuo-web-prod              0.06% CPU   801.9MiB / 14.72GiB   46 PIDs
mysql                        0.27% CPU   716.9MiB / 14.72GiB   54 PIDs
```

Dify compose refresh:

```text
project: docker
compose file: /app/bin/dify/dify-1.11.2/docker/docker-compose.yaml
services: plugin_daemon, sandbox, web, init_permissions, worker, api, nginx, ssrf_proxy, worker_beat
images:
  langgenius/dify-plugin-daemon:0.5.2-local
  nginx:latest
  langgenius/dify-web:1.11.2
  langgenius/dify-sandbox:0.2.12
  busybox:latest
  langgenius/dify-api:1.11.2
  ubuntu/squid:latest
```

Running Dify services remain up. `docker-web-1` remains `unhealthy`; the latest
health log still confirms the historical cause:

```text
exec: "pg_isready": executable file not found in $PATH
```

Internal Dify HTTP refresh:

```text
http://127.0.0.1:8081/ -> 200 after redirect to /apps
http://127.0.0.1:8081/apps -> 200
http://127.0.0.1:8081/signin -> 200
http://127.0.0.1:8081/console/api/account/profile -> 401
docker-api-1 http://127.0.0.1:5001/console/api/account/profile -> 401
```

OpenClaw artifact refresh:

```text
MISSING /app/bin/openclaw
MISSING /app/bin/openclaw-bridge
MISSING /opt/openclaw
MISSING /opt/openclaw-bridge
OpenClaw/Douyin/Bridge containers: none found
OpenClaw/Douyin/Bridge images: none found
```

OpenResty mount summary was inspected as JSON only. No full OpenResty config,
TLS private key, credential file, Cookie, token, full request header or full
environment variable dump was read.

Conclusion for this refresh:

```text
Production Dify remains unchanged by this audit.
No OpenClaw sidecar exists on the server.
Production Phase 2 remains NO-GO.
```

SHA256:

```text
43718ee7e22c31af97b3c989ac5f4374aeef89409ed08d441ebeda101f38cc10
```

Route summary:

```text
listen ${NGINX_PORT}
/console/api -> http://api:5001
/api         -> http://api:5001
/v1          -> http://api:5001
/files       -> http://api:5001
/explore     -> http://web:3000
/e/          -> http://plugin_daemon:5002
/            -> http://web:3000
/mcp         -> http://api:5001
/triggers    -> http://api:5001
```

Decision:

- Do not modify this Dify template for V1 OpenClaw.
- Use the outer OpenResty independent prefixes `/openclaw-lab/` and `/openclaw-api/` later, after Phase 0 and artifact gates pass.

## OpenResty Baseline

Container:

```text
openresty-prod
image: openresty/openresty:1.29.2.5-0-alpine
network: host
```

Main config mount:

```text
/app/config/openresty/conf -> /usr/local/openresty/nginx/conf
```

OpenResty syntax test:

```text
nginx: the configuration file /usr/local/openresty/nginx/conf/nginx.conf syntax is ok
nginx: configuration file /usr/local/openresty/nginx/conf/nginx.conf test is successful
```

Config include shape:

```text
nginx.conf includes ./conf.d/*.conf
nginx.conf includes ./conf.d/*.main
```

Dify public route summary:

```text
server_name ai001.huahuoai.com
location ^~ /
proxy_pass http://dify-master/
upstream dify-master is defined in conf.d/upstream.conf
```

Relevant config root files:

```text
/app/config/openresty/conf/conf.d/adm.huahuoai.com.conf
/app/config/openresty/conf/conf.d/ai001.huahuoai.com.conf
/app/config/openresty/conf/conf.d/default.conf
/app/config/openresty/conf/conf.d/huahuoai.com.conf
/app/config/openresty/conf/conf.d/testadm.huahuoai.com.common
/app/config/openresty/conf/conf.d/test.conf
/app/config/openresty/conf/conf.d/test.huahuoai.com.common
/app/config/openresty/conf/conf.d/upstream.conf
/app/config/openresty/conf/fastcgi.conf
/app/config/openresty/conf/nginx.conf
```

Selected SHA256 values:

```text
6541ee6f5bbc777c7cf72ba5a078341e58af43d82ba5bbde6fad980f253653ce  /app/config/openresty/conf/conf.d/ai001.huahuoai.com.conf
3990336ee67ac22497c200231c23f18963dad25288ce70bae610b5ad927b8c19  /app/config/openresty/conf/conf.d/upstream.conf
cd6c8b1e07101d718d075b180a4cdf77a94d9e7925b1dae1b2ce226f42ed69ec  /app/config/openresty/conf/nginx.conf
```

Future change guidance:

- Add OpenClaw only through a separate, versioned include file.
- Do not edit Dify compose.
- Do not edit `docker-nginx-1` runtime files.
- Before any future OpenResty reload, produce a rollback file and real-browser Dify baseline.

## Current Go / No-Go

```text
Phase 0 read-only inspection: GO
Phase 1 offline artifact preparation: BLOCKED until OpenClaw/video artifacts are provided
Phase 2 server-side旁路 deployment: NO-GO
Phase 3 public /openclaw-lab route: NO-GO
Direct Dify Web modification: NO-GO
Direct Dify compose modification: NO-GO
```

## Blockers

1. OpenClaw code, image, container, or deployment directory was not found.
2. `openclaw-bridge` code or image was not found.
3. A local `douyin_chong` candidate has since been found and a minimal V1
   source subset has been vendored in this repository, but it is not
   model-verified and is not present as a production server artifact.
4. No production-proven API contract exists between Bridge, OpenClaw, and the
   video worker on an isolated Linux Docker host.
5. No resource-limited video analysis benchmark exists on this host.
6. Dify public browser baseline is only partially complete because no Dify login credentials were provided for testing an authenticated existing app flow.

## Refresh 2026-06-06 10:36 Asia/Shanghai

Mode: read-only SSH inspection through `ssh-skill`; no deployment, reload,
restart, install, upload, download, `.env` read, full environment dump, cookie
read or token read was performed.

System/resource refresh:

```text
date: 2026-06-06T10:36:08+08:00
kernel: Linux AI-01 6.8.0-57-generic #59-Ubuntu SMP PREEMPT_DYNAMIC Sat Mar 15 17:40:59 UTC 2025 x86_64
docker server: 28.1.1
docker compose: v2.35.1
memory: 14Gi total, 11Gi used, 954Mi free, 3.7Gi available, swap 0B
/app: 500G total, 63G used, 438G available, 13% used
cpu cores: 8
uptime: 378 days, 19:03
load average: 1.59, 1.35, 1.25
```

Container resource refresh:

```text
openresty-prod               0.18% CPU   47.71MiB   2 PIDs
docker-nginx-1               0.09% CPU   11.33MiB   10 PIDs
docker-api-1                 5.47% CPU   4.302GiB   62 PIDs
docker-worker-1              0.02% CPU   296.8MiB   10 PIDs
docker-worker_beat-1         0.00% CPU   263.5MiB   17 PIDs
docker-web-1                 0.42% CPU   395.6MiB   34 PIDs
docker-plugin_daemon-1       1.56% CPU   1.225GiB   78 PIDs
docker-sandbox-1             0.00% CPU   442.6MiB   12 PIDs
docker-ssrf_proxy-1          0.01% CPU   18.76MiB   9 PIDs
weaviate-weaviate-master-1   2.76% CPU   194.8MiB   15 PIDs
huahuo-ai-test               0.01% CPU   336.1MiB   6 PIDs
huahuo-web-test              0.07% CPU   528.2MiB   46 PIDs
huahuo-web-prod              0.07% CPU   801.9MiB   46 PIDs
mysql                        0.73% CPU   716.9MiB   54 PIDs
```

Dify compose refresh:

```text
project: docker
root: /app/bin/dify/dify-1.11.2/docker
services: sandbox, init_permissions, api, web, nginx, worker, worker_beat, plugin_daemon, ssrf_proxy
api image: langgenius/dify-api:1.11.2
web image: langgenius/dify-web:1.11.2
nginx image: nginx:latest
plugin_daemon image: langgenius/dify-plugin-daemon:0.5.2-local
sandbox image: langgenius/dify-sandbox:0.2.12
```

Network refresh:

```text
docker_default containers:
  docker-api-1
  docker-ssrf_proxy-1
  docker-web-1
  docker-nginx-1
  docker-worker-1
  docker-plugin_daemon-1
  docker-worker_beat-1

aliases:
  docker-api-1   docker_default aliases=[docker-api-1 api]
  docker-api-1   docker_ssrf_proxy_network aliases=[docker-api-1 api]
  docker-web-1   docker_default aliases=[docker-web-1 web]
  docker-nginx-1 docker_default aliases=[docker-nginx-1 nginx]
```

HTTP refresh from server:

```text
http://127.0.0.1:8081 -> 200 final http://127.0.0.1:8081/apps
http://127.0.0.1:8081/apps -> 200
http://127.0.0.1:8081/signin -> 200
http://127.0.0.1:8081/console/api/account/profile -> 401
docker-api-1 internal http://127.0.0.1:5001/console/api/account/profile -> 401
```

Healthcheck refresh:

```text
docker-web-1 status: unhealthy
healthcheck: ["CMD","pg_isready","-h","db_postgres","-U","dify","-d","dify"]
recent log output: exec: "pg_isready": executable file not found in $PATH
```

This confirms the earlier interpretation: the unhealthy status is a historical
Dify healthcheck/config mismatch, not an OpenClaw-caused regression.

Port refresh and risk note:

```text
0.0.0.0:80    openresty
0.0.0.0:443   openresty
0.0.0.0:8081  docker-proxy -> docker-nginx-1
0.0.0.0:8443  docker-proxy -> docker-nginx-1
0.0.0.0:5003  docker-proxy -> docker-plugin_daemon-1
0.0.0.0:5001  gunicorn / Dify API
18180, 18181, 18789, 5432, 6379: not observed in filtered listener output
```

Risk: `0.0.0.0:5001` is currently listening on the host for the Dify API. This
was observed only as a baseline and was not changed. Future OpenClaw planning
must not add any new public listener, and any separate remediation of existing
`5001` exposure should be treated as a Dify/network hardening task outside this
OpenClaw deployment phase.
