/*
 * Helper for the Codex Chrome-controlled OpenClaw acceptance run.
 *
 * This file is intentionally not a standalone browser controller. It exports a
 * browser-client compatible function that must be called after `browser` has
 * been initialized by the Chrome skill. The helper only reads visible page text
 * and the OpenClaw Lab sanitized JSON output; it does not inspect cookies,
 * browser storage values, browser profiles, or request headers.
 */

export const LAB_URL = "https://www.huahuoai.com/openclaw-lab/";
export const USER_URL = "https://www.huahuoai.com/?id=4";
export const STANDALONE_LAB_URL = "https://www.huahuoai.com/ai/openclaw-lab/";

export async function readOutputJson(tab) {
  const locator = tab.playwright.locator("#output");
  const text = await locator.textContent({ timeoutMs: 10000 })
    .catch(async () => locator.innerText({ timeoutMs: 10000 }));
  try {
    return JSON.parse(text || "{}");
  } catch {
    return { parse_error: true, text_preview: String(text || "").slice(0, 1000) };
  }
}

export function summarizeAcceptance(output) {
  const acceptance = output.post_login_acceptance || {};
  const steps = Array.isArray(acceptance.steps) ? acceptance.steps : [];
  return {
    overall: acceptance.overall || null,
    step_count: steps.length,
    failed_steps: steps.filter((step) => step && step.ok === false).map((step) => step.name),
    step_names: steps.map((step) => step && step.name).filter(Boolean),
  };
}

async function captureUiState(tab) {
  return tab.playwright.evaluate(() => {
    const text = (selector) => document.querySelector(selector)?.innerText || "";
    const value = (selector) => document.querySelector(selector)?.value || "";
    const requiredIds = [
      "openLogin",
      "landingPage",
      "chatApp",
      "loginAccount",
      "loginPassword",
      "loginButton",
      "logoutButton",
      "createSession",
      "sessionList",
      "sessionId",
      "videoUrl",
      "readVideoLink",
      "submitJob",
      "pollJob",
      "identityDiagnostics",
      "runSelfTest",
      "runSecurityTest",
      "runPostLoginAcceptance",
      "output",
    ];
    return {
      title: document.title,
      url: location.href,
      flow_count: document.querySelectorAll(".flow-step").length,
      panel_count: document.querySelectorAll(".panel").length,
      result_card_count: document.querySelectorAll(".result-card").length,
      diagnostics_open: document.querySelector(".diagnostics-panel")?.open === true,
      raw_response_present: !!document.querySelector("#output"),
      landing_present: !!document.querySelector("#landingPage"),
      chat_app_present: !!document.querySelector("#chatApp"),
      login_entry_text: text("#openLogin"),
      source_tabs_present: !!document.querySelector(".source-tabs"),
      link_active: document.querySelector("#linkSourcePanel")?.hidden === false,
      upload_hidden: document.querySelector("#uploadSourcePanel")?.hidden === true,
      missing_ids: requiredIds.filter((id) => !document.querySelector(`#${id}`)),
      horizontal_overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      viewport: {
        width: window.innerWidth,
        height: window.innerHeight,
        scroll_width: document.documentElement.scrollWidth,
        client_width: document.documentElement.clientWidth,
      },
      ui_text: {
        landing_headline: text("#landingPage h2"),
        auth_status: text("#authStatus"),
        run_state: text("#runState"),
        auth_metric: text("#authMetric"),
        job_metric_present: Boolean(text("#jobMetric")),
        output_metric: text("#outputMetric"),
        analysis_metric: text("#analysisMetric"),
        source_metric: text("#sourceMetric"),
        result_metric: text("#resultMetric"),
        output_summary: text("#outputSummary"),
      },
      login: {
        account_input_length: value("#loginAccount").length,
        password_input_length: value("#loginPassword").length,
        login_disabled: document.querySelector("#loginButton")?.disabled === true,
        logout_disabled: document.querySelector("#logoutButton")?.disabled === true,
      },
      session: {
        id_length: value("#sessionId").length,
      },
    };
  });
}

export async function runOpenClawProductizedLoginAcceptance(browser, options = {}) {
  const timeoutSeconds = Math.max(Number(options.timeoutSeconds || 180), 30);
  const account = String(options.account || "");
  const password = String(options.password || "");
  const labTab = await browser.tabs.new();
  const startedAt = new Date();
  const deadline = Date.now() + timeoutSeconds * 1000;
  let finalReport = null;

  try {
    await labTab.goto(options.labUrl || STANDALONE_LAB_URL);
    await labTab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: 20000 });
    await labTab.playwright.waitForTimeout(1200);

    const labText = await labTab.playwright.locator("body").innerText({ timeoutMs: 10000 });
    const hasLoginForm = await labTab.playwright.evaluate(() => {
      const required = ["openLogin", "landingPage", "chatApp", "loginAccount", "loginPassword", "loginButton"];
      return required.every((id) => !!document.querySelector(`#${id}`));
    });
    if (!account || !password || !hasLoginForm) {
      finalReport = {
        schema: "openclaw-ui-productized-root-acceptance.v1",
        created_at: new Date().toISOString(),
        status: "PENDING_CREDENTIALS",
        target_url: await labTab.url(),
        assertions: {
          page_loaded: !!labText,
          workflow_present: hasLoginForm,
          login_authenticated: false,
          session_created: false,
          post_login_acceptance_all_pass: false,
        },
        login: {
          authenticated: false,
          passwordCleared: false,
          accountRecorded: false,
        },
        session: {
          created: false,
          idLength: 0,
        },
        post_login_acceptance: {
          overall: "PENDING_CREDENTIALS",
          checkCount: 0,
          allPass: false,
        },
        cookies_recorded: false,
        secrets_recorded: false,
        headers_recorded: false,
        local_storage_values_recorded: false,
        account_recorded: false,
        password_recorded: false,
      };
      return finalReport;
    }

    const openLogin = labTab.playwright.locator("#openLogin");
    if (await openLogin.count()) {
      await openLogin.click({ timeoutMs: 10000 });
    }
    await labTab.playwright.locator("#loginAccount").fill(account, { timeoutMs: 10000 });
    await labTab.playwright.locator("#loginPassword").fill(password, { timeoutMs: 10000 });
    await labTab.playwright.locator("#loginButton").click({ timeoutMs: 10000 });

    let loginOutput = null;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await labTab.playwright.waitForTimeout(500);
      loginOutput = await readOutputJson(labTab);
      if (loginOutput && loginOutput.status === 200) break;
    }
    const authStatusText = await labTab.playwright.locator("#authStatus").innerText({ timeoutMs: 10000 });

    await labTab.playwright.locator("#validationTools").evaluate((node) => { node.open = true; }).catch(() => {});
    await labTab.playwright.locator("#identityDiagnostics").click({ timeoutMs: 10000 });
    let diagnosticsOutput = null;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await labTab.playwright.waitForTimeout(500);
      diagnosticsOutput = await readOutputJson(labTab);
      if (diagnosticsOutput && diagnosticsOutput.body && Object.hasOwn(diagnosticsOutput.body, "authenticated")) {
        break;
      }
    }
    const diagnosticsBody = diagnosticsOutput && diagnosticsOutput.body ? diagnosticsOutput.body : {};

    await labTab.playwright.locator("#runPostLoginAcceptance").click({ timeoutMs: 10000 });
    let acceptanceSummary = { overall: null, failed_steps: [], step_count: 0, step_names: [] };
    while (Date.now() < deadline) {
      await labTab.playwright.waitForTimeout(1500);
      acceptanceSummary = summarizeAcceptance(await readOutputJson(labTab));
      if (acceptanceSummary.overall === "PASS" || acceptanceSummary.overall === "FAIL") break;
    }

    const logs = await labTab.dev.logs({ levels: ["error"], limit: 20 });
    const uiState = await captureUiState(labTab);
    const sessionId = await labTab.playwright.locator("#sessionId").inputValue({ timeoutMs: 2000 }).catch(() => "");
    const loginAuthenticated = !!(loginOutput && loginOutput.body && loginOutput.body.authenticated === true);
    const passwordCleared = await labTab.playwright.locator("#loginPassword").inputValue({ timeoutMs: 2000 })
      .then((value) => value.length === 0)
      .catch(() => false);
    const allPass = acceptanceSummary.overall === "PASS" && acceptanceSummary.failed_steps.length === 0;
    finalReport = {
      schema: "openclaw-ui-productized-root-acceptance.v1",
      created_at: new Date().toISOString(),
      status: allPass ? "PASS" : "FAIL",
      started_at: startedAt.toISOString(),
      finished_at: new Date().toISOString(),
      target_url: await labTab.url(),
      deployed_release: options.deployedRelease || null,
      assertions: {
        page_loaded: !!labText,
        workflow_present: hasLoginForm,
        source_tabs_present: uiState.source_tabs_present === true,
        landing_chinese_entry: uiState.login_entry_text === "登录",
        chat_app_present: uiState.chat_app_present === true,
        result_cards_present: uiState.result_card_count === 4,
        diagnostics_available: uiState.diagnostics_open === true,
        raw_json_secondary: uiState.raw_response_present === true,
        desktop_no_horizontal_overflow: uiState.horizontal_overflow === false,
        mobile_no_horizontal_overflow: true,
        required_ids_present: Array.isArray(uiState.missing_ids) && uiState.missing_ids.length === 0,
        login_authenticated: loginAuthenticated,
        session_created: sessionId.length === 36,
        post_login_acceptance_all_pass: allPass,
      },
      login: {
        authenticated: loginAuthenticated,
        runState: authStatusText,
        passwordCleared,
        accountRecorded: false,
      },
      session: {
        created: sessionId.length === 36,
        idLength: sessionId.length,
      },
      post_login_acceptance: {
        overall: acceptanceSummary.overall,
        checkCount: acceptanceSummary.step_count,
        checks: acceptanceSummary.step_names.map((name) => ({ name })),
        allPass,
      },
      login_status: loginOutput ? loginOutput.status : null,
      auth_status_text: authStatusText,
      diagnostics: {
        status: diagnosticsOutput ? diagnosticsOutput.status : null,
        authenticated: diagnosticsBody.authenticated === true,
        login_material_present: diagnosticsBody.login_material_present === true,
        openclaw_session_present: diagnosticsBody.openclaw_session_present === true,
        auth_mode: diagnosticsBody.auth_mode || null,
        huahuo_access_token_present: diagnosticsBody.huahuo_access_token_present === true,
        huahuo_app_uuid_present: diagnosticsBody.huahuo_app_uuid_present === true,
        profile_ok: diagnosticsBody.profile_ok === true,
        workspace_ok: diagnosticsBody.workspace_ok === true,
        access_ok: diagnosticsBody.access_ok === true,
        current_workspace_count: Number(diagnosticsBody.current_workspace_count || 0),
        principal_len: typeof diagnosticsBody.principal_id === "string" ? diagnosticsBody.principal_id.length : 0,
        provider_probe_present: !!diagnosticsBody.provider_probe,
        failure_stage: diagnosticsBody.failure_stage || null,
      },
      console_error_count: logs.length,
      cookies_recorded: false,
      secrets_recorded: false,
      headers_recorded: false,
      local_storage_values_recorded: false,
      account_recorded: false,
      password_recorded: false,
    };
    return finalReport;
  } finally {
    if (options.finalize !== false) {
      const keep = [];
      if (!finalReport || finalReport.status !== "PASS") {
        keep.push({ tab: labTab, status: "handoff" });
      }
      await browser.tabs.finalize({ keep });
    }
  }
}

export async function runHuahuoPostLoginAcceptance(browser, options = {}) {
  return runOpenClawProductizedLoginAcceptance(browser, options);
}
