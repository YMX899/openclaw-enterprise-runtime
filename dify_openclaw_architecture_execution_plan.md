# Dify Web 集成 OpenClaw Agent 架构执行方案

> 版本：V1.1 root 服务器现场修正版  
> 目标：在现有 Dify Web 中增加 OpenClaw 入口，使 Dify 用户可以通过网页端与 OpenClaw Agent 对话；OpenClaw 保存用户会话历史，按用户隔离 memory，支持每条消息携带视频链接。  
> 重要说明：本方案按生产可落地、权限隔离、可回滚、可扩展原则设计，并已根据 root 服务器当前 Dify 工程架构修正。工程落地不能在未执行前承诺“绝对百分之百”，因此本文档采用“运行门禁”保证：所有前置核验项必须全部通过，失败即停止执行；全部通过后再按本文步骤实施，以最大化保证正常运行。

---

## 0. root 服务器现场架构基线

本方案已按 root 服务器当前状态修正，后续执行不得再套用 Dify 默认本地 PostgreSQL/Redis compose 假设。

已核验事实：

```text
服务器别名：root
主机名：AI-01
Dify 版本：1.11.2
Dify API 镜像：langgenius/dify-api:1.11.2
Dify Web 镜像：langgenius/dify-web:1.11.2
Dify compose 路径：/app/bin/dify/dify-1.11.2/docker/docker-compose.yaml
Dify compose project：docker
Dify 主 Docker network：docker_default
Dify API 容器：docker-api-1，网络别名 api，端口 5001
Dify Web 容器：docker-web-1，网络别名 web，端口 3000
Dify Nginx 容器：docker-nginx-1，网络别名 nginx，容器端口 8081
Dify Nginx 模板：/app/bin/dify/dify-1.11.2/docker/nginx/conf.d/default.conf.template
Dify DB：阿里云 PostgreSQL RDS，不是本地 db_postgres 容器
Dify Redis：阿里云 Redis，不是本地 redis 容器
Dify 当前用户接口：GET http://api:5001/console/api/account/profile
Dify 用户表字段：accounts.id/name/email/avatar/created_at 存在
OpenClaw 现场状态：当前 root 服务器未发现 /opt/openclaw、OpenClaw 容器或 OpenClaw 镜像；执行前必须先完成 OpenClaw 实际部署位置核验
```

运行门禁：

```text
1. docker network inspect docker_default 成功。
2. openclaw-bridge 容器能解析并访问 http://api:5001/console/api/account/profile。
3. Bridge 使用浏览器原始 Cookie/Authorization/CSRF 相关头调用 Dify profile 接口，能拿到当前 account 与 tenant 上下文。
4. 若 Bridge 需要直连数据库，RDS 已创建只读视图与只读账号，且 RDS 白名单/安全组允许 Bridge 访问。
5. OpenClaw 服务已部署，Bridge 能访问 OpenClaw /health。
6. OpenClaw 已验证 user_id + session_id 隔离。
7. Dify Web 自定义镜像已基于 1.11.2 构建并通过页面冒烟测试。
8. Nginx 模板修改后 nginx -t 通过。
9. 双用户隔离测试、视频 URL SSRF 测试、回滚演练全部通过。
```

以上任一门禁失败，都不得继续上线。

---

## 1. 已确认需求

### 1.1 Dify 现状

- Dify 已经部署完成。
- Dify 当前运行正常。
- Dify 当前为单 workspace 使用。
- 用户个人基础信息已经存在于 Dify 数据库。
- V1 阶段只读取 Dify 用户基础信息。
- V2 阶段再做“用户在 Dify 中历史对话/行为压缩摘要”。

### 1.2 OpenClaw 现状

- OpenClaw 当前必须先完成现场部署核验：root 服务器现有 Docker 资产中暂未发现 OpenClaw 容器、镜像或 `/opt/openclaw` 目录。
- V1 执行前必须明确 OpenClaw 是部署在 root 服务器、另一台服务器，还是已有服务地址。
- OpenClaw `/health` 必须能被 Bridge 稳定访问后，才能进入 Dify Web 集成阶段。
- OpenClaw 视频分析功能已运行正常。
- 视频分析具体实现由现有 OpenClaw 侧负责，本方案不展开。
- OpenClaw 内部可以修改。
- OpenClaw 不需要伪装成飞书消息。
- OpenClaw memory 支持按 `user_id` 或 `session_id` 隔离。
- OpenClaw 保存用户会话历史。
- Dify 不重复保存 OpenClaw 的完整历史。

### 1.3 交互需求

- Dify Web 增加一个 OpenClaw 入口。
- 用户点击入口后，进入 OpenClaw 对话页面。
- 页面打开后，通过 Bridge 向 OpenClaw 拉取当前用户历史会话。
- 用户可以创建多个会话。
- 一个会话可以包含多个视频。
- 每条消息可以附带一个 `video_url`。
- OpenClaw memory 按 `user_id` 隔离。
- OpenClaw 会话历史按 `session_id` 隔离。
- V1 网页端可先使用同步请求，但必须设置超时、取消、重试和重复提交保护；如果单次视频分析可能超过 60 秒，必须优先改为任务状态轮询或 SSE：
  - 用户发消息；
  - Web 请求 Bridge；
  - Bridge 等待 OpenClaw 返回；
  - Web 展示结果。

---

## 2. 总体架构结论

最终采用以下架构：

```text
Dify Web 新增 OpenClaw 页面
        ↓
Dify Nginx 反向代理 /openclaw-api/*
        ↓
openclaw-bridge
        ↓
OpenClaw 新增 Dify Web Channel / HTTP 接入层
        ↓
OpenClaw Agent Runtime
        ↓
OpenClaw Memory / Session Store
```

职责边界：

```text
Dify：
- 用户登录
- 用户身份源
- 用户基础信息源
- Web 页面入口

openclaw-bridge：
- 校验 Dify 当前用户
- 读取当前用户基础信息
- 映射 Dify 用户到 OpenClaw user_id
- 映射 Dify 会话到 OpenClaw session_id
- 转发消息给 OpenClaw
- 从 OpenClaw 拉取会话历史
- 防止用户访问其他用户会话

OpenClaw：
- Agent 执行
- 视频分析
- 每个用户 memory 隔离
- 每个会话历史保存
- 多会话管理
```

---

## 3. 为什么必须保留 Bridge

Bridge 在本项目中不是普通反向代理，而是 **Dify 与 OpenClaw 的协议适配层、身份隔离层、权限控制层**。

### 3.1 如果没有 Bridge，会出现的问题

如果 Dify Web 直接调用 OpenClaw：

```text
Dify Web → OpenClaw
```

问题：

- 浏览器无法直接可靠访问 Docker 内部容器名。
- OpenClaw 内部接口可能需要暴露到公网或 Dify 前端可访问网络。
- OpenClaw token 或内部通信凭据可能暴露给浏览器。
- 用户身份校验会被放到前端，容易被伪造。
- 无法可靠保证用户 A 不能读取用户 B 的会话。
- 无法集中做审计、限流、错误处理和隔离。

如果 OpenClaw 直接读 Dify 数据库：

```text
OpenClaw → Dify PostgreSQL
```

问题：

- OpenClaw 需要持有 Dify 数据库凭据。
- Agent 容器风险边界变大。
- 一旦 OpenClaw 插件、工具或提示注入出现问题，可能读取全量用户数据。
- 用户隔离逻辑分散到 Agent 内部，难以审计。
- Dify 数据库结构变化会直接影响 OpenClaw。

### 3.2 推荐方式

```text
Dify Web → Bridge → OpenClaw
              ↓
        Dify PostgreSQL
```

Bridge 负责：

- 只读取当前登录用户的数据；
- 只给 OpenClaw 传递必要字段；
- 生成稳定的 `user_id` 和 `session_id`；
- 调用 OpenClaw 的 Dify Web Channel；
- 对外隐藏 OpenClaw 内部实现。

---

## 4. 部署结构

### 4.1 root 服务器实际目录

root 服务器 Dify 实际目录如下，执行时以此为准：

```text
/app/bin/dify/dify-1.11.2/docker
/app/bin/dify/dify-1.11.2/docker/docker-compose.yaml
/app/bin/dify/dify-1.11.2/docker/.env
/app/bin/dify/dify-1.11.2/docker/nginx/conf.d/default.conf.template
```

OpenClaw/Bridge 推荐目录：

```text
/app/bin/openclaw
/app/bin/openclaw-bridge
```

如果最终仍使用 `/opt/openclaw`，必须先创建目录、记录 owner/权限，并在本文档执行记录中替换对应路径。

### 4.2 网络原则

OpenClaw 相关容器通过 external Docker network 加入 Dify 网络。

root 服务器 Dify network 实际名称为：

```text
docker_default
```

OpenClaw compose 中引用：

```yaml
networks:
  dify_net:
    external: true
    name: docker_default
```

这样 OpenClaw 相关容器可以访问 Dify 内部服务：

```text
api:5001
web:3000
nginx:8081
```

注意：root 服务器当前 Dify 数据库和 Redis 都不是 Docker 内部容器，而是云服务：

```text
PostgreSQL：阿里云 RDS，Dify API 环境变量 DB_HOST 指向 RDS 地址
Redis：阿里云 Redis，Dify API 环境变量 REDIS_HOST 指向云 Redis 地址
Weaviate：Dify API 环境变量 WEAVIATE_ENDPOINT 指向固定内网 IP
```

因此 Bridge 不能假设 `db_postgres:5432` 或 `redis:6379` 可用。

---

## 5. Docker Compose 设计

在 `/app/bin/openclaw/docker-compose.yml` 中增加或调整。若 OpenClaw 实际部署在其他目录，执行前必须同步修改本节路径。

重要：以下 RDS/Redis/OpenClaw 地址必须来自现场核验，不允许沿用默认占位值。

```yaml
services:
  openclaw:
    image: your-openclaw-image:latest
    container_name: openclaw
    restart: unless-stopped
    environment:
      OPENCLAW_ENV: production
    networks:
      - dify_net

  openclaw-bridge:
    image: your-openclaw-bridge:latest
    container_name: openclaw-bridge
    restart: unless-stopped
    environment:
      # Dify PostgreSQL RDS，只读用户；不得写成 db_postgres
      DIFY_DB_HOST: ${DIFY_DB_HOST}
      DIFY_DB_PORT: 5432
      DIFY_DB_NAME: dify
      DIFY_DB_USER: dify_openclaw_reader
      DIFY_DB_PASSWORD: ${DIFY_OPENCLAW_READER_PASSWORD}

      # Dify 内部 API，用于校验当前用户
      DIFY_API_BASE: http://api:5001
      DIFY_PROFILE_PATH: /console/api/account/profile

      # OpenClaw 内部接入地址
      OPENCLAW_BASE_URL: http://openclaw:8080

      # 当前单 workspace
      DIFY_WORKSPACE_MODE: single

      # 即使当前单 workspace，也使用 tenant-aware key，避免后续迁移 OpenClaw memory/session
      OPENCLAW_USER_KEY_MODE: tenant_account

    networks:
      - dify_net
    depends_on:
      - openclaw

networks:
  dify_net:
    external: true
    name: docker_default
```

### 5.1 注意事项

- `name: docker_default` 是 root 服务器当前 Dify Docker network 名称，不能写成 `dify_default`。
- `your-openclaw-image:latest` 替换成真实 OpenClaw 镜像。
- `your-openclaw-bridge:latest` 替换成实际 Bridge 镜像。
- 生产环境不要把数据库密码写死在 compose 文件中，应使用 `.env`。
- Bridge 直连 RDS 前必须确认 RDS 白名单/安全组允许容器所在宿主机访问。
- 如果 Bridge 只通过 Dify profile API 获取用户基础资料，V1 可以不直连 RDS；需要用户扩展资料时再启用 RDS 只读视图。

---

## 6. Dify Web 改造方案

root 服务器当前 `docker-web-1` 内是已构建的 Next.js 产物，主要目录为 `/app/web/.next`，不应直接进入容器修改页面文件。

正确方式：

```text
1. 使用 Dify 1.11.2 对应源码作为改造基线。
2. 在源码中新增 OpenClaw 菜单、路由和页面。
3. 构建自定义 dify-web 镜像，例如 dify-web-openclaw:1.11.2-v1。
4. 修改 /app/bin/dify/dify-1.11.2/docker/docker-compose.yaml 中 web 服务镜像。
5. 保留原 langgenius/dify-web:1.11.2 镜像和 compose 备份，用于回滚。
```

### 6.1 入口位置

入口位置暂定，可放在：

```text
Dify 左侧菜单
```

菜单项名称建议：

```text
OpenClaw 视频分析
```

页面路由建议：

```text
/openclaw
```

或：

```text
/apps/openclaw
```

### 6.2 页面职责

Dify Web 页面只做 UI 和请求，不承担权限逻辑。

页面负责：

- 展示 OpenClaw 会话列表；
- 创建新会话；
- 展示当前会话消息；
- 输入消息；
- 输入或附加 `video_url`；
- 发送到 Bridge；
- 展示 OpenClaw 回复；
- 显示 loading、error、retry 状态。

页面不负责：

- 直接访问 Dify 数据库；
- 直接访问 OpenClaw；
- 拼接用户隐私上下文；
- 判断用户是否能访问某个 session；
- 保存完整 OpenClaw 会话历史。

---

## 7. Dify Nginx 反向代理

root 服务器 Nginx 配置来自模板：

```text
/app/bin/dify/dify-1.11.2/docker/nginx/conf.d/default.conf.template
```

不要只修改容器内 `/etc/nginx/conf.d/default.conf`，否则后续重建容器会丢失。应先备份模板，再在模板中增加路径：

```nginx
location /openclaw-api/ {
    proxy_pass http://openclaw-bridge:3000/;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Cookie $http_cookie;
    proxy_set_header X-CSRF-Token $http_x_csrf_token;
    proxy_set_header X-Requested-With $http_x_requested_with;
    include proxy.conf;
}
```

如果前端实际使用的 CSRF 头名称不是 `X-CSRF-Token`，必须按 Dify Web 当前请求头修正，不能只转 Cookie。

修改后必须执行：

```bash
docker exec docker-nginx-1 nginx -t
cd /app/bin/dify/dify-1.11.2/docker
docker compose restart nginx
docker exec docker-nginx-1 nginx -T | grep -n "openclaw-api"
```

如果外层 `openresty-prod` 负责公网入口，还必须确认它会把 `/openclaw-api/` 原样转发到 `docker-nginx-1:8081`。

禁止写成：

```nginx
location /openclaw-api/ {
    proxy_pass http://openclaw-bridge:3000/;
    # 只转 Cookie，不转 Dify CSRF/鉴权相关头
}
```

前端请求：

```ts
fetch('/openclaw-api/chat', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    // 按 Dify Web 现有请求方式附带 CSRF/鉴权相关头；具体字段以 1.11.2 前端实现为准
    ...getDifyAuthHeaders(),
  },
  credentials: 'include',
  body: JSON.stringify({
    session_id,
    message,
    video_url,
  }),
})
```

---

## 8. 用户身份校验方案

### 8.1 推荐方案

Bridge 使用 Dify 当前登录态校验用户。

请求路径：

```text
Dify Web → /openclaw-api/* → Bridge
```

Bridge 接收：

- Cookie；
- Authorization header；
- 其他 Dify Web 已有登录态信息。

Bridge 校验方式：

```text
Bridge 调用 Dify 1.11.2 当前用户接口获取当前用户信息：
GET http://api:5001/console/api/account/profile
```

逻辑：

```text
1. Dify Web 发请求给 Bridge。
2. Bridge 原样读取并转发请求中的 Cookie / Authorization / CSRF 相关头。
3. Bridge 调 Dify API：GET /console/api/account/profile。
4. Dify API 通过 login_required、CSRF 校验和 current_account_with_tenant() 验证当前用户。
5. Dify API 返回当前用户基础信息；Bridge 必须同时取得或补齐 tenant_id。
6. Bridge 使用 tenant_id + ":" + account_id 作为 OpenClaw user_id。
```

如果 Bridge 调用 profile 接口返回 401/403，必须直接向前端返回未登录或无权限错误，不得降级为信任前端传入的 account_id。

### 8.2 禁止方式

不要让前端直接传：

```json
{
  "account_id": "xxx"
}
```

然后 Bridge 信任它。

原因：

- 前端参数可被用户篡改；
- 用户 A 可以伪造用户 B 的 account_id；
- 会破坏用户隔离。

---

## 9. 用户基础信息读取方案

V1 只读取用户基础信息。

优先路径：

```text
Bridge 调用 Dify profile API 获取当前登录用户基础信息。
```

可选路径：

```text
当 OpenClaw 需要 profile API 之外的字段时，Bridge 再通过 RDS 只读视图读取扩展字段。
```

### 9.1 默认字段

V1 建议读取：

```text
tenant_id
account_id
name
email
avatar
created_at
```

root 服务器 Dify 1.11.2 源码已确认 `accounts.id/name/email/avatar/created_at` 存在。tenant 维度应来自 Dify 当前用户上下文或 `tenant_account_joins`。

### 9.2 数据库视图

如需直连 RDS，推荐创建只读视图。视图必须包含 `tenant_id`，不要只按 `account_id` 查询：

```sql
CREATE VIEW openclaw_user_basic_context AS
SELECT
  taj.tenant_id,
  a.id AS account_id,
  a.name,
  a.email,
  a.avatar,
  a.created_at
FROM accounts a
JOIN tenant_account_joins taj ON taj.account_id = a.id;
```

如果现场表名不是 `tenant_account_joins`，必须先在 RDS 中核验 Dify 1.11.2 实际表结构，再调整视图。不得猜表名执行 DDL。

### 9.3 Bridge 查询方式

```sql
SELECT
  account_id,
  name,
  email,
  avatar,
  created_at
FROM openclaw_user_basic_context
WHERE tenant_id = $1
AND account_id = $2;
```

即使当前是单 workspace，也必须保留 `tenant_id` 查询条件，避免未来多 workspace 或账号迁移时造成 OpenClaw memory/session 串用。

---

## 10. 数据库权限设计

### 10.1 创建只读用户

root 服务器 Dify PostgreSQL 是阿里云 RDS，不是本机 Docker `db_postgres` 容器。禁止使用下面这种默认部署命令：

```bash
docker exec -it <dify-postgres-container> psql -U postgres -d dify
```

正确方式：

```text
1. 使用 RDS 管理入口或受控运维机连接 PostgreSQL。
2. 确认连接账号具备创建视图和用户的权限。
3. 确认 RDS 白名单/安全组允许 Bridge 容器所在宿主机访问。
4. 创建只读视图和只读用户。
5. 使用只读用户从 Bridge 容器内测试 SELECT。
```

创建 Bridge 专用只读用户：

```sql
CREATE USER dify_openclaw_reader WITH PASSWORD '强密码';

GRANT CONNECT ON DATABASE dify TO dify_openclaw_reader;
GRANT USAGE ON SCHEMA public TO dify_openclaw_reader;
GRANT SELECT ON openclaw_user_basic_context TO dify_openclaw_reader;
```

### 10.2 不推荐授权

不要在生产环境直接执行：

```sql
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dify_openclaw_reader;
```

除非仅在开发阶段临时排查问题。

### 10.3 权限原则

Bridge 数据库账号只能读取：

- 当前用户基础信息视图；
- 未来 V2 的用户摘要视图；
- 必要的最小辅助表。

Bridge 不应该拥有：

- INSERT 权限；
- UPDATE 权限；
- DELETE 权限；
- DDL 权限；
- PostgreSQL 超级用户权限。

---

## 11. OpenClaw 内部改造方案

由于 OpenClaw 可以修改，推荐新增一个轻量 HTTP 接入层：

```text
Dify Web Channel
```

### 11.1 OpenClaw 新增接口

建议 OpenClaw 提供以下内部接口：

```text
POST /channels/dify-web/chat
GET  /channels/dify-web/sessions
POST /channels/dify-web/sessions
GET  /channels/dify-web/sessions/{session_id}/messages
GET  /health
```

这些接口只给 Bridge 调用，不直接暴露给浏览器或公网。

### 11.2 Chat 接口

```http
POST /channels/dify-web/chat
```

请求：

```json
{
  "user_id": "tenant_id:account_id",
  "session_id": "openclaw_session_id",
  "message": "请帮我看看这个视频",
  "video_url": "https://example.com/video.mp4",
  "user_profile": {
    "tenant_id": "tenant_xxx",
    "account_id": "xxx",
    "name": "张三",
    "email": "xxx@example.com",
    "avatar": "https://example.com/avatar.png",
    "created_at": "2026-01-01T00:00:00Z"
  }
}
```

返回：

```json
{
  "session_id": "openclaw_session_id",
  "reply": "分析结果...",
  "message_id": "msg_xxx",
  "created_at": "2026-01-01T00:00:00Z"
}
```

### 11.3 Sessions List 接口

```http
GET /channels/dify-web/sessions?user_id=xxx
```

返回：

```json
{
  "sessions": [
    {
      "session_id": "session_xxx",
      "title": "视频分析 1",
      "updated_at": "2026-01-01T00:00:00Z"
    }
  ]
}
```

### 11.4 Create Session 接口

```http
POST /channels/dify-web/sessions
```

请求：

```json
{
  "user_id": "tenant_id:account_id",
  "title": "新会话"
}
```

返回：

```json
{
  "session_id": "session_xxx",
  "title": "新会话",
  "created_at": "2026-01-01T00:00:00Z"
}
```

### 11.5 Session Messages 接口

```http
GET /channels/dify-web/sessions/{session_id}/messages?user_id=xxx
```

返回：

```json
{
  "session_id": "session_xxx",
  "messages": [
    {
      "role": "user",
      "content": "请帮我分析这个视频",
      "video_url": "https://example.com/video.mp4",
      "created_at": "2026-01-01T00:00:00Z"
    },
    {
      "role": "assistant",
      "content": "分析结果...",
      "created_at": "2026-01-01T00:01:00Z"
    }
  ]
}
```

---

## 12. Bridge API 设计

Bridge 对 Dify Web 暴露以下接口：

```text
GET  /health
GET  /sessions
POST /sessions
GET  /sessions/{session_id}/messages
POST /chat
```

### 12.1 GET /health

用途：健康检查。

返回：

```json
{
  "status": "ok",
  "dify_db": "ok",
  "dify_api": "ok",
  "openclaw": "ok"
}
```

### 12.2 GET /sessions

用途：获取当前 Dify 用户的 OpenClaw 会话列表。

流程：

```text
1. Bridge 校验 Dify 当前用户。
2. 获取 tenant_id 与 account_id。
3. 调 OpenClaw sessions list。
4. 返回属于当前用户的 sessions。
```

返回：

```json
{
  "sessions": [
    {
      "session_id": "session_xxx",
      "title": "视频分析",
      "updated_at": "2026-01-01T00:00:00Z"
    }
  ]
}
```

### 12.3 POST /sessions

用途：创建新会话。

请求：

```json
{
  "title": "新会话"
}
```

返回：

```json
{
  "session_id": "session_xxx",
  "title": "新会话",
  "created_at": "2026-01-01T00:00:00Z"
}
```

### 12.4 GET /sessions/{session_id}/messages

用途：读取当前用户某个会话的历史消息。

流程：

```text
1. Bridge 校验 Dify 当前用户。
2. 获取 tenant_id 与 account_id。
3. Bridge 请求 OpenClaw 时同时传 user_id 和 session_id。
4. OpenClaw 必须校验 session_id 属于 user_id。
5. 返回消息。
```

### 12.5 POST /chat

用途：发送消息给 OpenClaw。

请求：

```json
{
  "session_id": "session_xxx",
  "message": "请分析这个视频",
  "video_url": "https://example.com/video.mp4"
}
```

返回：

```json
{
  "session_id": "session_xxx",
  "reply": "分析结果...",
  "message_id": "msg_xxx",
  "created_at": "2026-01-01T00:00:00Z"
}
```

---

## 13. ID 映射规则

### 13.1 当前 V1

root 服务器当前虽然按单 workspace 使用，但 Dify 1.11.2 的账号体系天然带 tenant/workspace 上下文。V1 必须直接使用 tenant-aware user_id：

```text
openclaw_user_id = tenant_id + ":" + account_id
```

session_id 由 OpenClaw 或 Bridge 创建。

推荐：

```text
session_id = OpenClaw 创建
```

原因：

- 会话历史由 OpenClaw 保存；
- OpenClaw 是会话主存储；
- session_id 由 OpenClaw 管理更自然。

Bridge 保存轻量映射或不保存映射均可。

推荐 OpenClaw session 记录中必须包含：

```text
user_id
tenant_id
account_id
session_id
title
created_at
updated_at
```

### 13.2 为什么 V1 就保留 tenant_id

原因：

```text
1. Dify 当前用户接口内部使用 current_account_with_tenant()。
2. 只用 account_id 会让 OpenClaw memory/session 未来迁移困难。
3. tenant_id + account_id 可以兼容当前单 workspace 和未来多 workspace。
```

示例：

```text
tenant_001:account_001
```

---

## 14. 会话与 Memory 隔离

### 14.1 Memory 隔离

```text
OpenClaw memory key = user_id
```

每个用户独立 memory。

### 14.2 会话历史隔离

```text
OpenClaw session key = user_id + session_id
```

OpenClaw 查询消息时必须校验：

```text
session.user_id == request.user_id
```

否则拒绝访问。

### 14.3 消息隔离

每条消息至少包含：

```text
message_id
user_id
session_id
role
content
video_url
created_at
```

---

## 15. 消息数据模型

### 15.1 用户消息

```json
{
  "message_id": "msg_user_xxx",
  "user_id": "tenant_id:account_id",
  "tenant_id": "tenant_xxx",
  "account_id": "account_xxx",
  "session_id": "session_xxx",
  "role": "user",
  "content": "请分析这个视频",
  "video_url": "https://example.com/video.mp4",
  "created_at": "2026-01-01T00:00:00Z"
}
```

### 15.2 Agent 回复

```json
{
  "message_id": "msg_agent_xxx",
  "user_id": "tenant_id:account_id",
  "tenant_id": "tenant_xxx",
  "account_id": "account_xxx",
  "session_id": "session_xxx",
  "role": "assistant",
  "content": "分析结果...",
  "created_at": "2026-01-01T00:01:00Z"
}
```

---

## 16. 用户基础信息进入 OpenClaw 的方式

V1 使用方式 C：

```text
Bridge 读取 Dify 用户基础信息
        ↓
Bridge 在每次请求中传给 OpenClaw
        ↓
OpenClaw 作为 session 初始化上下文使用
```

### 16.1 是否保存到 OpenClaw

V1 推荐：

- OpenClaw 不必把 Dify 基础信息作为长期 profile 单独保存；
- 可以在 session 首次创建时保存一份 profile snapshot；
- 每次聊天时 Bridge 仍然传当前最新基础信息；
- OpenClaw 处理时优先使用当前请求中的 `user_profile`。

这样可以避免 Dify 用户改名、改头像后 OpenClaw 长期使用旧信息。

### 16.2 Session 初始化上下文

OpenClaw 在创建 session 或处理首条消息时，构造上下文：

```text
你正在和 Dify 用户进行视频分析对话。

当前用户基础信息：
- OpenClaw 用户 ID：{{tenant_id}}:{{account_id}}
- Dify tenant ID：{{tenant_id}}
- Dify account ID：{{account_id}}
- 名称：{{name}}
- 邮箱：{{email}}

约束：
1. 只使用当前 user_id 对应的 memory。
2. 只读取当前 session_id 对应的会话历史。
3. 不得引用其他用户的信息。
4. 如果视频链接不可访问，应明确说明。
5. 如果视频内容无法判断，不要编造。
```

---

## 17. 视频 URL 处理

### 17.1 V1 约定

- 用户每条消息可以附带 `video_url`。
- `video_url` 可以为空。
- 一个会话可以出现多个不同 `video_url`。
- OpenClaw 自己负责读取视频并分析。
- Bridge 不负责视频下载、转码、抽帧、识别。

### 17.2 Bridge 需要做的最小校验

虽然视频分析由 OpenClaw 处理，但 Bridge 应做最小安全校验：

```text
1. video_url 必须是 http 或 https。
2. video_url 长度限制。
3. 拒绝 file://。
4. 拒绝 localhost、127.0.0.0/8、0.0.0.0/8、10.0.0.0/8、172.16.0.0/12、192.168.0.0/16、169.254.0.0/16。
5. 拒绝 IPv6 本地与内网地址，例如 ::1、fc00::/7、fe80::/10。
6. 必须 DNS 解析后校验最终 IP，不能只校验字符串。
7. 如果允许 HTTP 重定向，必须对每一次重定向后的 URL 和 IP 重新校验。
8. 可选：只允许白名单域名。
```

如果暂时不做白名单，至少要防止 SSRF 风险。

---

## 18. 推荐 Bridge 技术栈

推荐：

```text
Python FastAPI
```

依赖：

```text
fastapi
uvicorn
httpx
asyncpg 或 sqlalchemy
pydantic
```

原因：

- 开发快；
- 适合 API 转发；
- AI 工程生态好；
- Docker 化简单；
- 后续可扩展异步任务、队列、日志。

---

## 19. Bridge 核心伪代码

```python
@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    # 1. 校验 Dify 当前用户
    current_user = await verify_dify_user(request)

    account_id = current_user.account_id
    tenant_id = current_user.tenant_id
    openclaw_user_id = f"{tenant_id}:{account_id}"

    # 2. 读取用户基础信息。优先使用 Dify profile API 返回值；必要时再查 RDS 只读视图。
    profile = await get_user_basic_profile(tenant_id, account_id)

    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found")

    # 3. 校验 video_url
    validate_video_url(req.video_url)

    # 4. 调用 OpenClaw
    payload = {
        "user_id": openclaw_user_id,
        "tenant_id": tenant_id,
        "account_id": account_id,
        "session_id": req.session_id,
        "message": req.message,
        "video_url": req.video_url,
        "user_profile": profile,
    }

    result = await openclaw_client.chat(payload)

    # 5. 返回结果
    return result
```

---

## 20. OpenClaw Dify Web Channel 伪代码

```python
@app.post("/channels/dify-web/chat")
async def dify_web_chat(req: DifyWebChatRequest):
    user_id = req.user_id
    session_id = req.session_id

    # 1. 校验或创建 session
    session = session_store.get(session_id)

    if not session:
        session = session_store.create(
            user_id=user_id,
            session_id=session_id,
            profile_snapshot=req.user_profile,
        )

    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="Session does not belong to user")

    # 2. 加载用户 memory
    memory = memory_store.load(user_id=user_id)

    # 3. 加载会话历史
    history = session_store.load_messages(
        user_id=user_id,
        session_id=session_id,
    )

    # 4. 保存用户消息
    session_store.append_message(
        user_id=user_id,
        session_id=session_id,
        role="user",
        content=req.message,
        video_url=req.video_url,
    )

    # 5. 调用 Agent
    reply = agent.run(
        user_id=user_id,
        session_id=session_id,
        message=req.message,
        video_url=req.video_url,
        user_profile=req.user_profile,
        memory=memory,
        history=history,
    )

    # 6. 保存 Agent 回复
    session_store.append_message(
        user_id=user_id,
        session_id=session_id,
        role="assistant",
        content=reply,
    )

    return {
        "session_id": session_id,
        "reply": reply,
    }
```

---

## 21. 前端页面流程

### 21.1 页面打开

```text
用户点击 OpenClaw 入口
        ↓
GET /openclaw-api/sessions
        ↓
显示历史会话列表
```

### 21.2 创建会话

```text
用户点击新建会话
        ↓
POST /openclaw-api/sessions
        ↓
Bridge 调 OpenClaw 创建 session
        ↓
前端进入新 session
```

### 21.3 查看历史

```text
用户点击某个历史会话
        ↓
GET /openclaw-api/sessions/{session_id}/messages
        ↓
显示该会话消息
```

### 21.4 发送消息

```text
用户输入 message，可选 video_url
        ↓
POST /openclaw-api/chat
        ↓
Bridge 读取用户基础信息
        ↓
OpenClaw 处理并保存历史
        ↓
前端展示 reply
```

---

## 22. V1 开发任务拆解

### 22.1 Dify Web

- 增加 OpenClaw 菜单入口。
- 增加 OpenClaw 页面。
- 增加会话列表组件。
- 增加消息列表组件。
- 增加输入框。
- 增加 video_url 输入框。
- 调用 Bridge API。
- 处理 loading 和错误状态。

### 22.2 openclaw-bridge

- 实现 Dify 用户校验。
- 实现 Dify 用户基础信息读取。
- 实现 `/sessions`。
- 实现 `/sessions/{session_id}/messages`。
- 实现 `/sessions` 创建。
- 实现 `/chat`。
- 实现 `/health`。
- 实现 OpenClaw client。
- 实现 video_url 基础校验。
- 实现错误处理。

### 22.3 OpenClaw

- 新增 Dify Web Channel HTTP 接入层。
- 新增 session list 接口。
- 新增 session create 接口。
- 新增 session messages 接口。
- 新增 chat 接口。
- 保证 `user_id` memory 隔离。
- 保证 `session_id` 历史隔离。
- 支持 message + video_url 输入。
- 保存用户消息和 Agent 回复。

### 22.4 运维

- OpenClaw 加入 root 服务器实际 Dify Docker network：`docker_default`。
- Bridge 加入 root 服务器实际 Dify Docker network：`docker_default`。
- 在 `/app/bin/dify/dify-1.11.2/docker/nginx/conf.d/default.conf.template` 增加 `/openclaw-api/` 反代。
- 如需 RDS 直连，创建 Dify DB 只读视图。
- 如需 RDS 直连，创建 Dify DB 只读用户并配置 RDS 白名单/安全组。
- 配置 `.env`。
- 配置日志。
- 配置健康检查。

---

## 23. 测试方案

### 23.1 网络测试

```bash
docker exec -it openclaw-bridge getent hosts api
docker exec -it openclaw-bridge curl -i http://api:5001/console/api/account/profile
docker exec -it openclaw-bridge curl http://openclaw:8080/health
```

预期：

```text
1. api 可以解析到 docker_default 网络内地址。
2. 未带登录 Cookie/CSRF 时，profile 接口返回 401/403 属于正常。
3. 带浏览器真实登录态转发时，Bridge 调 profile 接口能拿到当前用户。
4. OpenClaw /health 返回 ok。
```

如果 Bridge 需要直连 RDS，再增加：

```bash
docker exec -it openclaw-bridge nc -zv "$DIFY_DB_HOST" 5432
```

### 23.2 数据库权限测试

使用只读用户测试：

```bash
psql -h "$DIFY_DB_HOST" -U dify_openclaw_reader -d dify
```

测试：

```sql
SELECT tenant_id, account_id, name, email, avatar, created_at
FROM openclaw_user_basic_context
LIMIT 1;
```

确认不能：

```sql
DELETE FROM accounts;
UPDATE accounts SET name = 'x';
```

### 23.3 用户隔离测试

准备两个 Dify 用户：

```text
User A
User B
```

测试：

1. User A 登录 OpenClaw 页面。
2. User A 创建 session A1。
3. User A 发送消息。
4. User B 登录 OpenClaw 页面。
5. User B 不能看到 session A1。
6. User B 创建 session B1。
7. User A 不能看到 session B1。
8. 直接请求 `/sessions/A1/messages` 时，如果当前用户是 B，应返回 403。

### 23.4 Memory 隔离测试

1. User A 告诉 Agent 一个只属于 A 的信息。
2. User B 提问相关内容。
3. OpenClaw 不应泄露 A 的信息。
4. User A 再次提问，OpenClaw 可以记得 A 的信息。

### 23.5 视频 URL 测试

测试合法 URL：

```text
https://example.com/video.mp4
```

测试非法 URL：

```text
file:///etc/passwd
http://127.0.0.1:5432
http://localhost:8080
http://169.254.169.254/latest/meta-data
```

非法 URL 应被拒绝。

### 23.6 历史会话测试

1. 创建多个 session。
2. 每个 session 发送多条消息。
3. 刷新页面。
4. 重新进入 OpenClaw 页面。
5. 会话列表和消息历史应正确显示。

---

## 24. 灰度上线方案

### 24.1 第一阶段：内部开发环境

- 使用测试 Dify 用户。
- 使用测试 OpenClaw 容器。
- 使用测试数据库视图。
- 验证网络、鉴权、会话、视频链接流程。

### 24.2 第二阶段：内部小范围用户

- 只给少数用户显示 OpenClaw 菜单。
- 加 feature flag：

```text
ENABLE_OPENCLAW_ENTRY=true
```

- 记录错误日志。
- 验证用户隔离。

### 24.3 第三阶段：正式启用

- 打开 OpenClaw 菜单。
- 保留 feature flag，方便快速关闭入口。
- 保留 Nginx 配置回滚文件。
- 保留旧 Dify Web 镜像。

---

## 25. 回滚方案

如果出现问题：

### 25.1 关闭前端入口

设置：

```text
ENABLE_OPENCLAW_ENTRY=false
```

或隐藏菜单。

### 25.2 停止 Bridge

```bash
docker stop openclaw-bridge
```

### 25.3 恢复 Nginx

从模板中移除：

```nginx
location /openclaw-api/ { ... }
```

然后执行：

```bash
cd /app/bin/dify/dify-1.11.2/docker
docker compose restart nginx
docker exec docker-nginx-1 nginx -t
```

如果已替换 Dify Web 镜像，还必须将 `web` 服务镜像恢复为 `langgenius/dify-web:1.11.2` 或回滚到备份 compose。

### 25.4 不影响 Dify 主功能

因为本方案不改 Dify 核心 API，不写 Dify 数据库主表，所以回滚后：

- Dify 登录不受影响；
- Dify 原应用不受影响；
- Dify 知识库不受影响；
- OpenClaw 独立数据仍保留。

---

## 26. 风险清单与控制措施

| 风险 | 说明 | 控制措施 |
|---|---|---|
| 用户身份伪造 | 前端传 account_id 被篡改 | Bridge 必须通过 Dify profile API 获取 account_id 与 tenant_id |
| 用户会话串用 | 用户 B 访问 A 的 session | OpenClaw 查询 session 时校验 tenant-aware user_id |
| 数据库权限过大 | Bridge 读到不该读的数据 | 优先用 Dify profile API；如需 RDS，使用只读视图 + 最小授权 |
| OpenClaw 暴露公网 | Agent 接口被外部调用 | OpenClaw 只在 Docker network 内访问 |
| 视频 URL SSRF | 用户提交内网地址 | Bridge 做 DNS 解析后 IP 校验、重定向复查和可选白名单 |
| Dify 升级冲突 | 修改 Web 后合并困难 | 基于 Dify 1.11.2 源码构建自定义 web 镜像，使用 feature flag |
| OpenClaw 接口变化 | Bridge 调用失败 | Bridge 作为适配层，隔离变化 |
| 历史记录丢失 | OpenClaw session store 异常 | 备份 OpenClaw session/memory 存储 |
| 同步请求超时 | 视频分析耗时较长 | 超过 60 秒优先改任务轮询或 SSE；同步模式必须有取消/重试/超时 |
| RDS 不可达 | Bridge 容器无法连阿里云 RDS | 执行前配置 RDS 白名单/安全组并从 Bridge 容器测试 |

---

## 27. V2 扩展方向

V2 增加用户信息压缩摘要。

架构：

```text
Dify 用户历史行为 / 对话
        ↓
摘要生成任务
        ↓
user_profile_summary
        ↓
Bridge 读取摘要
        ↓
OpenClaw session 初始化上下文
```

V2 可新增字段：

```text
user_summary
preference_summary
behavior_summary
conversation_summary
last_summary_at
```

V2 建议新增视图：

```sql
CREATE VIEW openclaw_user_summary_context AS
SELECT
  taj.tenant_id,
  a.id AS account_id,
  a.name,
  a.email,
  s.user_summary,
  s.preference_summary,
  s.behavior_summary,
  s.last_summary_at
FROM accounts a
JOIN tenant_account_joins taj ON taj.account_id = a.id
LEFT JOIN user_profile_summaries s ON s.account_id = a.id AND s.tenant_id = taj.tenant_id;
```

---

## 28. 最终架构确认

最终推荐架构：

```text
Dify Web
  - OpenClaw 页面
  - 会话列表
  - 聊天输入
  - video_url 输入

Dify Nginx
  - /openclaw-api/* 转发到 Bridge

openclaw-bridge
  - 通过 Dify profile API 校验 Dify 用户
  - 读取 Dify 用户基础信息，按需读取 RDS 只读视图
  - 转发 OpenClaw 请求
  - 用户隔离控制

OpenClaw Dify Web Channel
  - 接收 Bridge 消息
  - 加载 user memory
  - 加载 session history
  - 调用 Agent
  - 保存会话历史

OpenClaw Memory / Session Store
  - user_id 隔离 memory
  - session_id 隔离会话历史
```

V1 最核心原则：

```text
1. Dify 是身份源。
2. Dify 是基础用户信息源。
3. OpenClaw 是会话历史主存储。
4. OpenClaw 是 Agent 和视频分析执行方。
5. Bridge 是唯一协议适配和权限控制层。
6. 不让 OpenClaw 直接读 Dify 数据库。
7. 不让 Dify Web 直接调用 OpenClaw。
8. 所有用户隔离都基于 tenant-aware user_id + session_id。
```

---

## 29. 执行前必须核验清单

正式开发前必须核验：

```text
1. Dify Docker network 为 docker_default，Bridge/OpenClaw 均已加入。
2. Dify compose 路径为 /app/bin/dify/dify-1.11.2/docker/docker-compose.yaml。
3. Dify 当前用户接口 GET http://api:5001/console/api/account/profile 可被 Bridge 访问。
4. Bridge 能转发 Cookie/Authorization/CSRF 相关头，并通过 profile API 拿到当前 account 与 tenant。
5. Dify 用户基础信息实际表结构已核验；如需 RDS 直连，只读视图包含 tenant_id/account_id。
6. RDS 白名单/安全组允许 Bridge 容器所在宿主机访问。
7. Dify Web 自定义镜像基于 1.11.2 构建，菜单和路由改造位置已通过本地/测试环境验证。
8. OpenClaw 实际部署位置、容器名、端口和 /health 已确认。
9. OpenClaw session/memory 实际存储位置已确认并可备份。
10. OpenClaw Agent 如何接收 message + video_url 已确认。
11. OpenClaw 已通过双用户测试，能稳定按 tenant-aware user_id/session_id 隔离。
12. Nginx 模板允许新增 /openclaw-api/，修改后 nginx -t 通过。
```

这些点不核验，任何方案都不能保证稳定运行。

---

## 30. 推荐实施顺序

严格按以下顺序执行：

```text
1. 备份 /app/bin/dify/dify-1.11.2/docker/docker-compose.yaml、.env、nginx/conf.d/default.conf.template。
2. 备份 Dify RDS 或至少确认已有可恢复备份。
3. 确认 docker_default 网络和 api/web/nginx 别名。
4. 确认 OpenClaw 实际部署位置；没有则先部署 OpenClaw 并提供 /health。
5. 开发 OpenClaw Dify Web Channel /health。
6. 开发 Bridge /health。
7. 让 Bridge 加入 docker_default。
8. 打通 Bridge 到 Dify profile API。
9. 实现 Dify 用户鉴权，生成 tenant_id:account_id。
10. 如需 RDS 扩展资料，创建 RDS 只读视图和只读用户，并从 Bridge 容器测试。
11. 打通 Bridge 到 OpenClaw /health。
12. 实现 sessions list。
13. 实现 create session。
14. 实现 messages list。
15. 实现 chat。
16. 实现 video_url SSRF 防护。
17. 基于 Dify 1.11.2 源码改 Dify Web 页面并构建自定义 web 镜像。
18. 替换 web 镜像，开启 feature flag 做页面冒烟测试。
19. 修改 Nginx 模板，增加 /openclaw-api/，执行 nginx -t 并重启 nginx。
20. 做双用户隔离测试。
21. 做 memory 隔离测试。
22. 做视频 URL 测试。
23. 做同步超时/取消/重试测试，必要时改任务轮询或 SSE。
24. 做回滚演练。
25. 内部灰度上线。
26. 正式上线。
```

---

## 31. 结论

本方案在当前需求下是最稳妥的架构：

```text
Dify Web + Bridge + OpenClaw Dify Web Channel
```

它满足：

- OpenClaw 内部可以按最直接方式新增 Dify Web 接入；
- Dify 只保留身份源和基础用户信息源；
- OpenClaw 保存完整会话历史；
- Dify 不重复保存 OpenClaw 完整历史；
- 每个用户可拥有多个会话；
- 每条消息可附带 video_url；
- memory 按 user_id 隔离；
- session history 按 session_id 隔离；
- Bridge 统一负责安全、鉴权、协议适配和用户资料读取。

只要严格执行本文档的网络、鉴权、数据库只读权限、session ownership 校验、灰度测试和回滚策略，系统可以达到稳定、可维护、可扩展的运行状态。
