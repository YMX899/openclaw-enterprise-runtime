# OpenClaw / Dify Server Handover

更新时间：2026-06-12

## 1. 服务器工程位置

本工程已准备迁移到服务器 `root`，目标目录：

```text
/project/Dify
```

该目录用于后续开发、编译、构建和交接。服务器上已有一套线上运行路径，注意不要混淆：

```text
/app/bin/openclaw-video/current/openclaw-video
```

`/app/bin/...` 是当前线上部署目录，`/project/Dify` 是后续开发工作目录。需要发布到线上时，应先在 `/project/Dify` 完成验证，再按部署脚本或明确发布流程同步到线上目录。

## 2. 本地到服务器的版本交接方式

本次上传使用 Git bundle 保留版本历史，然后在服务器 `/project/Dify` 克隆得到完整 Git 工作树。

服务器工程应能执行：

```bash
cd /project/Dify
git status
git log --oneline -5
```

如需继续开发，请在服务器上创建新分支：

```bash
cd /project/Dify
git checkout -b codex/<task-name>
```

## 3. 目录结构

核心目录如下：

```text
/project/Dify
├── openclaw-video/                         # 短视频分析 sidecar 主工程
│   ├── pyproject.toml                      # Python 包与依赖声明
│   ├── docker-compose.openclaw-video.yaml  # bridge / gateway / worker / postgres 编排
│   ├── src/openclaw_video/                 # 后端 Python 代码
│   ├── web/                                # Web 聊天端，Vite + TypeScript
│   ├── tests/                              # Python 单元/集成测试
│   ├── docker/                             # Dockerfile
│   ├── database/migrations/                # bridge 数据库迁移
│   ├── scripts/                            # 本项目运维与验证脚本
│   ├── vendor/douyin_chong/                # 抖音/视频解析适配来源
│   └── secrets/                            # 本地/服务器密钥，不应提交
├── artifacts/                              # 知识库等运行依赖资源
├── scripts/                                # 根目录辅助脚本
├── HANDOVER.md                             # 当前工程功能/测试交接文档
└── SERVER_HANDOVER.md                      # 本文档，服务器开发交接入口
```

## 4. 架构关系

主要服务关系：

```text
Web UI
  -> openclaw-bridge FastAPI
      -> bridge-postgres
      -> openclaw-gateway WebSocket
      -> video-analysis-worker
          -> douyin_chong / vendor 解析适配器
          -> 视频下载、时长探测、帧限制与分析流程
```

关键模块：

- `openclaw-video/src/openclaw_video/bridge_app.py`：FastAPI bridge，负责登录、会话、聊天、任务创建、Web 静态资源和 API。
- `openclaw-video/src/openclaw_video/video_link_probe.py`：视频链接探测、平台识别、重定向解析、时长读取和安全限制。
- `openclaw-video/src/openclaw_video/video_limits.py`：视频处理上限，当前长视频链接限制为 5 分钟以内。
- `openclaw-video/src/openclaw_video/worker_service.py`：视频分析任务执行入口。
- `openclaw-video/src/openclaw_video/douyin_legacy_adapter.py`：抖音/视频解析 legacy 适配入口。
- `openclaw-video/src/openclaw_video/douyin_wrapper.py`：对 vendor 解析器的包装。
- `openclaw-video/web/src/main.ts`：网页端聊天 UI 主逻辑。
- `openclaw-video/web/src/styles.css`：网页端布局、深色模式、Markdown 显示与按钮样式。
- `openclaw-video/src/openclaw_video/webdist/`：`npm run build` 生成并被 bridge 服务读取的静态资源目录。

## 5. 环境要求

服务器开发环境至少需要：

- Python 3.11 或更高版本。
- Node.js 18 或更高版本，建议 Node.js 20/22。
- npm。
- Git。
- Docker 与 Docker Compose plugin，用于完整容器构建和服务编排。
- 常用构建工具：`build-essential`、`python3-venv`、`python3-pip`。

Python 依赖以 `openclaw-video/pyproject.toml` 为准。Web 依赖以 `openclaw-video/web/package.json` 与 `package-lock.json` 为准。

## 6. 服务器构建验证命令

推荐在服务器上按以下顺序验证：

```bash
cd /project/Dify/openclaw-video
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -e ".[dev]"
python -m compileall -q src/openclaw_video
python -m pytest tests
```

Web 构建：

```bash
cd /project/Dify/openclaw-video/web
npm ci
npm run build
```

Compose 配置检查：

```bash
cd /project/Dify/openclaw-video
docker compose -f docker-compose.openclaw-video.yaml config
```

如只需快速重建线上 bridge，可参考：

```bash
cd /project/Dify/openclaw-video
scripts/root_rebuild_bridge_fast.sh
```

该脚本之前已修复：会把 `webdist` 同步进容器中的 installed package 目录，避免线上仍使用旧前端资源。

## 7. 当前重要功能状态

- 网页端聊天 UI 已调整为短视频分析助手品牌，不再显示 OpenClaw 作为页面标题。
- 左侧对话列表显示用户第一条消息的简称，而不是固定“本次对话简介”。
- 对话回复使用 Markdown 渲染，并调整了 `h2`、段落、引用块间距，使回复更紧凑。
- 对话消息显示发送时间，操作按钮以图标为主，支持复制、重生成、删除等操作。
- 深色模式下聊天输入框和左侧会话三点操作已修复过可见性和可点击问题。
- 视频链接支持抖音短链、抖音长链、B 站短链、B 站移动端链接等格式。
- 长视频链接已限制为 5 分钟以内，超过限制应拒绝分析，避免任务过长或资源失控。

## 8. 运行与发布注意事项

- `/project/Dify` 是开发目录，不建议直接作为线上运行目录。
- 当前线上服务仍在 `/app/bin/openclaw-video/current/openclaw-video` 下运行。
- 发布前必须完成 Web 构建、Python 编译/测试和容器配置检查。
- `secrets/`、`.env`、密钥、cookies、上传文件和运行输出不得提交到 Git。
- `openclaw-video/output/`、`node_modules/`、`web/dist/`、`__pycache__/` 等为生成物，不应作为源代码交接。
- 如需排查线上服务，优先检查容器：

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker logs --tail=200 openclaw-video-openclaw-bridge-1
docker logs --tail=200 openclaw-video-video-analysis-worker-1
docker logs --tail=200 openclaw-video-openclaw-gateway-1
```

## 9. 接手建议

新 agent 接手时建议先做四件事：

1. 读取 `SERVER_HANDOVER.md` 和 `HANDOVER.md`。
2. 在 `/project/Dify` 执行 `git status`，确认工作树状态。
3. 在 `/project/Dify/openclaw-video` 执行 Python 编译/测试与 Web 构建。
4. 如果要改线上服务，先确认 `/project/Dify` 与 `/app/bin/openclaw-video/current/openclaw-video` 的差异，再决定同步策略。

涉及远程服务器操作时，当前 Codex 环境必须使用 `ssh-skill`，不要直接调用原生 `ssh` 或 `scp`。
