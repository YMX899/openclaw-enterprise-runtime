"""Unit tests for the Bridge-side agent persona, intent detection, and guardrails."""
import unittest
from openclaw_video.agent_persona import (
    GREETING,
    SYSTEM_PERSONA,
    build_agent_message,
    detect_intent,
    guardrail_for_message,
    has_douyin_link,
)


class IntentDetectionTests(unittest.TestCase):
    def test_analyze_my_video(self):
        self.assertEqual(detect_intent("帮我分析这条视频"), "analyze_my_video")
        self.assertEqual(detect_intent("这条视频哪里有问题"), "analyze_my_video")

    def test_analyze_benchmark_video(self):
        self.assertEqual(detect_intent("帮我拆一下这个爆款"), "analyze_benchmark_video")
        self.assertEqual(detect_intent("这个视频为什么火"), "analyze_benchmark_video")

    def test_why_not_viral(self):
        self.assertEqual(detect_intent("为什么不爆"), "ask_why_not_viral")

    def test_rewrite_opening(self):
        self.assertEqual(detect_intent("开头怎么改"), "ask_rewrite_opening")

    def test_rewrite_script(self):
        self.assertEqual(detect_intent("帮我写一版脚本"), "ask_rewrite_script")

    def test_reshoot(self):
        self.assertEqual(detect_intent("复拍方案怎么写"), "ask_reshoot_plan")

    def test_casual_chat(self):
        self.assertEqual(detect_intent("你好"), "casual_chat")
        self.assertEqual(detect_intent(""), "casual_chat")


class GuardrailTests(unittest.TestCase):
    def test_no_guardrail_for_plain_text(self):
        self.assertIsNone(guardrail_for_message("你好，你能帮我什么？"))

    def test_no_guardrail_for_douyin_link(self):
        self.assertIsNone(guardrail_for_message("帮我分析 https://www.douyin.com/video/123"))

    def test_no_guardrail_for_short_douyin_link(self):
        self.assertIsNone(guardrail_for_message("https://v.douyin.com/abc123/"))

    def test_guardrail_youtube(self):
        g = guardrail_for_message("帮我分析 https://www.youtube.com/watch?v=abc")
        self.assertIsNotNone(g)
        self.assertEqual(g.reason, "unsupported_platform")
        self.assertIn("YouTube", g.content)
        self.assertIn("抖音", g.content)

    def test_guardrail_bilibili(self):
        g = guardrail_for_message("https://www.bilibili.com/video/BV1xx")
        self.assertIsNotNone(g)
        self.assertEqual(g.reason, "unsupported_platform")
        self.assertIn("B 站", g.content)

    def test_guardrail_xiaohongshu(self):
        g = guardrail_for_message("https://www.xiaohongshu.com/explore/abc")
        self.assertIsNotNone(g)
        self.assertIn("小红书", g.content)

    def test_guardrail_profile_link(self):
        g = guardrail_for_message("https://www.douyin.com/user/MS4wLjA")
        self.assertIsNotNone(g)
        self.assertEqual(g.reason, "profile_link")
        self.assertIn("主页链接", g.content)

    def test_guardrail_blocks_fake_capabilities(self):
        g = guardrail_for_message("帮我分析 https://www.youtube.com/watch?v=test")
        # Must not say it can transcribe captions or access YouTube
        self.assertNotIn("转录字幕", g.content)
        self.assertNotIn("提取视频标题", g.content)


class PersonaInjectionTests(unittest.TestCase):
    def test_first_turn_gets_persona(self):
        msg = build_agent_message("帮我分析视频", is_first_turn=True)
        self.assertIn(SYSTEM_PERSONA[:30], msg)
        self.assertIn("帮我分析视频", msg)

    def test_subsequent_turns_skip_persona(self):
        msg = build_agent_message("开头怎么改", is_first_turn=False)
        self.assertEqual(msg, "开头怎么改")
        self.assertNotIn(SYSTEM_PERSONA[:30], msg)

    def test_persona_is_chinese(self):
        self.assertIn("短视频", SYSTEM_PERSONA)
        self.assertIn("中文", SYSTEM_PERSONA)

    def test_greeting_is_chinese(self):
        self.assertIn("抖音", GREETING)
        self.assertIn("分析", GREETING)


if __name__ == "__main__":
    unittest.main()
