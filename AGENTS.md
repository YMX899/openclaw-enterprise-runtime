每次工程有功能上的改动都要进行版本git管理，本地与云端同步。

## API key 用途标注

- 当前新增的百炼/OpenAI-compatible API key 是给 OpenClaw agent 普通聊天 API 使用的，不是 `openclaw-video` 视频分析模型 worker 的 key pool。
- 这些普通聊天 API key 目前不要配置到 `BAILIAN_API_KEYS`，也不要作为 `video_model_request` lane 的模型分析 key 使用。
- `openclaw-video` 视频分析模型 key pool 只认 worker 侧配置：`BAILIAN_API_KEYS` / `BAILIAN_API_KEY`、`BAILIAN_OPENAI_BASE_URL`、`BAILIAN_MODEL`、`BAILIAN_API_KEY_COOLDOWN_SECONDS`。
- OpenClaw agent 普通聊天和视频分析模型是两条不同调用链：普通聊天走 agent/bridge/gateway/Dify 相关路径；视频分析走 `video_jobs` -> `video-analysis-worker` -> `/files` + `/responses`。
- 系统里已有但未接入视频 worker 的 API key，应标注为“普通聊天 agent key，未用于视频分析模型”，避免后续误判为视频高并发 key pool。
- 任何 API key 明文只能放在服务器 secret/env 中，不要提交到 Git、说明文件、测试 fixture、evidence 或日志。说明文件里只允许写用途、来源系统、hash 前缀或序号，不写完整 key。
