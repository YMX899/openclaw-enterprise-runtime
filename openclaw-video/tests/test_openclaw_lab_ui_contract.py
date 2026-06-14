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
            "openLogin", "landingPage", "chatApp", "loginForm", "loginAccount", "loginPassword",
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
            'name="username"', 'autocomplete="username"', 'name="password"',
            'autocomplete="current-password"', "访问花火AI首页", "https://www.huahuoai.com/home/",
        ]
        for required in in_shell:
            with self.subTest(shell=required):
                self.assertIn(required, self.index_html)
        self.assertIn('id="devDrawer" class="cg-dev-hidden" hidden', self.index_html)
        self.assertNotIn("开发详情：脱敏响应", self.index_html)
        self.assertNotIn("验证工具", self.index_html)
        self.assertNotIn("前 3 秒钩子", self.index_html)
        in_source = [
            "setPrimaryAction", "setPanelState", "showLanding", "showChatApp",
            "loadSessions", "renderSessions", "selectSession", "sendChat", "refreshMessages",
            "apiPrefix + '/chat'", "apiPrefix + '/sessions'",
            "apiPrefix + '/sessions/' + encodeURIComponent(sessionId) + '/messages'",
            "JOB_AUTO_POLL_ATTEMPTS", "hydrateCompletedJobMessages", "仍在分析中，可稍后刷新查看结果。",
            "video_too_large", "500MB", "上传至视频分析模型",
            "xiaohongshu", "xhslink", "小红书",
        ]
        for required in in_source:
            with self.subTest(source=required):
                self.assertIn(required, self.source)
        self.assertNotIn("分析超时，请稍后重试", self.built_js)
        self.assertNotIn("视频理解 fps", self.source)

    def test_video_submission_status_copy_matches_files_api_flow(self):
        expected_status_copy = [
            "已收到视频文件，正在上传…",
            "1/4 准备上传视频文件…",
            "1/4 上传视频文件…",
            "2/4 上传完成，正在提交分析任务…",
            "3/4 模型正在分析视频，请继续等待…",
            "4/4 分析完成",
            "正在读取视频链接…",
            "1/4 正在读取视频链接…",
            "2/4 链接读取完成，正在提交分析任务…",
            "模型正在分析视频，请继续等待…",
            "正在下载/读取并上传至视频分析模型",
            "分析上限：500MB",
            "这个视频文件超过 500MB",
            "500MB 以内的 mp4/avi/mov",
            'accept=".mp4,.avi,.mov,video/mp4,video/avi,video/mov,video/quicktime,video/x-msvideo"',
        ]
        for required in expected_status_copy:
            with self.subTest(status_copy=required):
                self.assertIn(required, self.source)
                self.assertIn(required, self.built_js + self.index_html)
        for forbidden in ["压缩后再上传", "视频理解 fps", "512MB", "video/webm"]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.source)
                self.assertNotIn(forbidden, self.built_js + self.index_html)

    def test_sidebar_keeps_user_menu_visible_while_history_scrolls(self):
        required_css = [
            ".chat-app {\n  display: grid;\n  grid-template-columns: 268px minmax(0, 1fr);\n  height: 100vh;",
            ".chat-app {\n  display: grid;\n  grid-template-columns: 268px minmax(0, 1fr);\n  height: 100vh;\n  min-height: 100vh;\n  overflow: hidden;",
            ".cg-sidebar {\n  min-width: 0;\n  height: 100vh;",
            "max-height: 100vh;\n  overflow: hidden;\n  display: flex;",
            ".cg-session-list {\n  flex: 1 1 0;\n  min-height: 0;\n  overflow-y: auto;",
            "overscroll-behavior: contain;",
            ".cg-sidebar-footer {\n  position: sticky;\n  bottom: 0;\n  z-index: 2;\n  flex: 0 0 auto;",
            "margin-top: auto;\n  padding-top: var(--space-3);",
        ]
        for required in required_css:
            with self.subTest(css=required):
                self.assertIn(required, self.source)

    def test_ui_does_not_expose_gateway_or_browser_secret_surfaces(self):
        for forbidden in ["localStorage", "OPENCLAW_GATEWAY_TOKEN", "openclaw-gateway:18789", "Authorization", "Cookie", "HUAHUO-access"]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.built_js)
                self.assertNotIn(forbidden, self.index_html)


if __name__ == "__main__":
    unittest.main()
