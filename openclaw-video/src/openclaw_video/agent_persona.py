"""Short-video coach agent persona, intent detection and conversation guardrails.

This is the Bridge-side "rule floor": stable, unit-testable logic that gives the
OpenClaw chat agent a fixed short-video-analyst identity, classifies user intent,
and blocks unsupported requests with fixed replies so the agent cannot drift or
hallucinate capabilities it does not have.

Design (confirmed with user): rules decide identity/intent/guardrails here; the
agent only generates natural language. The agent never reads uploaded video
content - that is handled by the dedicated worker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- persona ----------------------------------------------------------------

SYSTEM_PERSONA = (
    "你是 OpenClaw 短视频分析与优化助手，服务对象是短视频创作者。"
    "你的任务不是泛聊天，而是帮用户分析抖音视频、拆解爆款、并给出可执行的改进建议。\n\n"
    "硬性规则：\n"
    "1. 只用中文回答。\n"
    "2. 你只能分析通过本平台视频管线（抖音视频链接读取或视频文件上传）真实解析出来的视频。"
    "你不能假装看过没有成功解析的视频，不能虚构画面、台词、数据或产品功效。\n"
    "3. 第一版只支持抖音视频链接和视频文件上传。对于 YouTube、B 站、小红书、微博等其他平台，"
    "明确说明当前只支持抖音，不要声称能转录字幕或读取这些平台的视频。\n"
    "4. 如果用户还没有提供视频，引导他粘贴抖音视频链接或上传视频文件；也可以先就选题、开头、"
    "结构、画面思路给方向性建议，但要说明这是基于描述而非已解析的视频。\n"
    "5. 分析时围绕：选题与目标用户、前3秒钩子、内容结构与信息密度、画面设计、转化引导，"
    "并给出可直接执行的修改方案（开头改法、脚本改法、复拍建议）。\n"
    "6. 语气像专业的短视频编导教练：先结论、再原因、再怎么改；直接但不羞辱用户。"
)

GREETING = (
    "你好，我是 OpenClaw 短视频分析助手。你可以直接把抖音视频链接粘贴给我，"
    "或点击输入框左侧的 ＋ 上传视频文件，我会帮你拆这条视频的选题、前3秒钩子、"
    "结构、画面和可执行的改法。如果你是想拆对标爆款，也可以直接发对标视频。"
)

# --- intents ----------------------------------------------------------------

INTENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("analyze_benchmark_video", ("对标", "爆款", "拆一下这个", "模仿这个", "为什么火", "怎么复刻", "怎么火")),
    ("ask_rewrite_opening", ("开头怎么改", "前3秒", "前三秒", "钩子怎么", "怎么让人停", "开场")),
    ("ask_rewrite_script", ("写一版", "脚本怎么改", "重写", "改成我的", "给我一版文案", "口播稿")),
    ("ask_reshoot_plan", ("怎么重拍", "复拍", "镜头怎么拍", "拍摄清单", "分镜")),
    ("ask_picture_improvement", ("画面怎么改", "镜头问题", "拍得不好", "场景怎么", "画面设计")),
    ("ask_why_not_viral", ("为什么不爆", "为什么不行", "为什么没人看", "播放量低", "为什么不火")),
    ("analyze_my_video", ("帮我看看", "分析一下我的", "哪里有问题", "帮我优化", "怎么改", "帮我分析")),
    ("ask_how_to_make_video", ("我想做短视频", "不知道发什么", "做一个账号", "帮我规划", "从0", "从零")),
)


def detect_intent(text: str) -> str:
    lowered = (text or "").strip()
    for intent, keywords in INTENT_RULES:
        if any(keyword in lowered for keyword in keywords):
            return intent
    return "casual_chat"


# --- link / platform guardrails ---------------------------------------------

_DOUYIN_RE = re.compile(
    r"https?://(?:[\w.-]*\.)?(?:douyin\.com|iesdouyin\.com)/\S+", re.IGNORECASE
)
_DOUYIN_SHORT_RE = re.compile(r"https?://v\.douyin\.com/\S+", re.IGNORECASE)
_ANY_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

_OTHER_PLATFORMS = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "bilibili.com": "B 站",
    "b23.tv": "B 站",
    "xiaohongshu.com": "小红书",
    "xhslink.com": "小红书",
    "weibo.com": "微博",
    "kuaishou.com": "快手",
    "tiktok.com": "TikTok",
}


@dataclass(frozen=True)
class GuardrailReply:
    """A fixed reply that should be returned without invoking the agent."""

    content: str
    reason: str


def has_douyin_link(text: str) -> bool:
    return bool(_DOUYIN_RE.search(text or "") or _DOUYIN_SHORT_RE.search(text or ""))


def _find_other_platform(text: str) -> str | None:
    for url in _ANY_URL_RE.findall(text or ""):
        lowered = url.lower()
        for host, label in _OTHER_PLATFORMS.items():
            if host in lowered:
                return label
    return None


def _is_profile_link(text: str) -> bool:
    return bool(re.search(r"douyin\.com/user/", text or "", re.IGNORECASE))


def guardrail_for_message(text: str) -> GuardrailReply | None:
    """Return a fixed reply for messages the agent must not free-form answer.

    Covers: non-douyin platform links and douyin profile links. Real douyin
    video links and pure text fall through (text goes to the persona agent;
    video links are routed to the analysis pipeline by the caller).
    """
    if _is_profile_link(text):
        return GuardrailReply(
            content=(
                "这看起来是抖音主页链接。第一版我先帮你分析单条视频，效果会更准确。"
                "请点进主页选一条最想分析的视频，把单条视频链接发我，格式类似 "
                "https://www.douyin.com/video/xxxx 。"
            ),
            reason="profile_link",
        )
    if has_douyin_link(text):
        return None
    platform = _find_other_platform(text)
    if platform:
        return GuardrailReply(
            content=(
                f"这个链接看起来是{platform}的，第一版我只支持抖音视频链接，"
                "还不能读取或转录其他平台的视频，也不会假装已经看过它。\n\n"
                "你可以发抖音单条视频链接（形如 https://www.douyin.com/video/xxxx），"
                "或者把视频内容大概描述给我，我可以先从选题、开头和结构上帮你判断。"
            ),
            reason="unsupported_platform",
        )
    return None


def build_agent_message(content: str, *, is_first_turn: bool) -> str:
    """Prepend the persona on the first turn so the agent has a fixed identity.

    The Gateway agent keeps its own session memory, so the persona only needs to
    be injected once per OpenClaw session (first user turn).
    """
    if is_first_turn:
        return SYSTEM_PERSONA + "\n\n用户消息：" + content
    return content
