from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

from .agent_persona import (
    ANALYSIS_FRAMEWORK,
    HOOK_GUIDE,
    MARKDOWN_OUTPUT_RULES,
    PICTURE_PRINCIPLES,
    SYSTEM_PERSONA,
    _STATE_HINTS,
    build_agent_message,
    build_branch_prompt,
    build_continue_prompt,
    current_video_from_history,
    derive_state,
    detect_intent,
    error_reply_for,
    fixed_state_reply,
    guardrail_for_message,
    is_continue_request,
    knowledge_for_intent,
    load_full_knowledge_context,
)


CONTEXT_MARKER_PREFIX = "__openclaw_context_marker__"

_BRANCH_INSTRUCTIONS: dict[str, str] = {
    "ask_rewrite_opening": (
        "用户想改开头。先点出当前开头的核心问题，再给 3 个可直接用的开头版本"
        "（痛点型 / 反常识型 / 结果前置型），最后说明更推荐哪个版本以及原因。"
    ),
    "ask_rewrite_script": (
        "用户想要一版脚本。按这条视频的原始方向改成更容易留人的脚本，给出新脚本结构、"
        "完整口播稿和拍摄提醒。"
    ),
    "ask_reshoot_plan": (
        "用户想复拍。给复拍目标 + 分镜方案（每个镜头含画面/动作/文案/目的）+ 拍摄前检查。"
    ),
    "ask_picture_improvement": (
        "用户想改画面。围绕镜头语言、场景、道具、信息可视化给具体可执行的画面改法。"
    ),
    "ask_why_not_viral": (
        "用户问为什么不爆。按选题与目标用户、前3秒钩子、内容结构与信息密度、画面设计、"
        "转化引导五个维度逐条诊断，指出最关键的 1-2 个硬伤并给改法。"
    ),
}

_KNOWLEDGE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hook_guide", ("开头", "前3秒", "前三秒", "钩子")),
    ("picture_principles", ("画面", "镜头", "场景", "道具")),
    ("script_framework", ("脚本", "文案", "口播")),
    ("structure_framework", ("复拍", "分镜")),
    ("analysis_framework", ("为什么不爆", "诊断")),
    ("benchmark_framework", ("对标", "爆款", "复刻")),
)

_INTENT_KNOWLEDGE_KEYS: dict[str, tuple[str, ...]] = {
    "ask_rewrite_opening": ("hook_guide",),
    "ask_picture_improvement": ("picture_principles",),
    "ask_reshoot_plan": ("picture_principles", "structure_framework"),
    "ask_rewrite_script": ("script_framework",),
    "ask_why_not_viral": ("analysis_framework",),
    "analyze_benchmark_video": ("benchmark_framework", "analysis_framework"),
}

_SELECTED_KNOWLEDGE: dict[str, str] = {
    "hook_guide": HOOK_GUIDE,
    "picture_principles": PICTURE_PRINCIPLES,
    "analysis_framework": ANALYSIS_FRAMEWORK,
    "script_framework": (
        "脚本框架：前3秒给停留理由，随后放大问题，再给解决方案、证据案例和结尾引导；"
        "每 10 秒至少有一个新信息点，删掉不能推动理解或情绪的废话。"
    ),
    "structure_framework": (
        "复拍/分镜框架：每个镜头都要明确画面、动作、文案和目的；先保证静音可懂，"
        "再用道具、场景和细节证明卖点。"
    ),
    "benchmark_framework": (
        "对标拆解框架：拆需求、开头停留理由、内容骨架、画面证据、可迁移点和不能照抄的点；"
        "复刻的是结构和心理触发，不是照搬台词与画面表层。"
    ),
}


@dataclass(frozen=True)
class OrchestratorInput:
    principal_id: str
    session_id: str
    history: tuple[Any, ...]
    user_content: str
    current_video_job_id: str | None = None
    current_video_status: str | None = None
    current_video_error_code: str | None = None
    current_video_result: dict[str, Any] | None = None
    has_uploaded_or_link_video: bool = False
    is_video_submission: bool = False
    is_upload_submission: bool = False
    previous_assistant: str | None = None


@dataclass(frozen=True)
class OrchestratorDecision:
    route: str
    intent: str
    state: str
    should_create_video_job: bool = False
    should_call_gateway: bool = False
    fixed_reply: str | None = None
    prompt: str = ""
    knowledge_mode: str = "none"
    knowledge_keys: tuple[str, ...] = ()
    analysis_context_mode: str = "none"
    analysis_context_injected: bool = False
    analysis_context_chars: int = 0
    full_kb_reason: str | None = None
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisContext:
    mode: str
    text: str
    injected: bool
    budget: int


@dataclass(frozen=True)
class KnowledgeContext:
    mode: str
    text: str
    keys: tuple[str, ...] = ()
    full_kb_reason: str | None = None


def _env_int(name: str, default: int) -> int:
    try:
        value = int(str(os.environ.get(name, default)).strip())
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def _trim(text: str | None, budget: int, *, tail: bool = False) -> str:
    value = str(text or "").strip()
    if not value or len(value) <= budget:
        return value
    if tail:
        return value[-budget:].lstrip()
    return value[:budget].rstrip() + "..."


def is_internal_context_marker(message: Any) -> bool:
    return getattr(message, "role", None) == "system" and str(getattr(message, "content", "")).startswith(
        CONTEXT_MARKER_PREFIX
    )


class ContextMarker:
    @staticmethod
    def content(*, session_id: str, job_id: str | None, marker_type: str = "analysis_detail_injected") -> str:
        payload = {"type": marker_type, "session_id": session_id, "job_id": job_id}
        return CONTEXT_MARKER_PREFIX + json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def analysis_detail_injected(history: Iterable[Any]) -> bool:
        for message in history:
            if not is_internal_context_marker(message):
                continue
            raw = str(getattr(message, "content", ""))[len(CONTEXT_MARKER_PREFIX) :]
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "analysis_detail_injected":
                return True
        return False


class KnowledgeSelector:
    def __init__(self) -> None:
        self.full_kb_max_chars = _env_int("OPENCLAW_FULL_KB_MAX_CHARS", 12000)
        self.full_kb_mode = os.environ.get("OPENCLAW_FULL_KB_MODE", "auto").strip().lower() or "auto"

    def select(self, *, intent: str, user_content: str, state: str) -> KnowledgeContext:
        if self.full_kb_mode == "off":
            return self._compact(intent, user_content, state)

        full_reason = self._full_kb_reason(user_content, state)
        if self.full_kb_mode == "on" and not full_reason:
            full_reason = "debug_mode"
        if full_reason:
            text = _trim(load_full_knowledge_context(), self.full_kb_max_chars)
            if text:
                return KnowledgeContext("full_kb", text, full_kb_reason=full_reason)

        return self._compact(intent, user_content, state)

    def _compact(self, intent: str, user_content: str, state: str = "") -> KnowledgeContext:
        keys = list(_INTENT_KNOWLEDGE_KEYS.get(intent, ()))
        for key, keywords in _KNOWLEDGE_KEYWORDS:
            if any(keyword in user_content for keyword in keywords) and key not in keys:
                keys.append(key)
        if keys:
            blocks = [f"【{key}】\n{_SELECTED_KNOWLEDGE[key]}" for key in keys if key in _SELECTED_KNOWLEDGE]
            return KnowledgeContext("compact_by_intent", "\n\n".join(blocks).strip(), tuple(keys))
        if intent == "casual_chat" and state not in {"feedback_given", "follow_up"}:
            return KnowledgeContext("none", "")
        if intent == "ask_how_to_make_video":
            return KnowledgeContext("none", "")
        return KnowledgeContext("compact_by_intent", knowledge_for_intent(intent), ("analysis_framework",))

    @staticmethod
    def _full_kb_reason(user_content: str, state: str) -> str | None:
        text = user_content or ""
        if any(key in text for key in ("完整知识库", "完整方法论", "全部方法论", "系统性", "全链路", "从头到尾")):
            return "explicit_full_methodology"
        if "完整诊断" in text and any(key in text for key in ("方法论", "系统", "全链路", "深度")):
            return "explicit_deep_diagnosis"
        if state in {"feedback_given", "follow_up"} and "深度诊断" in text and not any(
            key in text for key in ("开头", "脚本", "画面", "复拍", "分镜")
        ):
            return "broad_deep_diagnosis"
        return None


class AnalysisContextSelector:
    def __init__(self) -> None:
        self.detail_once_max_chars = _env_int("OPENCLAW_DETAIL_ONCE_MAX_CHARS", 8000)
        self.selected_detail_max_chars = _env_int("OPENCLAW_SELECTED_DETAIL_MAX_CHARS", 3000)
        self.summary_max_chars = _env_int("OPENCLAW_SUMMARY_CONTEXT_MAX_CHARS", 1500)

    def select(self, *, result: dict[str, Any] | None, history: Iterable[Any], prefer_detail: bool) -> AnalysisContext:
        if not isinstance(result, dict):
            return AnalysisContext("none", "", False, 0)
        summary = str(result.get("summary") or "").strip()
        detail = str(result.get("analysis_detail") or summary).strip()
        if not detail and not summary:
            return AnalysisContext("none", "", False, 0)
        if not ContextMarker.analysis_detail_injected(history):
            return AnalysisContext(
                "detail_once",
                _trim(detail or summary, self.detail_once_max_chars),
                True,
                self.detail_once_max_chars,
            )
        if prefer_detail and detail:
            return AnalysisContext(
                "selected_detail",
                _trim(detail, self.selected_detail_max_chars),
                False,
                self.selected_detail_max_chars,
            )
        return AnalysisContext("summary_only", _trim(summary or detail, self.summary_max_chars), False, self.summary_max_chars)


class PromptBuilder:
    def __init__(self) -> None:
        self.previous_assistant_max_chars = _env_int("OPENCLAW_PREVIOUS_ASSISTANT_MAX_CHARS", 5000)

    def build(
        self,
        *,
        user_content: str,
        route: str,
        state: str,
        intent: str,
        analysis: AnalysisContext,
        knowledge: KnowledgeContext,
        previous_assistant: str | None = None,
    ) -> str:
        parts = [SYSTEM_PERSONA, MARKDOWN_OUTPUT_RULES]
        hint = _STATE_HINTS.get(state or "")
        if hint:
            parts.append(hint)
        parts.append("本轮路由：" + route)
        branch = self._branch_instruction(route, intent)
        if branch:
            parts.append("本轮分支要求：" + branch)
        if analysis.text:
            parts.append(
                "以下是当前这条视频已经完成的真实分析结果，请严格基于它回答，不要脱离它另行虚构画面或台词：\n"
                + analysis.text
            )
        elif route.startswith("follow_up") or route == "answer_initial_video_question":
            parts.append("（当前没有可用的视频分析结果。不要假装看过视频。）")
        if knowledge.text:
            label = "完整短视频知识库" if knowledge.mode == "full_kb" else "相关短视频方法论知识块"
            parts.append(f"以下是{label}，回答必须结合它：\n{knowledge.text}")
        if route == "continue_previous" and previous_assistant:
            parts.append(
                "以下是上一条助手回复，请从它的末尾继续，不要从头重写：\n"
                + _trim(previous_assistant, self.previous_assistant_max_chars, tail=True)
            )
        parts.append("用户消息：" + user_content)
        return "\n\n".join(part for part in parts if part).strip()

    @staticmethod
    def _branch_instruction(route: str, intent: str) -> str:
        if route == "continue_previous":
            return (
                "用户是在要求你续写上一条没有完整输出的回答，不是提出新问题。必须从上一条助手回复的最后一句之后自然接着写；"
                "不要重新开题，不要重复已经输出的内容，不要改变上一条回答的方案方向。"
            )
        if route == "general_chat":
            return "如果用户没有提供视频，只给方向性建议，并引导其发送支持平台单条视频链接或上传视频。"
        return _BRANCH_INSTRUCTIONS.get(intent, "")


class SkillOrchestrator:
    def __init__(self, *, knowledge_selector: KnowledgeSelector | None = None) -> None:
        self.knowledge_selector = knowledge_selector or KnowledgeSelector()
        self.analysis_selector = AnalysisContextSelector()
        self.prompt_builder = PromptBuilder()

    def decide(self, input: OrchestratorInput) -> OrchestratorDecision:
        content = input.user_content.strip()
        intent = detect_intent(content)

        if input.is_video_submission or input.is_upload_submission or input.has_uploaded_or_link_video:
            return OrchestratorDecision(
                route="create_video_job",
                intent=intent,
                state="video_link_received",
                should_create_video_job=True,
                debug={"skill": "openclaw_video.orchestrator_skill"},
            )

        guardrail = guardrail_for_message(content)
        if guardrail is not None:
            return OrchestratorDecision(
                route="fixed_guardrail",
                intent=intent,
                state="waiting_for_video",
                fixed_reply=guardrail.content,
                debug={"reason": guardrail.reason},
            )

        latest_status = input.current_video_status or ""
        video_failed = latest_status in {"failed", "timed_out", "cancelled"}
        video_analyzing = latest_status in {"queued", "running"}
        has_terminal_video = bool(input.current_video_job_id and latest_status in {"succeeded", "completed"})
        has_current_video = bool(input.current_video_job_id and input.current_video_result)
        has_user_history = any(getattr(item, "role", None) == "user" for item in input.history)
        state = derive_state(
            has_user_history=has_user_history,
            has_terminal_video=has_terminal_video,
            video_failed=video_failed,
            intent=intent,
            has_current_video=has_current_video,
            video_analyzing=video_analyzing,
        )

        previous_assistant = input.previous_assistant or self._previous_assistant(input.history)
        wants_continuation = bool(previous_assistant and is_continue_request(content))
        if video_failed and not wants_continuation:
            return OrchestratorDecision(
                route="fixed_error_recovering",
                intent=intent,
                state=state,
                fixed_reply=error_reply_for(input.current_video_error_code),
            )
        if video_analyzing and not wants_continuation:
            fixed = fixed_state_reply(state, intent)
            return OrchestratorDecision(route="fixed_video_analyzing", intent=intent, state=state, fixed_reply=fixed)

        fixed = fixed_state_reply(state, intent)
        if fixed is not None and not wants_continuation:
            return OrchestratorDecision(route="fixed_waiting_for_video", intent=intent, state=state, fixed_reply=fixed)

        route = self._gateway_route(intent, state, wants_continuation)
        prefer_detail = route != "general_chat"
        analysis = self.analysis_selector.select(
            result=input.current_video_result,
            history=input.history,
            prefer_detail=prefer_detail,
        )
        knowledge = self.knowledge_selector.select(intent=intent, user_content=content, state=state)
        prompt = self.prompt_builder.build(
            user_content=content,
            route=route,
            state=state,
            intent=intent,
            analysis=analysis,
            knowledge=knowledge,
            previous_assistant=previous_assistant if wants_continuation else None,
        )
        return OrchestratorDecision(
            route=route,
            intent=intent,
            state=state,
            should_call_gateway=True,
            prompt=prompt,
            knowledge_mode=knowledge.mode,
            knowledge_keys=knowledge.keys,
            analysis_context_mode=analysis.mode,
            analysis_context_injected=analysis.injected,
            analysis_context_chars=len(analysis.text),
            full_kb_reason=knowledge.full_kb_reason,
            debug={"skill": "openclaw_video.orchestrator_skill"},
        )

    def decide_initial_video_question(self, input: OrchestratorInput) -> OrchestratorDecision:
        content = input.user_content.strip()
        intent = detect_intent(content)
        state = "follow_up"
        analysis = self.analysis_selector.select(
            result=input.current_video_result,
            history=input.history,
            prefer_detail=True,
        )
        knowledge = self.knowledge_selector.select(intent=intent, user_content=content, state=state)
        prompt = self.prompt_builder.build(
            user_content=content,
            route="answer_initial_video_question",
            state=state,
            intent=intent,
            analysis=analysis,
            knowledge=knowledge,
        )
        return OrchestratorDecision(
            route="answer_initial_video_question",
            intent=intent,
            state=state,
            should_call_gateway=True,
            prompt=prompt,
            knowledge_mode=knowledge.mode,
            knowledge_keys=knowledge.keys,
            analysis_context_mode=analysis.mode,
            analysis_context_injected=analysis.injected,
            analysis_context_chars=len(analysis.text),
            full_kb_reason=knowledge.full_kb_reason,
            debug={"skill": "openclaw_video.orchestrator_skill"},
        )

    @staticmethod
    def _previous_assistant(history: Iterable[Any]) -> str:
        for message in reversed(tuple(history)):
            if getattr(message, "role", None) == "assistant" and str(getattr(message, "content", "")).strip():
                return str(message.content)
        return ""

    @staticmethod
    def _gateway_route(intent: str, state: str, wants_continuation: bool) -> str:
        if wants_continuation:
            return "continue_previous"
        if state in {"feedback_given", "follow_up"}:
            return {
                "ask_rewrite_opening": "follow_up_opening",
                "ask_rewrite_script": "follow_up_script",
                "ask_picture_improvement": "follow_up_picture",
                "ask_reshoot_plan": "follow_up_reshoot",
                "ask_why_not_viral": "follow_up_why_not_viral",
            }.get(intent, "follow_up_general")
        return "general_chat"


def current_video_job_id_from_history(messages: Iterable[Any], job_status_fn: Any) -> str | None:
    job_id, _ = current_video_from_history(messages, job_status_fn)
    return job_id


class LegacyBridgeOrchestrator:
    """Compatibility mode used when OPENCLAW_ORCHESTRATOR_SKILL_ENABLED=0."""

    def decide(self, input: OrchestratorInput) -> OrchestratorDecision:
        content = input.user_content.strip()
        intent = detect_intent(content)
        if input.is_video_submission or input.is_upload_submission or input.has_uploaded_or_link_video:
            return OrchestratorDecision(
                route="create_video_job",
                intent=intent,
                state="video_link_received",
                should_create_video_job=True,
            )
        guardrail = guardrail_for_message(content)
        if guardrail is not None:
            return OrchestratorDecision(
                route="fixed_guardrail",
                intent=intent,
                state="waiting_for_video",
                fixed_reply=guardrail.content,
                debug={"reason": guardrail.reason},
            )
        latest_status = input.current_video_status or ""
        video_failed = latest_status in {"failed", "timed_out", "cancelled"}
        video_analyzing = latest_status in {"queued", "running"}
        has_current_video = bool(input.current_video_job_id and input.current_video_result)
        has_terminal_video = bool(input.current_video_job_id and latest_status in {"succeeded", "completed"})
        has_user_history = any(getattr(item, "role", None) == "user" for item in input.history)
        state = derive_state(
            has_user_history=has_user_history,
            has_terminal_video=has_terminal_video,
            video_failed=video_failed,
            intent=intent,
            has_current_video=has_current_video,
            video_analyzing=video_analyzing,
        )
        previous_assistant = input.previous_assistant or SkillOrchestrator._previous_assistant(input.history)
        wants_continuation = bool(previous_assistant and is_continue_request(content))
        if video_failed and not wants_continuation:
            return OrchestratorDecision(
                route="fixed_error_recovering",
                intent=intent,
                state=state,
                fixed_reply=error_reply_for(input.current_video_error_code),
            )
        fixed = fixed_state_reply(state, intent)
        if fixed is not None and not wants_continuation:
            route = "fixed_video_analyzing" if state == "video_analyzing" else "fixed_waiting_for_video"
            return OrchestratorDecision(route=route, intent=intent, state=state, fixed_reply=fixed)
        if wants_continuation:
            prompt = build_continue_prompt(
                content,
                previous_assistant=previous_assistant,
                analysis_context=self._analysis_text(input.current_video_result),
                knowledge_context=load_full_knowledge_context(),
            )
            return OrchestratorDecision(
                route="continue_previous",
                intent=intent,
                state=state,
                should_call_gateway=True,
                prompt=prompt,
                knowledge_mode="full_kb",
                analysis_context_mode="selected_detail",
            )
        if state in {"feedback_given", "follow_up"} and input.current_video_job_id:
            prompt = build_branch_prompt(
                content,
                state=state,
                intent=intent,
                analysis_context=self._analysis_text(input.current_video_result),
                knowledge_context=load_full_knowledge_context(),
            )
            return OrchestratorDecision(
                route=SkillOrchestrator._gateway_route(intent, state, False),
                intent=intent,
                state=state,
                should_call_gateway=True,
                prompt=prompt,
                knowledge_mode="full_kb",
                analysis_context_mode="selected_detail",
            )
        prompt = build_agent_message(content, is_first_turn=not has_user_history, state=state)
        return OrchestratorDecision(
            route="general_chat",
            intent=intent,
            state=state,
            should_call_gateway=True,
            prompt=prompt,
        )

    def decide_initial_video_question(self, input: OrchestratorInput) -> OrchestratorDecision:
        content = input.user_content.strip()
        intent = detect_intent(content)
        prompt = build_branch_prompt(
            content,
            state="follow_up",
            intent=intent,
            analysis_context=self._analysis_text(input.current_video_result),
            knowledge_context=load_full_knowledge_context(),
        )
        return OrchestratorDecision(
            route="answer_initial_video_question",
            intent=intent,
            state="follow_up",
            should_call_gateway=True,
            prompt=prompt,
            knowledge_mode="full_kb",
            analysis_context_mode="selected_detail",
        )

    @staticmethod
    def _analysis_text(result: dict[str, Any] | None) -> str:
        if not isinstance(result, dict):
            return ""
        return str(result.get("analysis_detail") or result.get("summary") or "").strip()
