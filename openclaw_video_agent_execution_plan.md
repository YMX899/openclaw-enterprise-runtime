# OpenClaw 短视频分析智能体执行方案（细颗粒度版）

> 版本：V1.0  
> 目标：在 OpenClaw 容器化运行环境中，实现一个面向短视频创作者的「视频链接接收、引导、解析、分析、改进建议」智能体。  
> 用户交互入口：Dify Web。  
> 会话、历史、视频记录、分析结果、工具调用编排：OpenClaw。  
> 第一版重点平台：抖音视频链接。  
> 第一版不支持：本地视频文件上传、复杂多平台、视频对比、多类型专用提示词、用户长期画像强制采集。

---

## 0. 已确认需求汇总

### 0.1 产品对象

第一版面向：

```text
短视频创作者
```

主要场景：

```text
用户通过 Dify Web 和 OpenClaw 智能体对话。
OpenClaw 引导用户发送抖音视频链接。
用户发送视频链接后，OpenClaw 调用视频解析工具读取视频。
读取完成后，结合短视频知识库，给出分析意见和改进建议。
```

### 0.2 核心能力

OpenClaw 需要实现：

```text
1. 接收用户消息
2. 判断用户是否已经发送视频链接
3. 如果没有视频，引导用户发送视频链接
4. 支持分析用户自己的视频
5. 支持分析对标爆款视频
6. 支持一个会话连续分析多个视频
7. 当前上下文默认绑定最新视频
8. 保存用户消息、助手回复、视频记录、视频分析结果
9. 每次分析默认引用短视频知识库中的分析标准
10. 调用已有视频分析工程，调用方式为命令行
11. 视频分析可采用“先同步、后续可异步扩展”的方案
12. 历史由 OpenClaw 提供，Dify Web 只负责用户交互入口
```

### 0.3 第一版边界

第一版只做：

```text
1. 主要支持抖音视频链接
2. 不支持本地视频文件上传
3. 不做复杂用户画像采集，用户基础信息默认未知
4. 不做评分
5. 需要输出改进建议
6. 需要输出可执行内容，例如开头改法、脚本改法、复拍建议
7. 暂不做不同视频类型的专用提示词分流
8. 一个会话可以连续分析多个视频，但默认围绕最新视频追问
9. 不强依赖 Dify 的 conversation_id
10. OpenClaw 以容器方式运行
```

---

## 1. 总体架构

### 1.1 架构定位

OpenClaw 在本方案中不是普通聊天机器人，也不是单纯消息存储层，而是：

```text
短视频分析场景下的对话编排层 + 工具调用层 + 记忆与历史存储层。
```

Dify Web 只承担：

```text
1. 用户输入
2. 用户界面展示
3. 调用 OpenClaw Bridge API
```

OpenClaw 承担：

```text
1. 会话状态管理
2. 用户消息识别
3. 视频链接识别
4. 引导式对话
5. 视频分析命令行工具调用
6. 知识库与提示词装配
7. 分析结果保存
8. 历史消息返回
9. 后续追问上下文绑定
```

视频分析工具承担：

```text
1. 抖音链接解析
2. 可播放视频流 URL 提取
3. Ark 多模态视频理解
4. 抽帧兜底
5. 生成视频理解结果 Markdown
```

### 1.2 总体调用链

```text
用户
  ↓
Dify Web
  ↓ HTTP
OpenClaw Bridge API
  ↓
OpenClaw communicate_agent
  ↓
Message Router / Intent Detector
  ↓
Session State Machine
  ↓
Video Link Resolver Decision
  ↓
Video Analysis Skill
  ↓ command line
已有视频分析工程 douyin_chong
  ↓
Ark 多模态模型 / 抖音解析逻辑
  ↓
Markdown 分析结果
  ↓
OpenClaw 结果整理 Agent
  ↓
短视频知识库增强建议
  ↓
保存 message / video / analysis_result
  ↓
返回 Dify Web 展示
```

---

## 2. 推荐工作目录结构

根据当前工程截图，建议保持 OpenClaw 原有目录规则，不破坏它自己生成的 agent/workspace/session 文件结构。

当前可见结构大致为：

```text
Backend/
├─ communicate_agent/                         # 负责和前台通信的智能体文件夹
│  ├─ agent/
│  │  └─ communicate_agnet-sale_copilot_.../  # OpenClaw 自己生成的智能体目录
│  │     ├─ agent/
│  │     ├─ session/
│  │     └─ workspace/
│  │        └─ workspace-communicate_agnet-sale_copilot_.../
│  │           ├─ .openclaw/
│  │           ├─ AGENTS.md
│  │           ├─ BOOTSTRAP.md
│  │           ├─ HEARTBEAT.md
│  │           ├─ IDENTITY.md
│  │           ├─ SOUL.md
│  │           ├─ TOOLS.md
│  │           └─ USER.md
│  └─ ...
├─ EventFollow-up/                            # 时间管理智能体预留目录
├─ saleguy/                                   # 销售分析智能体目录
│  ├─ agent/
│  ├─ employee_files/
│  └─ workspace/
├─ SKILL/                                     # skill 文件夹
├─ README.md
└─ share/                                     # 所有智能体共享资源
```

### 2.1 本功能新增目录建议

不要把业务文件散落在 OpenClaw 自动生成目录内，建议新增清晰分层：

```text
Backend/
├─ communicate_agent/
│  ├─ agent/
│  │  └─ communicate_agnet-sale_copilot_.../
│  │     ├─ agent/
│  │     ├─ session/
│  │     └─ workspace/
│  │        └─ workspace-communicate_agnet-sale_copilot_.../
│  │           ├─ .openclaw/
│  │           ├─ AGENTS.md
│  │           ├─ BOOTSTRAP.md
│  │           ├─ HEARTBEAT.md
│  │           ├─ IDENTITY.md
│  │           ├─ SOUL.md
│  │           ├─ TOOLS.md
│  │           ├─ USER.md
│  │           └─ prompts/                     # 新增：该 agent 私有提示词
│  │              ├─ system_role.md
│  │              ├─ conversation_policy.md
│  │              ├─ video_feedback_template.md
│  │              ├─ ask_for_video_template.md
│  │              └─ followup_template.md
│  │
│  ├─ bridge/                                 # 新增：Dify Web 调用 OpenClaw 的 HTTP 接口
│  │  ├─ routes.py 或 routes.ts
│  │  ├─ chat_controller.py 或 chat_controller.ts
│  │  ├─ session_controller.py 或 session_controller.ts
│  │  └─ schemas.py 或 schemas.ts
│  │
│  ├─ core/                                   # 新增：核心业务逻辑
│  │  ├─ message_router.py
│  │  ├─ intent_detector.py
│  │  ├─ session_state_machine.py
│  │  ├─ video_context_manager.py
│  │  ├─ response_planner.py
│  │  └─ chat_orchestrator.py
│  │
│  ├─ repositories/                           # 新增：数据库读写
│  │  ├─ user_repository.py
│  │  ├─ session_repository.py
│  │  ├─ message_repository.py
│  │  ├─ video_repository.py
│  │  └─ analysis_repository.py
│  │
│  ├─ services/                               # 新增：业务服务
│  │  ├─ user_service.py
│  │  ├─ session_service.py
│  │  ├─ message_service.py
│  │  ├─ video_service.py
│  │  ├─ analysis_service.py
│  │  ├─ prompt_service.py
│  │  └─ knowledge_service.py
│  │
│  └─ config/
│     ├─ app.yaml
│     ├─ database.yaml
│     ├─ video_tool.yaml
│     └─ prompt.yaml
│
├─ SKILL/
│  ├─ video_link_detect/                      # 新增 skill：识别视频链接
│  │  ├─ SKILL.md
│  │  └─ examples.md
│  ├─ douyin_video_analyze/                   # 新增 skill：调用视频分析命令行工具
│  │  ├─ SKILL.md
│  │  ├─ command_spec.md
│  │  └─ error_map.md
│  ├─ short_video_feedback/                   # 新增 skill：结合知识库生成建议
│  │  ├─ SKILL.md
│  │  ├─ output_framework.md
│  │  └─ branch_dialogues.md
│  ├─ conversation_state/                     # 新增 skill：状态机与分支对话
│  │  ├─ SKILL.md
│  │  └─ states.md
│  └─ knowledge_retrieval/                    # 新增 skill：知识库检索/装配
│     ├─ SKILL.md
│     └─ retrieval_rules.md
│
├─ share/
│  ├─ knowledge_base/                         # 共享知识库
│  │  ├─ short_video/
│  │  │  ├─ 爆款短视频制作与分析知识库.md
│  │  │  ├─ index.yaml
│  │  │  └─ chunks/
│  │  │     ├─ topic.md
│  │  │     ├─ structure.md
│  │  │     ├─ hook.md
│  │  │     ├─ picture_design.md
│  │  │     ├─ editing_review.md
│  │  │     └─ output_templates.md
│  │  └─ video_tool/
│  │     ├─ VIDEO_ANALYSIS_REPRODUCTION.md
│  │     └─ command_examples.md
│  │
│  ├─ prompts/                                # 共享提示词
│  │  ├─ video_analysis_base.md
│  │  ├─ video_analysis_user_video.md
│  │  ├─ video_analysis_benchmark_video.md
│  │  ├─ video_followup.md
│  │  ├─ video_rewrite_opening.md
│  │  ├─ video_rewrite_script.md
│  │  └─ video_reshoot_plan.md
│  │
│  ├─ tools/                                  # 外部工具挂载/包装
│  │  └─ douyin_chong_runner/
│  │     ├─ run_single_video.sh
│  │     ├─ run_action_extract.sh
│  │     ├─ parse_output.py
│  │     └─ README.md
│  │
│  └─ mappings/                               # 共享映射文件
│     ├─ intent_to_action.yaml
│     ├─ state_transition.yaml
│     ├─ platform_patterns.yaml
│     └─ error_reply_map.yaml
│
└─ docker/
   ├─ Dockerfile.openclaw
   ├─ docker-compose.yml
   ├─ entrypoint.sh
   └─ env.example
```

---

## 3. 容器化运行设计

### 3.1 OpenClaw 容器职责

OpenClaw 作为容器运行时，容器内至少需要具备：

```text
1. OpenClaw 后端服务
2. Bridge HTTP API
3. 数据库连接能力
4. 命令行调用视频分析工具的能力
5. 访问 share/knowledge_base 的能力
6. 访问 share/prompts 的能力
7. 访问 SKILL 目录的能力
8. 日志输出能力
```

### 3.2 视频分析工具运行方式

用户已确认：视频分析工程已有，OpenClaw 通过命令调用。

因此第一版推荐两种部署方式。

#### 方式 A：视频分析代码打进同一个 OpenClaw 容器

```text
OpenClaw 容器
├─ OpenClaw backend
├─ communicate_agent
├─ SKILL
├─ share
└─ video_analysis_tool/douyin_chong
```

优点：

```text
1. 部署简单
2. OpenClaw 可以直接 subprocess 调用 python -m douyin_chong...
3. 文件输出路径好管理
```

缺点：

```text
1. 容器变大
2. Python 依赖、Playwright、OpenCV、OpenClaw 依赖混在一起
3. 后续扩展成异步服务时需要拆分
```

#### 方式 B：视频分析工具单独容器

```text
openclaw_backend 容器
  ↓ command / docker exec / shared volume
video_analysis_worker 容器
```

优点：

```text
1. 职责更清晰
2. 后续扩展为队列/HTTP 服务更方便
3. Ark key、Playwright、OpenCV 依赖隔离
```

缺点：

```text
1. 第一版部署复杂度更高
2. 需要共享 volume 或者增加 HTTP API
```

### 3.3 第一版建议

第一版建议采用：

```text
同一个 docker-compose，两个容器：
1. openclaw_backend
2. postgres
```

视频分析工具先放在 `openclaw_backend` 容器内，通过命令行调用。

后续 V2 再拆成：

```text
1. openclaw_backend
2. video_analysis_worker
3. postgres
4. redis / queue
```

### 3.4 容器内关键路径

建议容器内统一路径：

```text
/app/backend                         # OpenClaw 后端代码
/app/backend/communicate_agent        # 当前智能体代码
/app/backend/SKILL                    # skills
/app/backend/share                    # 共享知识库/提示词/工具映射
/app/video_analysis/tik               # 已有视频解析工程
/app/data/analysis_runs                # 视频分析输出目录
/app/logs                              # 日志
```

### 3.5 docker-compose 示例

```yaml
version: "3.9"

services:
  openclaw_backend:
    build:
      context: .
      dockerfile: docker/Dockerfile.openclaw
    container_name: openclaw_backend
    env_file:
      - docker/env.example
    ports:
      - "8080:8080"
    volumes:
      - ./Backend:/app/backend
      - ./video_analysis/tik:/app/video_analysis/tik
      - ./data/analysis_runs:/app/data/analysis_runs
      - ./logs:/app/logs
    depends_on:
      - postgres
    command: ["/app/backend/docker/entrypoint.sh"]

  postgres:
    image: postgres:16
    container_name: openclaw_postgres
    environment:
      POSTGRES_USER: openclaw
      POSTGRES_PASSWORD: openclaw_password
      POSTGRES_DB: openclaw_video_agent
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

---

## 4. OpenClaw 智能体文件设计

### 4.1 `IDENTITY.md`

用于定义智能体身份。

建议内容：

```markdown
# IDENTITY

你是 OpenClaw 中的短视频分析与优化智能体。

你的服务对象是短视频创作者。
你的核心任务不是泛聊天，而是帮助用户：

1. 明确要分析的视频对象；
2. 引导用户发送抖音视频链接；
3. 分析用户自己的视频或对标爆款视频；
4. 结合短视频制作与分析知识库，输出可执行的改进建议；
5. 在用户追问时，默认围绕当前会话最新视频继续回答；
6. 如果用户没有视频，也可以先帮助用户明确账号方向、内容目标和拍摄思路。

你不能假装已经看过没有成功解析的视频。
你不能虚构视频里不存在的画面、人物、台词、产品功效。
如果视频解析失败，要清楚告诉用户失败原因，并引导用户换标准抖音视频链接。
```

### 4.2 `SOUL.md`

用于定义语气和价值观。

```markdown
# SOUL

你的表达风格：

1. 像短视频编导教练，而不是客服；
2. 先给结论，再给原因，再给怎么改；
3. 不说空话，尽量给用户可直接执行的建议；
4. 当用户表达模糊时，用少量问题引导，不连续审问；
5. 用户发视频后，不要只说“不错”，必须指出问题、机会和修改方向；
6. 对短视频创作者要直接，但不要羞辱；
7. 回复要有明确结构，适合用户复制给团队执行。
```

### 4.3 `TOOLS.md`

定义可用工具。

```markdown
# TOOLS

你可以使用以下 OpenClaw skills：

1. video_link_detect
   - 用于识别用户消息中的抖音视频链接。
   - 判断链接是否可能是视频链接、主页链接、搜索页链接或无效链接。

2. douyin_video_analyze
   - 用于通过命令行调用已有视频分析工程。
   - 输入：原始抖音视频链接、分析提示词、输出目录。
   - 输出：视频分析 Markdown、元数据、抽帧图片路径、错误信息。

3. short_video_feedback
   - 用于结合短视频知识库生成最终反馈。
   - 输入：视频分析结果、用户原始需求、当前会话目标、知识库片段。
   - 输出：结构化分析建议。

4. conversation_state
   - 用于判断当前会话阶段和下一步回复策略。

5. knowledge_retrieval
   - 用于从短视频知识库中选择分析维度、提示词、模板。
```

### 4.4 `USER.md`

第一版默认用户信息未知，不要求强采集。

```markdown
# USER

默认情况下，你不知道用户的账号类型、赛道、产品、目标用户和变现方式。

当这些信息缺失时，不要阻塞视频分析。
你可以在分析建议最后轻量询问：

“如果你愿意，我还可以按你的账号赛道/变现目标，把这条视频的修改方案再具体化。”

仅当用户要求从 0 做视频，或者要求非常具体的改法时，再收集：

1. 账号赛道
2. 发布平台
3. 视频目标
4. 目标用户
5. 产品/服务
6. 变现方式
```

### 4.5 `BOOTSTRAP.md`

```markdown
# BOOTSTRAP

上线后第一句不要机械自我介绍。

当用户进入新会话时，可以说：

“你可以直接把要分析的抖音视频链接发我。我会先帮你看这条视频的问题、爆点、开头、结构、画面和可改法。如果你是想拆对标爆款，也可以直接发对标视频。”

如果用户没有视频，只说想做短视频，先区分：

1. 分析已有视频
2. 拆解对标爆款
3. 从 0 设计一条视频
```

---

## 5. Skill 设计

### 5.1 Skill 总览

第一版需要 5 个核心 skill：

```text
1. video_link_detect
2. douyin_video_analyze
3. short_video_feedback
4. conversation_state
5. knowledge_retrieval
```

---

## 5.2 `video_link_detect` Skill

### 5.2.1 目标

识别用户消息中是否包含抖音视频链接。

### 5.2.2 输入

```json
{
  "content": "帮我看看这个视频 https://www.douyin.com/video/123",
  "attachments": []
}
```

### 5.2.3 输出

```json
{
  "has_video_link": true,
  "platform": "douyin",
  "link_type": "video",
  "urls": ["https://www.douyin.com/video/123"],
  "confidence": 0.95
}
```

### 5.2.4 链接类型

```text
video      标准视频链接，例如 /video/<id>
share      分享链接，例如 v.douyin.com 短链
modal      搜索页/精选页带 modal_id 的链接
profile    用户主页链接
unknown    无法判断
none       没有链接
```

### 5.2.5 第一版处理规则

```text
1. 标准视频链接：进入视频分析
2. 分享短链：进入视频分析，由底层工具解析
3. modal_id 链接：进入视频分析，由底层工具解析
4. 主页链接：第一版不主动批量抓取，提示用户发单条视频链接
5. 非抖音链接：提示第一版主要支持抖音视频链接
6. 无链接：进入引导分支
```

### 5.2.6 需要识别的模式

```regex
https?://www\.douyin\.com/video/[0-9A-Za-z_-]+[^\s]*
https?://v\.douyin\.com/[0-9A-Za-z_-]+/?[^\s]*
https?://www\.douyin\.com/[^\s]*modal_id=[0-9A-Za-z_-]+[^\s]*
https?://www\.iesdouyin\.com/share/video/[0-9A-Za-z_-]+[^\s]*
```

---

## 5.3 `douyin_video_analyze` Skill

### 5.3.1 目标

把用户给的抖音视频链接交给已有视频分析工程，用命令行方式调用。

### 5.3.2 输入

```json
{
  "user_id": "user_123",
  "session_id": "session_abc",
  "video_id": "vid_xxx",
  "source_url": "https://www.douyin.com/video/123",
  "analysis_prompt": "请重点分析这条视频的选题、前3秒钩子、结构、画面和改进建议。",
  "output_dir": "/app/data/analysis_runs/user_123/session_abc/vid_xxx"
}
```

### 5.3.3 输出

```json
{
  "status": "success",
  "output_markdown_path": "/app/data/analysis_runs/user_123/session_abc/vid_xxx/extract.md",
  "metadata_path": "/app/data/analysis_runs/user_123/session_abc/vid_xxx/metadata.jsonl",
  "frame_paths": [
    "/app/data/analysis_runs/user_123/session_abc/vid_xxx/photo/img_001.jpg"
  ],
  "raw_output": "...",
  "error": null
}
```

失败输出：

```json
{
  "status": "failed",
  "error_type": "DOUYIN_PARSE_FAILED",
  "error_message": "Could not find Douyin router data in share page HTML",
  "raw_stderr": "..."
}
```

### 5.3.4 推荐命令

第一版优先调用动作解析或单条视频解析。

可选命令 1：动作解析入口

```bash
cd /app/video_analysis/tik && \
python -m douyin_chong.video_action_extract \
  --text "${VIDEO_URL}" \
  --output "${OUTPUT_DIR}" \
  --fps 4 \
  --max-tokens 12000
```

可选命令 2：主知识源模式，不推荐第一版动态使用，因为需要写入 source-book/knowledge.md。

```bash
cd /app/video_analysis/tik && \
python -m douyin_chong --limit 1 --fps 4 --max-tokens 12000 --workers 1
```

可选命令 3：如果已有工程支持单条 URL + prompt 参数，优先改造为：

```bash
cd /app/video_analysis/tik && \
python -m douyin_chong.single_video_analyze \
  --url "${VIDEO_URL}" \
  --prompt-file "${PROMPT_FILE}" \
  --output "${OUTPUT_DIR}" \
  --fps 4 \
  --max-tokens 12000
```

### 5.3.5 建议新增 wrapper

在 `share/tools/douyin_chong_runner/run_single_video.sh` 中封装：

```bash
#!/usr/bin/env bash
set -euo pipefail

VIDEO_URL="$1"
PROMPT_FILE="$2"
OUTPUT_DIR="$3"

mkdir -p "$OUTPUT_DIR"

cd /app/video_analysis/tik

python -m douyin_chong.video_action_extract \
  --text "$VIDEO_URL" \
  --output "$OUTPUT_DIR" \
  --fps "${VIDEO_ANALYSIS_FPS:-4}" \
  --max-tokens "${VIDEO_ANALYSIS_MAX_TOKENS:-12000}"
```

如果当前工具暂时不能接收 prompt-file，就先用默认动作解析/高保真解析，OpenClaw 在后处理阶段再结合知识库生成反馈。

### 5.3.6 超时策略

第一版：

```text
命令行整体超时：600 秒
单条视频最长等待：10 分钟
超过后标记为 failed: TOOL_TIMEOUT
```

后续 V2：

```text
改为异步 job：用户先收到“已收到，正在分析”，前端轮询 job 状态。
```

---

## 5.4 `knowledge_retrieval` Skill

### 5.4.1 目标

根据用户当前问题，从短视频知识库中选择对应分析维度。

### 5.4.2 知识库存放位置

建议放在：

```text
Backend/share/knowledge_base/short_video/爆款短视频制作与分析知识库.md
```

并拆分为：

```text
Backend/share/knowledge_base/short_video/chunks/topic.md
Backend/share/knowledge_base/short_video/chunks/structure.md
Backend/share/knowledge_base/short_video/chunks/hook.md
Backend/share/knowledge_base/short_video/chunks/picture_design.md
Backend/share/knowledge_base/short_video/chunks/editing_review.md
Backend/share/knowledge_base/short_video/chunks/output_templates.md
```

### 5.4.3 知识库拆分规则

```text
topic.md:
- 选题
- 目标用户需求
- 解决方案
- 播放量上限判断

structure.md:
- 钩子
- 骨架
- 情绪刺点
- 内容是否抽象
- 信息密度
- 含金量

picture_design.md:
- 欲望 C 位
- 空间身份
- 物品证据
- 动作代替状态
- 细节代替大词
- 时间感
- 风格统一

editing_review.md:
- 掉人点复盘
- 剪辑节奏
- 音效
- 特效
- 音乐
- 拍摄
- 服化道
- 人物状态
- 文案

output_templates.md:
- 爆款视频分析回答模板
- 用户反馈结构
- 可复用分析顺序
```

### 5.4.4 检索策略

| 用户意图 | 需要检索的知识块 |
|---|---|
| 通用分析 | topic + structure + picture_design + output_templates |
| 为什么不爆 | topic + structure + editing_review |
| 开头怎么改 | hook + picture_design + output_templates |
| 画面怎么改 | picture_design |
| 脚本怎么改 | structure + topic + output_templates |
| 拆对标爆款 | topic + structure + picture_design + output_templates |
| 复拍方案 | picture_design + structure + editing_review |
| 发布后复盘 | editing_review |

---

## 5.5 `short_video_feedback` Skill

### 5.5.1 目标

把视频工具输出的原始解析结果，转成用户可读、可执行、符合短视频教练风格的最终回复。

### 5.5.2 输入

```json
{
  "user_message": "帮我看看这个视频为什么不爆",
  "video_analysis_markdown": "...",
  "knowledge_chunks": ["topic", "structure", "picture_design", "output_templates"],
  "analysis_mode": "user_video",
  "session_goal": null
}
```

### 5.5.3 输出框架

当用户分析自己的视频：

```markdown
我看完这条视频后，先给你一个直接结论：

## 1. 总评
这条视频最大的问题是：...
最值得保留的是：...
最应该优先改的是：...

## 2. 选题与目标用户
- 这条视频在解决什么问题：...
- 目标用户是谁：...
- 需求强不强：...
- 解决方案是否明确：...

## 3. 前 3 秒钩子
- 当前开头：...
- 问题：...
- 为什么容易掉人：...
- 建议改法：...

## 4. 内容结构
- 当前结构：...
- 哪一段信息密度不足：...
- 哪一段应该前置/删除/压缩：...

## 5. 画面与镜头
- 欲望 C 位是否清楚：...
- 空间是否交代身份：...
- 道具/动作是否能证明内容：...
- 画面是否承担信息：...

## 6. 表达与信息密度
- 有没有废话：...
- 有没有抽象表达：...
- 有没有每 10 秒给用户一个新信息：...

## 7. 可直接修改的方案
### 7.1 开头改法
给你 3 个开头版本：
1. ...
2. ...
3. ...

### 7.2 结构改法
建议改成：
1. ...
2. ...
3. ...

### 7.3 复拍建议
- 镜头 1：...
- 镜头 2：...
- 镜头 3：...

## 8. 优先级
你先改这 3 个地方：
1. ...
2. ...
3. ...
```

当用户分析对标爆款：

```markdown
这条对标视频值得拆的不是表面形式，而是它的爆款机制。

## 1. 它为什么容易爆
...

## 2. 它抓住了什么用户需求
...

## 3. 前 3 秒是怎么让人停下来的
...

## 4. 它的内容骨架
...

## 5. 它的画面设计
...

## 6. 哪些地方可以复刻
...

## 7. 哪些地方不建议照抄
...

## 8. 给你的迁移版本
如果你要借鉴这条视频，可以改成：
...
```

---

## 5.6 `conversation_state` Skill

### 5.6.1 状态定义

```text
new                         新会话
collecting_intent            正在判断用户想做什么
waiting_for_video            等待用户发视频链接
video_link_received          已收到视频链接
video_analyzing              视频分析中
video_analyzed               视频分析完成
feedback_given               已给出反馈
follow_up                    用户围绕当前视频追问
waiting_for_clarification    等待用户补充信息
error_recovering             错误恢复中
```

### 5.6.2 状态流转

```text
new
  ├─ 用户发视频链接 → video_link_received
  ├─ 用户说“帮我分析视频”但无链接 → waiting_for_video
  ├─ 用户说“我想做短视频” → collecting_intent
  └─ 用户闲聊 → collecting_intent

collecting_intent
  ├─ 用户选择分析已有视频 → waiting_for_video
  ├─ 用户选择拆对标爆款 → waiting_for_video
  ├─ 用户选择从 0 做视频 → waiting_for_clarification
  └─ 用户发视频链接 → video_link_received

waiting_for_video
  ├─ 用户发视频链接 → video_link_received
  ├─ 用户发主页链接 → waiting_for_video + 提示发单条视频
  ├─ 用户发非抖音链接 → waiting_for_video + 提示第一版支持抖音
  └─ 用户继续问“怎么做” → 给简短方向 + 继续要链接

video_link_received
  └─ 创建 video 记录 → video_analyzing

video_analyzing
  ├─ 工具成功 → video_analyzed
  ├─ 工具失败 → error_recovering
  └─ 工具超时 → error_recovering

video_analyzed
  └─ 生成最终反馈 → feedback_given

feedback_given
  ├─ 用户继续问当前视频 → follow_up
  ├─ 用户发新视频 → video_link_received
  ├─ 用户要求改开头 → follow_up
  ├─ 用户要求改脚本 → follow_up
  ├─ 用户要求复拍方案 → follow_up
  └─ 用户问无关问题 → 轻量回答后拉回视频优化
```

---

## 6. 数据库设计

### 6.1 users

```sql
CREATE TABLE users (
  id BIGSERIAL PRIMARY KEY,
  user_id VARCHAR(128) UNIQUE NOT NULL,
  display_name VARCHAR(255),
  avatar_url TEXT,
  profile JSONB DEFAULT '{}',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

### 6.2 sessions

```sql
CREATE TABLE sessions (
  id BIGSERIAL PRIMARY KEY,
  session_id VARCHAR(128) UNIQUE NOT NULL,
  user_id VARCHAR(128) NOT NULL,
  title VARCHAR(255),
  stage VARCHAR(64) DEFAULT 'new',
  current_video_id VARCHAR(128),
  current_analysis_mode VARCHAR(64),
  goal TEXT,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_user_updated ON sessions(user_id, updated_at DESC);
```

### 6.3 messages

```sql
CREATE TABLE messages (
  id BIGSERIAL PRIMARY KEY,
  message_id VARCHAR(128) UNIQUE NOT NULL,
  user_id VARCHAR(128) NOT NULL,
  session_id VARCHAR(128) NOT NULL,
  role VARCHAR(32) NOT NULL,
  content TEXT,
  message_type VARCHAR(64) DEFAULT 'text',
  video_id VARCHAR(128),
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_messages_user_session_time
ON messages(user_id, session_id, created_at ASC);
```

### 6.4 videos

```sql
CREATE TABLE videos (
  id BIGSERIAL PRIMARY KEY,
  video_id VARCHAR(128) UNIQUE NOT NULL,
  user_id VARCHAR(128) NOT NULL,
  session_id VARCHAR(128) NOT NULL,
  source_url TEXT NOT NULL,
  platform VARCHAR(64) DEFAULT 'douyin',
  source_type VARCHAR(32) DEFAULT 'url',
  link_type VARCHAR(64),
  title TEXT,
  author TEXT,
  duration_ms INTEGER,
  status VARCHAR(64) DEFAULT 'received',
  analysis_mode VARCHAR(64) DEFAULT 'user_video',
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_videos_user_session_time
ON videos(user_id, session_id, created_at DESC);
```

### 6.5 video_analysis_jobs

```sql
CREATE TABLE video_analysis_jobs (
  id BIGSERIAL PRIMARY KEY,
  job_id VARCHAR(128) UNIQUE NOT NULL,
  user_id VARCHAR(128) NOT NULL,
  session_id VARCHAR(128) NOT NULL,
  video_id VARCHAR(128) NOT NULL,
  status VARCHAR(64) DEFAULT 'pending',
  command TEXT,
  output_dir TEXT,
  stdout TEXT,
  stderr TEXT,
  error_type VARCHAR(128),
  error_message TEXT,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_jobs_video_id ON video_analysis_jobs(video_id);
```

### 6.6 video_analysis_results

```sql
CREATE TABLE video_analysis_results (
  id BIGSERIAL PRIMARY KEY,
  result_id VARCHAR(128) UNIQUE NOT NULL,
  user_id VARCHAR(128) NOT NULL,
  session_id VARCHAR(128) NOT NULL,
  video_id VARCHAR(128) NOT NULL,
  job_id VARCHAR(128) NOT NULL,
  raw_markdown TEXT,
  final_feedback TEXT,
  output_markdown_path TEXT,
  metadata_path TEXT,
  frame_paths JSONB DEFAULT '[]',
  knowledge_chunks JSONB DEFAULT '[]',
  prompt_version VARCHAR(64),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_results_video_id ON video_analysis_results(video_id);
```

---

## 7. Bridge API 设计

### 7.1 初始化会话

```http
POST /bridge/session/init
```

请求：

```json
{
  "user_id": "user_123",
  "session_id": "session_abc"
}
```

返回：

```json
{
  "user": {
    "user_id": "user_123",
    "profile": {}
  },
  "session": {
    "session_id": "session_abc",
    "stage": "new",
    "current_video_id": null
  },
  "messages": []
}
```

### 7.2 创建会话

```http
POST /bridge/session/create
```

请求：

```json
{
  "user_id": "user_123",
  "title": "视频分析会话"
}
```

返回：

```json
{
  "session_id": "sess_xxx",
  "title": "视频分析会话"
}
```

### 7.3 会话列表

```http
GET /bridge/sessions?user_id=user_123
```

返回：

```json
{
  "sessions": [
    {
      "session_id": "sess_001",
      "title": "第一个视频分析",
      "current_video_id": "vid_001",
      "updated_at": "2026-06-03T12:00:00Z"
    }
  ]
}
```

### 7.4 获取历史

```http
GET /bridge/session/history?user_id=user_123&session_id=sess_001
```

返回：

```json
{
  "session_id": "sess_001",
  "messages": [
    {
      "role": "user",
      "content": "帮我看看这个视频",
      "video_id": "vid_001",
      "created_at": "..."
    },
    {
      "role": "assistant",
      "content": "我看完后，最大的问题是...",
      "created_at": "..."
    }
  ]
}
```

### 7.5 核心聊天接口

```http
POST /bridge/chat
```

请求：

```json
{
  "user_id": "user_123",
  "session_id": "sess_001",
  "content": "帮我看看这个视频为什么不爆 https://www.douyin.com/video/123",
  "client_message_id": "optional"
}
```

同步返回：

```json
{
  "status": "ok",
  "session": {
    "session_id": "sess_001",
    "stage": "feedback_given",
    "current_video_id": "vid_xxx"
  },
  "messages": [
    {
      "role": "assistant",
      "content": "我看完这条视频后，先给你一个直接结论..."
    }
  ],
  "video": {
    "video_id": "vid_xxx",
    "status": "analyzed"
  }
}
```

分析失败返回：

```json
{
  "status": "tool_failed",
  "session": {
    "stage": "error_recovering"
  },
  "messages": [
    {
      "role": "assistant",
      "content": "这个链接我暂时没能成功解析。你可以换成抖音单条视频页链接，例如 https://www.douyin.com/video/xxx。"
    }
  ],
  "error": {
    "type": "DOUYIN_PARSE_FAILED"
  }
}
```

---

## 8. `/bridge/chat` 内部流程

### 8.1 主流程伪代码

```python
async def bridge_chat(input):
    user = ensure_user(input.user_id)
    session = ensure_session(input.user_id, input.session_id)

    user_message = save_user_message(
        user_id=input.user_id,
        session_id=session.session_id,
        content=input.content
    )

    link_result = video_link_detect(input.content)
    intent = detect_intent(input.content, link_result, session)
    decision = decide_next_action(session, intent, link_result)

    if decision.action == "ASK_FOR_VIDEO":
        reply = build_ask_for_video_reply(intent)
        save_assistant_message(reply)
        update_session_stage("waiting_for_video")
        return reply

    if decision.action == "ASK_FOR_SINGLE_VIDEO_LINK":
        reply = build_ask_single_video_link_reply()
        save_assistant_message(reply)
        update_session_stage("waiting_for_video")
        return reply

    if decision.action == "ANALYZE_VIDEO":
        video = create_video_record(...)
        link_message_to_video(user_message.message_id, video.video_id)
        update_session_current_video(video.video_id)
        update_session_stage("video_analyzing")

        prompt = build_video_analysis_prompt(
            user_message=input.content,
            mode=decision.analysis_mode,
            knowledge_base="short_video"
        )

        job = create_analysis_job(video.video_id, prompt)
        tool_result = run_douyin_video_analyze(job)

        if tool_result.failed:
            mark_job_failed(job, tool_result)
            mark_video_failed(video)
            reply = build_tool_error_reply(tool_result.error_type)
            save_assistant_message(reply)
            update_session_stage("error_recovering")
            return reply

        raw_markdown = read_tool_output(tool_result.output_markdown_path)
        knowledge_chunks = retrieve_knowledge(intent, mode=decision.analysis_mode)
        final_feedback = build_final_feedback(
            user_message=input.content,
            raw_markdown=raw_markdown,
            knowledge_chunks=knowledge_chunks,
            mode=decision.analysis_mode
        )

        save_analysis_result(...)
        save_assistant_message(final_feedback)
        mark_video_analyzed(video)
        update_session_stage("feedback_given")
        return final_feedback

    if decision.action == "FOLLOW_UP":
        current_video = get_current_video(session)
        latest_result = get_latest_analysis_result(current_video.video_id)
        knowledge_chunks = retrieve_knowledge(intent)
        reply = build_followup_reply(input.content, latest_result, knowledge_chunks)
        save_assistant_message(reply)
        update_session_stage("follow_up")
        return reply
```

---

## 9. 用户意图识别

### 9.1 意图枚举

```text
analyze_my_video             分析我的视频
analyze_benchmark_video      分析对标爆款
ask_how_to_make_video        问怎么做短视频
ask_for_script               要脚本
ask_rewrite_opening          改开头
ask_rewrite_script           改整条脚本
ask_reshoot_plan             要复拍方案
ask_picture_improvement      问画面怎么改
ask_why_not_viral            问为什么不爆
send_video_link              发送视频链接
send_profile_link            发送主页链接
send_invalid_link            发送无效链接
casual_chat                  闲聊
unsupported_platform         不支持的平台
```

### 9.2 规则识别词

#### 分析自己视频

```text
帮我看看
分析一下我的视频
这条视频为什么不行
为什么不爆
哪里有问题
帮我优化
怎么改
```

#### 对标爆款

```text
对标
爆款
拆一下这个爆款
我想模仿这个
这个为什么火
这个视频怎么复刻
```

#### 开头改法

```text
开头怎么改
前3秒怎么改
钩子怎么写
怎么让人停下来
开场白
```

#### 脚本改法

```text
帮我写一版
脚本怎么改
重写一下
按这个改成我的
给我一版文案
```

#### 复拍方案

```text
怎么重拍
复拍方案
镜头怎么拍
拍摄清单
分镜
```

#### 画面问题

```text
画面怎么改
镜头问题
拍得不好看
场景怎么布置
画面设计
```

---

## 10. 分支对话设计

下面按照真实用户表达设计完整分支。

---

### 10.1 新用户进入，没有明确需求

用户可能说：

```text
你好
在吗
你是干嘛的
我想做短视频
```

OpenClaw 回复：

```text
你可以直接把要分析的抖音视频链接发我。

我会帮你看：
1. 这条视频为什么能不能留住人；
2. 前 3 秒钩子有没有问题；
3. 选题和目标用户是否清楚；
4. 内容结构、信息密度、画面设计哪里要改；
5. 给你一版可以直接执行的修改方案。

如果你是想拆对标爆款，也可以直接发对标视频链接。
```

状态：

```text
new -> waiting_for_video
```

---

### 10.2 用户想做短视频，但没有视频

用户可能说：

```text
我想做短视频
我现在不知道发什么
我想做一个账号
帮我规划一下
```

OpenClaw 回复：

```text
可以。你现在有两个方向可以选：

1. 如果你已经有视频，直接发抖音视频链接，我先帮你拆问题和改法；
2. 如果你还没有视频，我可以先帮你从 0 设计一条视频。

如果从 0 做，我需要你补充 4 个信息：
- 你做什么赛道？
- 你想吸引什么人？
- 你的视频目标是涨粉、获客、带货，还是建立人设？
- 你有没有产品或服务要卖？
```

状态：

```text
new -> collecting_intent
```

---

### 10.3 用户说“帮我分析视频”，但没发链接

用户可能说：

```text
帮我分析一个视频
我有个视频想让你看看
帮我看看哪里能改
```

OpenClaw 回复：

```text
可以，直接把抖音视频链接发我就行。

我会先按这个顺序看：
1. 选题和目标用户；
2. 前 3 秒钩子；
3. 内容结构和信息密度；
4. 画面设计和镜头信息；
5. 最后给你具体修改方案。
```

状态：

```text
collecting_intent -> waiting_for_video
```

---

### 10.4 用户只发视频链接，不说需求

用户：

```text
https://www.douyin.com/video/123
```

OpenClaw 处理：

```text
1. 识别为抖音视频链接
2. 默认分析模式：user_video
3. 保存视频
4. 调用视频分析工具
5. 输出通用分析 + 改进建议
```

OpenClaw 回复结构：

```text
我先按通用短视频优化标准帮你看这条视频。

[分析结果]

如果你想继续，我还可以接着帮你做：
1. 单独改前 3 秒开头；
2. 重写一版完整脚本；
3. 出一版复拍分镜；
4. 按对标爆款方式拆它的可复刻点。
```

状态：

```text
waiting_for_video -> video_analyzing -> feedback_given
```

---

### 10.5 用户发链接并说“为什么不爆”

用户：

```text
这个视频为什么不爆？https://www.douyin.com/video/123
```

OpenClaw 分析重点：

```text
1. 选题需求是否足够大
2. 前 3 秒是否有停留理由
3. 内容是否抽象
4. 信息密度是否持续
5. 是否有情绪刺点
6. 画面是否把欲望放在 C 位
7. 是否有废话和掉人点
```

回复结构：

```markdown
我先直接说结论：这条视频不容易爆，主要不是因为拍得不够努力，而是因为【核心问题】。

## 1. 最大问题
...

## 2. 前 3 秒为什么留不住人
...

## 3. 选题有没有需求
...

## 4. 内容结构哪里弱
...

## 5. 画面有没有浪费
...

## 6. 你应该优先改什么
1. ...
2. ...
3. ...

## 7. 我给你一版开头改法
...
```

---

### 10.6 用户发对标爆款

用户：

```text
帮我拆一下这个爆款，我想模仿它 https://www.douyin.com/video/123
```

分析模式：

```text
benchmark_video
```

回复结构：

```markdown
这条视频可以作为对标，但不要只学它的表面形式。
真正值得拆的是它的爆款机制。

## 1. 它抓住了什么需求
...

## 2. 它前 3 秒怎么让人停下来
...

## 3. 它的内容骨架是什么
...

## 4. 它的情绪刺点在哪里
...

## 5. 它的画面设计为什么有效
...

## 6. 你可以复刻的地方
...

## 7. 你不能照抄的地方
...

## 8. 给你的迁移版本
如果你要迁移到自己的账号，可以这样拍：
...
```

---

### 10.7 用户发送主页链接

用户：

```text
https://www.douyin.com/user/xxxxx
```

第一版不做主页批量抓取，回复：

```text
这个看起来是抖音主页链接。

第一版我先帮你分析单条视频，效果会更准确。你可以点进主页里选一条最想分析的视频，把单条视频链接发我。

格式类似：
https://www.douyin.com/video/xxxx
```

状态：

```text
waiting_for_video
```

---

### 10.8 用户发送非抖音链接

用户：

```text
https://www.xiaohongshu.com/...
```

回复：

```text
这个链接暂时不是第一版重点支持的抖音视频链接。

你可以先发抖音单条视频链接，我能更稳定地解析视频内容并给出建议。
如果你只有这个平台的视频，也可以把视频内容大概描述给我，我可以先按脚本和画面思路帮你分析，但不会假装已经读取了视频。
```

---

### 10.9 链接解析失败

常见失败：

```text
1. 抖音风控
2. 视频 ID 提取失败
3. 页面结构变化
4. 链接过期
5. 视频被删除
6. 链接不是单条视频
```

回复：

```text
这个链接我暂时没有成功解析，所以我不能假装已经看过视频。

你可以试一下：
1. 发抖音单条视频页链接，而不是主页链接；
2. 确认视频没有被删除或设为私密；
3. 如果是分享短链，可以打开后复制浏览器里的完整链接再发我。

你也可以简单描述一下视频内容，我先按你描述的信息帮你判断开头、结构和画面怎么改。
```

---

### 10.10 视频分析工具超时

回复：

```text
这条视频解析时间有点长，本次没有在限定时间内完成。

你可以稍后重试，或者换一条更短的单条视频链接。
如果你愿意，也可以先告诉我这条视频的大概内容和目标，我先帮你从选题、开头和结构上判断一版。
```

---

### 10.11 用户问“开头怎么改”

前提：session.current_video_id 存在。

用户：

```text
那这个开头怎么改？
```

OpenClaw 行为：

```text
1. 读取当前最新视频分析结果
2. 检索 hook + picture_design + output_templates
3. 输出 3 个开头版本
```

回复：

```markdown
这条视频的开头要改的核心是：先给观众一个明确的停留理由。

我给你 3 个版本：

## 版本 1：痛点型
...

## 版本 2：反常识型
...

## 版本 3：结果前置型
...

我更建议你先用第 X 个，因为它和这条视频的内容最匹配。
```

---

### 10.12 用户问“帮我写一版脚本”

回复：

```markdown
可以，我按这条视频的原始方向，给你改成一版更容易留人的脚本。

## 新脚本结构

### 1. 前 3 秒
...

### 2. 问题放大
...

### 3. 解决方案
...

### 4. 证据/案例
...

### 5. 结尾引导
...

## 完整口播稿
...

## 拍摄提醒
- ...
```

---

### 10.13 用户问“怎么复拍”

回复：

```markdown
如果这条视频要复拍，我建议不要只改文案，要连画面一起改。

## 复拍目标
...

## 分镜方案

### 镜头 1：前 3 秒
- 画面：...
- 动作：...
- 文案：...
- 目的：...

### 镜头 2：问题展示
...

### 镜头 3：解决方案
...

### 镜头 4：证明
...

### 镜头 5：结尾引导
...

## 拍摄前检查
- 欲望 C 位是否明确
- 空间是否交代身份
- 道具是否进入动作
- 关掉声音后是否还能看懂
```

---

### 10.14 用户连续发第二个视频

用户：

```text
再看这个 https://www.douyin.com/video/456
```

OpenClaw 行为：

```text
1. 创建新 video 记录 vid_456
2. session.current_video_id 更新为 vid_456
3. 不删除旧视频
4. 后续追问默认围绕 vid_456
```

回复中可提示：

```text
收到，我会把这条作为当前正在分析的视频。后续你直接问“开头怎么改”“脚本怎么改”，我默认都是围绕这条最新视频回答。
```

---

### 10.15 用户想对比两个视频

第一版不支持深度对比，但可以轻度处理。

用户：

```text
这两个视频哪个更好？
```

如果当前会话已有多个视频：

```text
第一版我可以先做轻量对比，主要从选题、开头、结构、画面和转化方向看。
如果要做严格逐帧对比，需要后续版本增加“视频对比分析”能力。
```

回复结构：

```markdown
我先做轻量对比：

| 维度 | 视频 A | 视频 B | 哪个更好 |
|---|---|---|---|
| 选题需求 | ... | ... | ... |
| 前 3 秒 | ... | ... | ... |
| 内容结构 | ... | ... | ... |
| 画面设计 | ... | ... | ... |
| 可复刻性 | ... | ... | ... |

结论：...
```

---

## 11. 提示词系统设计

### 11.1 提示词分层

最终传给分析/生成环节的提示词分为 5 层：

```text
1. OpenClaw Agent 系统身份提示词
2. 视频分析基础提示词
3. 短视频知识库维度提示词
4. 用户本轮附加要求
5. 输出结构模板
```

### 11.2 基础视频分析提示词

文件：

```text
Backend/share/prompts/video_analysis_base.md
```

内容：

```markdown
你正在帮助短视频创作者分析一条抖音视频。

请严格基于视频中真实出现的画面、动作、字幕、口播、节奏和可见信息进行分析。
不能虚构视频里没有出现的内容。
不能因为用户希望你判断就编造数据。

分析时默认关注：

1. 选题：它洞察了什么需求，给了什么解决方案；
2. 人群：目标用户是谁，需求量是否足够大；
3. 前 3 秒：有没有钩子、反差、痛点、结果前置；
4. 内容结构：是否有清晰骨架；
5. 信息密度：是否持续输出新信息；
6. 含金量：是否有新鲜感、价值感、认知增量；
7. 表达：是否抽象，用户是否容易理解；
8. 画面：欲望 C 位、空间、物品、动作、细节是否有效；
9. 转化：是否有信任建立和行动引导；
10. 修改建议：必须给可执行方案。
```

### 11.3 用户视频分析提示词

```markdown
这是一条用户希望优化的自己的视频。

你的重点不是夸它，而是找出：
1. 最大问题；
2. 最值得保留的点；
3. 最优先修改的 3 个地方；
4. 可直接替换的开头；
5. 可直接执行的结构调整；
6. 是否需要复拍，以及复拍怎么拍。

语气要直接、专业、可执行。
```

### 11.4 对标爆款分析提示词

```markdown
这是一条用户想拆解和学习的对标爆款视频。

请不要只总结内容，而要拆出爆款机制：
1. 它抓住了什么用户需求；
2. 前 3 秒如何制造停留；
3. 内容骨架如何推进；
4. 情绪刺点在哪里；
5. 画面设计如何激活欲望；
6. 哪些元素可以迁移；
7. 哪些元素不能照抄；
8. 如何改写成用户自己的版本。
```

### 11.5 最终回复输出模板

```markdown
## 直接结论
...

## 这条视频的问题/爆点
...

## 分维度分析
### 1. 选题
...
### 2. 前 3 秒
...
### 3. 内容结构
...
### 4. 信息密度
...
### 5. 画面设计
...
### 6. 转化引导
...

## 可执行修改方案
...

## 优先级
...

## 下一步你可以让我继续做
1. 改开头
2. 重写脚本
3. 出复拍分镜
4. 拆成对标模板
```

---

## 12. 消息流向设计

### 12.1 页面打开

```text
Dify Web
  -> POST /bridge/session/init
OpenClaw
  -> ensure user
  -> ensure session
  -> read messages
  -> read current_video_id
  -> return history
Dify Web
  -> render messages
```

### 12.2 用户发普通消息

```text
Dify Web
  -> POST /bridge/chat
OpenClaw
  -> save user message
  -> detect intent
  -> no video link
  -> decide ASK_FOR_VIDEO or FOLLOW_UP
  -> save assistant message
  -> return reply
Dify Web
  -> render reply
```

### 12.3 用户发视频链接

```text
Dify Web
  -> POST /bridge/chat
OpenClaw
  -> save user message
  -> detect douyin video link
  -> create video record
  -> update session.current_video_id
  -> build prompt
  -> create video_analysis_job
  -> command call video tool
  -> read output markdown
  -> retrieve knowledge chunks
  -> build final feedback
  -> save result
  -> save assistant message
  -> return final feedback
Dify Web
  -> render final feedback
```

### 12.4 用户追问

```text
Dify Web
  -> POST /bridge/chat
OpenClaw
  -> save user message
  -> no new video link
  -> session has current_video_id
  -> read latest analysis result
  -> detect follow-up type
  -> retrieve specific knowledge chunks
  -> generate follow-up reply
  -> save assistant message
  -> return reply
```

---

## 13. 错误处理设计

### 13.1 错误类型

```text
NO_VIDEO_LINK
UNSUPPORTED_PLATFORM
PROFILE_LINK_NOT_SUPPORTED
DOUYIN_PARSE_FAILED
VIDEO_DELETED_OR_PRIVATE
TOOL_TIMEOUT
ARK_RATE_LIMIT
ARK_API_ERROR
OUTPUT_FILE_MISSING
EMPTY_ANALYSIS_RESULT
UNKNOWN_ERROR
```

### 13.2 错误回复映射

| 错误 | 用户回复 |
|---|---|
| NO_VIDEO_LINK | “直接把抖音单条视频链接发我，我会帮你分析。” |
| UNSUPPORTED_PLATFORM | “第一版主要支持抖音视频链接。” |
| PROFILE_LINK_NOT_SUPPORTED | “这是主页链接，请发单条视频链接。” |
| DOUYIN_PARSE_FAILED | “链接暂时没解析成功，请换完整视频页链接。” |
| VIDEO_DELETED_OR_PRIVATE | “视频可能被删除、私密或不可访问。” |
| TOOL_TIMEOUT | “这条视频解析超时，可以稍后重试或换更短链接。” |
| ARK_RATE_LIMIT | “视频理解服务繁忙，稍后重试。” |
| OUTPUT_FILE_MISSING | “工具执行完但没有生成结果，需要记录日志排查。” |

---

## 14. 日志与调试

### 14.1 每次 `/bridge/chat` 记录

```json
{
  "trace_id": "trace_xxx",
  "user_id": "user_123",
  "session_id": "sess_001",
  "message_id": "msg_001",
  "intent": "send_video_link",
  "stage_before": "waiting_for_video",
  "stage_after": "feedback_given",
  "video_id": "vid_001",
  "job_id": "job_001",
  "duration_ms": 124000,
  "status": "success"
}
```

### 14.2 视频分析命令日志

保存：

```text
/app/logs/video_analysis/yyyy-mm-dd/job_xxx.log
```

内容：

```text
command
stdout
stderr
exit_code
start_time
end_time
```

---

## 15. MVP 开发步骤

### 阶段 1：目录和配置

```text
1. 在 Backend/share/knowledge_base/short_video 放入知识库
2. 拆分 chunks
3. 在 Backend/share/prompts 放入提示词模板
4. 在 Backend/SKILL 下创建 5 个 skill 目录
5. 配置 docker-compose
```

验收：

```text
容器启动后能读取 share/knowledge_base 和 share/prompts。
```

### 阶段 2：数据库

```text
1. 创建 users
2. 创建 sessions
3. 创建 messages
4. 创建 videos
5. 创建 video_analysis_jobs
6. 创建 video_analysis_results
```

验收：

```text
能创建用户、会话、消息、视频记录。
```

### 阶段 3：Bridge API

```text
1. 实现 /bridge/session/init
2. 实现 /bridge/session/create
3. 实现 /bridge/sessions
4. 实现 /bridge/session/history
5. 实现 /bridge/chat 基础版本
```

验收：

```text
Dify Web 可以打开页面、创建会话、发送消息、恢复历史。
```

### 阶段 4：视频链接识别

```text
1. 实现抖音标准链接识别
2. 实现短链识别
3. 实现 modal_id 链接识别
4. 实现主页链接识别
5. 实现非抖音链接拒绝
```

验收：

```text
用户发不同链接时能进入正确分支。
```

### 阶段 5：命令行工具调用

```text
1. 把已有视频分析工程放入容器
2. 配置 ARK_API_KEY
3. 编写 run_single_video.sh
4. OpenClaw subprocess 调用
5. 读取输出 extract.md 和 metadata.jsonl
6. 保存 job 结果
```

验收：

```text
给一个抖音视频链接，OpenClaw 能生成 video_analysis_result。
```

### 阶段 6：最终反馈生成

```text
1. 读取视频分析原始结果
2. 检索知识库 chunks
3. 应用 user_video / benchmark_video 模板
4. 输出结构化反馈
5. 保存 assistant message
```

验收：

```text
用户收到的不只是工具原始 Markdown，而是可执行的短视频优化建议。
```

### 阶段 7：追问处理

```text
1. 当前视频上下文绑定
2. 识别“开头怎么改”
3. 识别“脚本怎么改”
4. 识别“怎么复拍”
5. 识别“画面怎么改”
6. 输出对应分支回复
```

验收：

```text
用户分析完视频后继续追问，OpenClaw 默认围绕最新视频回答。
```

---

## 16. 验收用例

### 用例 1：新用户无视频

输入：

```text
我想做短视频
```

期望：

```text
OpenClaw 区分分析已有视频、拆对标爆款、从 0 做视频，并引导用户发视频链接或补充信息。
```

### 用例 2：用户发抖音链接

输入：

```text
https://www.douyin.com/video/123
```

期望：

```text
OpenClaw 保存消息、保存视频、调用工具、返回分析建议。
```

### 用例 3：用户问为什么不爆

输入：

```text
这个为什么不爆 https://www.douyin.com/video/123
```

期望：

```text
回复重点包括选题、前3秒、结构、信息密度、画面、可改法。
```

### 用例 4：用户拆对标爆款

输入：

```text
帮我拆这个爆款，我想模仿 https://www.douyin.com/video/123
```

期望：

```text
回复包括爆款机制、可复刻点、不可照抄点、迁移版本。
```

### 用例 5：用户发主页链接

输入：

```text
https://www.douyin.com/user/xxx
```

期望：

```text
提示第一版先发单条视频链接。
```

### 用例 6：用户追问开头

前置：已分析一个视频。

输入：

```text
那开头怎么改？
```

期望：

```text
输出 3 个开头版本，并说明推荐哪一个。
```

### 用例 7：用户连续发第二条视频

输入：

```text
再看这个 https://www.douyin.com/video/456
```

期望：

```text
创建第二条视频记录，并把 current_video_id 更新为最新视频。
```

---

## 17. V2 扩展方向

```text
1. 视频分析异步任务队列
2. 支持本地视频上传
3. 支持视频对比分析
4. 支持小红书、快手、TikTok、B 站
5. 支持不同类型视频专用提示词
6. 支持用户画像长期记忆
7. 支持账号级复盘和多视频汇总
8. 支持自动生成拍摄脚本、分镜表、剪辑表
9. 支持抖音主页批量抓取
10. 支持前端展示分析进度和抽帧图片
```

---

## 18. 最终结论

第一版不要把系统做复杂。

最稳的 MVP 是：

```text
Dify Web 负责交互。
OpenClaw 容器负责会话、状态、历史、视频记录、工具调用、知识库增强和最终回复。
视频分析工程通过命令行调用。
短视频知识库放在 share/knowledge_base。
提示词放在 share/prompts。
Skills 放在 Backend/SKILL。
每个会话可连续分析多个视频，但默认当前上下文绑定最新视频。
用户没发视频时，引导发抖音单条视频链接。
用户发视频后，分析并输出可执行改进方案。
```

这样可以保证：

```text
1. 产品链路闭环；
2. OpenClaw 职责清晰；
3. Dify 不承担历史和状态；
4. 后续扩展视频上传、异步分析、多平台都不会推翻架构；
5. 知识库、提示词、工具和状态机都有明确位置。
```
