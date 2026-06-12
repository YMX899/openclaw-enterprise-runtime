"""UI contract test for the OpenClaw lab page after the Vite build migration.

The page is no longer an embedded Python string; it is built from openclaw-video/web
into src/openclaw_video/webdist. We assert:
  - automation selector IDs are present in the built shell (index.html);
  - required Chinese product / handler strings exist in the web source;
  - no browser-storage or gateway-secret surfaces leak into the built JS or shell.
"""
import glob
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
WEB = REPO_ROOT / "openclaw-video" / "web"
WEBDIST = REPO_ROOT / "openclaw-video" / "src" / "openclaw_video" / "webdist"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


class OpenClawLabUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index_html = _read(WEBDIST / "index.html")
        cls.built_js = "".join(_read(Path(p)) for p in glob.glob(str(WEBDIST / "assets" / "*.js")))
        # web source (shell + ts + css) — where handler names / API paths live unminified
        cls.source = (
            _read(WEB / "index.html")
            + _read(WEB / "src" / "main.ts")
            + _read(WEB / "src" / "styles.css")
        )
        assert cls.index_html, "webdist/index.html missing — run `npm run build` in openclaw-video/web"
        assert cls.built_js, "built JS missing — run `npm run build`"

    def test_productized_ui_preserves_required_automation_selectors(self):
        required_ids = [
            "openLogin", "landingPage", "chatApp", "loginAccount", "loginPassword",
            "loginButton", "authStatus", "identityDiagnostics", "runPostLoginAcceptance",
            "runSelfTest", "runSecurityTest", "createSession", "sessionList", "sessionId",
            "videoUrl", "prompt", "readVideoLink", "submitJob", "pollJob", "videoFile",
            "uploadJob", "uploadSmoke", "output",
        ]
        for element_id in required_ids:
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.index_html)

    def test_ui_has_chinese_landing_chat_history_and_hidden_diagnostics(self):
        # markup-level strings live in the built shell; handler/API strings live in source.
        in_shell = [
            "花火AI视频分析", "登录",
            "历史对话", "新建对话", "视频分析", "发送消息或粘贴视频链接", "nextAction",
        ]
        for required in in_shell:
            with self.subTest(shell=required):
                self.assertIn(required, self.index_html)
        self.assertIn('id="devDrawer" class="cg-dev-hidden" hidden', self.index_html)
        self.assertNotIn("开发详情：脱敏响应", self.index_html)
        self.assertNotIn("验证工具", self.index_html)
        in_source = [
            "setPrimaryAction", "setPanelState", "showLanding", "showChatApp",
            "loadSessions", "renderSessions", "selectSession", "sendChat", "refreshMessages",
            "apiPrefix + '/chat'", "apiPrefix + '/sessions'",
            "apiPrefix + '/sessions/' + encodeURIComponent(sessionId) + '/messages'",
            "JOB_AUTO_POLL_ATTEMPTS", "hydrateCompletedJobMessages", "仍在分析中，可稍后刷新查看结果。",
            "video_too_large", "视频理解 fps",
        ]
        for required in in_source:
            with self.subTest(source=required):
                self.assertIn(required, self.source)
        self.assertNotIn("分析超时，请稍后重试", self.built_js)

    def test_ui_does_not_expose_gateway_or_browser_secret_surfaces(self):
        for forbidden in ["localStorage", "OPENCLAW_GATEWAY_TOKEN", "openclaw-gateway:18789", "Authorization", "Cookie", "HUAHUO-access"]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.built_js)
                self.assertNotIn(forbidden, self.index_html)


if __name__ == "__main__":
    unittest.main()
