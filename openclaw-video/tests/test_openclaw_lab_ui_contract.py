import ast
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_APP = REPO_ROOT / "openclaw-video" / "src" / "openclaw_video" / "bridge_app.py"


def load_lab_page_html() -> str:
    tree = ast.parse(BRIDGE_APP.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "LAB_PAGE_HTML":
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str):
                        return value
    raise AssertionError("LAB_PAGE_HTML was not found")


class OpenClawLabUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = load_lab_page_html()

    def test_productized_ui_preserves_required_automation_selectors(self):
        required_ids = [
            "openLogin",
            "landingPage",
            "chatApp",
            "loginAccount",
            "loginPassword",
            "loginButton",
            "authStatus",
            "identityDiagnostics",
            "runPostLoginAcceptance",
            "runSelfTest",
            "runSecurityTest",
            "createSession",
            "sessionList",
            "sessionId",
            "videoUrl",
            "prompt",
            "readVideoLink",
            "submitJob",
            "pollJob",
            "videoFile",
            "uploadJob",
            "uploadSmoke",
            "output",
        ]
        for element_id in required_ids:
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.html)

    def test_ui_has_chinese_landing_chat_history_and_validation_layers(self):
        for required in [
            "OpenClaw 产品介绍",
            "OpenClaw 短视频智能分析",
            "让短视频链接直接进入可追踪的分析对话",
            "登录后进入分析对话",
            "无需再登录 Dify 网页",
            "OpenClaw 中文聊天分析界面",
            "历史对话",
            "新建对话",
            "分析对话",
            "视频分析",
            "nextAction",
            "下一步",
            "primary-active",
            "setPrimaryAction",
            "setPanelState",
            "showLanding",
            "showChatApp",
            "loadSessions",
            "renderSessions",
            "selectSession",
            "sessionPanel",
            "videoPanel",
            "conversationPanel",
            "发送",
            "刷新历史",
            "sendChat",
            "refreshMessages",
            "apiPrefix + '/chat'",
            "apiPrefix + '/sessions'",
            "apiPrefix + '/sessions/' + encodeURIComponent(sessionId) + '/messages'",
            "开发详情：脱敏响应",
            "验证工具",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, self.html)

    def test_ui_does_not_expose_gateway_or_browser_secret_surfaces(self):
        for forbidden in [
            "localStorage",
            "OPENCLAW_GATEWAY_TOKEN",
            "openclaw-gateway:18789",
            "Authorization",
            "Cookie",
            "HUAHUO-access",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.html)


if __name__ == "__main__":
    unittest.main()
