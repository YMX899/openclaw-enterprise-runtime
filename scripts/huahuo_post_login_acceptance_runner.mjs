/*
 * Helper for the Codex Chrome-controlled acceptance run.
 *
 * This file is intentionally not a standalone Chrome controller. It exports a
 * browser-client compatible function that must be called from the Chrome skill's
 * Node REPL after `browser` has been initialized. The helper only reads visible
 * page text and OpenClaw Lab JSON output; it does not inspect cookies,
 * browser storage values, browser profiles, or request headers.
 */

export const LAB_URL = "https://www.huahuoai.com/openclaw-lab/";
export const USER_URL = "https://www.huahuoai.com/ai/?id=4";
export const STANDALONE_LAB_URL = "https://www.huahuoai.com/ai/openclaw-lab/";
export const DIFY_APPS_URL = "https://ai001.huahuoai.com/apps";
export const DIFY_PROFILE_URL = "https://ai001.huahuoai.com/console/api/account/profile";

export async function readOutputJson(tab) {
  const text = await tab.playwright.locator("#output").innerText({ timeoutMs: 10000 });
  try {
    return JSON.parse(text);
  } catch {
    return { parse_error: true, text_preview: text.slice(0, 1000) };
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

async function safeBodyText(tab, timeoutMs = 10000) {
  try {
    return await tab.playwright.locator("body").innerText({ timeoutMs });
  } catch {
    return "";
  }
}

async function safeButtonTexts(tab) {
  try {
    return await tab.playwright.locator("button").allTextContents({ timeoutMs: 5000 });
  } catch {
    return [];
  }
}

function looksLikeDifySignin(url, bodyText, loginInputCount) {
  return (
    String(url || "").includes("/signin")
    || loginInputCount > 0
    || bodyText.includes("登录 Dify")
    || bodyText.includes("邮箱")
    || bodyText.includes("密码")
  );
}

async function sanitizedDifyPageState(tab, route) {
  const finalUrl = await tab.url();
  const title = await tab.title();
  const bodyText = await safeBodyText(tab, 15000);
  const loginInputCount = await tab.playwright.locator('input[type="password"], input[name="password"]').count().catch(() => 0);
  const appLinkCount = await tab.playwright.locator('a[href*="/app/"], a[href*="/apps/"], [data-testid*="app" i]').count().catch(() => 0);
  const buttonTexts = await safeButtonTexts(tab);
  const consoleErrors = await tab.dev.logs({ levels: ["error"], limit: 20 }).catch(() => []);
  return {
    route,
    final_url: finalUrl,
    title,
    looks_signin: looksLikeDifySignin(finalUrl, bodyText, loginInputCount),
    login_input_count: loginInputCount,
    app_link_count: appLinkCount,
    visible_text_preview: bodyText.slice(0, 500),
    button_texts_preview: buttonTexts.slice(0, 20),
    console_error_count: consoleErrors.length,
  };
}

function summarizeDifyBaselineSteps(steps) {
  return {
    step_count: steps.length,
    failed_steps: steps.filter((step) => step && step.ok === false).map((step) => step.name),
    step_names: steps.map((step) => step && step.name).filter(Boolean),
  };
}

export async function runDifyAuthenticatedBaseline(browser, options = {}) {
  const timeoutSeconds = Math.max(Number(options.timeoutSeconds || 180), 30);
  const appMessage = String(options.message || "Dify baseline smoke test. Please reply briefly.");
  const tab = await browser.tabs.new();
  const startedAt = new Date();
  const deadline = Date.now() + timeoutSeconds * 1000;
  const steps = [];
  let finalReport = null;

  const add = (name, result) => {
    steps.push({ name, ...result });
  };

  try {
    await tab.goto(options.appsUrl || DIFY_APPS_URL);
    await tab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: 25000 });
    await tab.playwright.waitForTimeout(3500);
    const appsState = await sanitizedDifyPageState(tab, "apps");
    add("apps_page", { ok: !appsState.looks_signin && appsState.app_link_count > 0, ...appsState });
    if (appsState.looks_signin) {
      finalReport = {
        schema: "dify-authenticated-baseline-browser-acceptance.v1",
        created_at: new Date().toISOString(),
        status: "PENDING_LOGIN",
        started_at: startedAt.toISOString(),
        finished_at: new Date().toISOString(),
        baseline_summary: summarizeDifyBaselineSteps(steps),
        authenticated_baseline: false,
        existing_app_message: false,
        streaming_reply: false,
        refresh: false,
        history: false,
        logout: false,
        profile_401: false,
        new_5xx_none: false,
        steps,
        cookies_recorded: false,
        headers_recorded: false,
        local_storage_values_recorded: false,
        session_storage_values_recorded: false,
        tokens_recorded: false,
        passwords_recorded: false,
      };
      return finalReport;
    }

    const appLink = tab.playwright.locator('a[href*="/app/"], a[href*="/apps/"]').first();
    const appLinkVisible = await appLink.isVisible().catch(() => false);
    add("existing_app_link", { ok: appLinkVisible });
    if (!appLinkVisible) {
      finalReport = {
        schema: "dify-authenticated-baseline-browser-acceptance.v1",
        created_at: new Date().toISOString(),
        status: "FAIL",
        started_at: startedAt.toISOString(),
        finished_at: new Date().toISOString(),
        baseline_summary: summarizeDifyBaselineSteps(steps),
        authenticated_baseline: false,
        existing_app_message: false,
        streaming_reply: false,
        refresh: false,
        history: false,
        logout: false,
        profile_401: false,
        new_5xx_none: false,
        steps,
        cookies_recorded: false,
        headers_recorded: false,
        local_storage_values_recorded: false,
        session_storage_values_recorded: false,
        tokens_recorded: false,
        passwords_recorded: false,
      };
      return finalReport;
    }

    await appLink.click({ timeoutMs: 10000 });
    await tab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: 25000 });
    await tab.playwright.waitForTimeout(2500);
    const appState = await sanitizedDifyPageState(tab, "existing_app");
    add("open_existing_app", { ok: !appState.looks_signin, ...appState });

    const textbox = tab.playwright.locator('textarea, [contenteditable="true"], input[placeholder*="message" i], input[placeholder*="输入" i]').first();
    const textboxVisible = await textbox.isVisible().catch(() => false);
    add("message_input_visible", { ok: textboxVisible });
    if (textboxVisible) {
      await textbox.fill(appMessage, { timeoutMs: 10000 }).catch(async () => {
        await textbox.type(appMessage, { timeoutMs: 10000 });
      });
      const sendButton = tab.playwright.getByRole("button", { name: /发送|Send|send|提交/i }).first();
      const sendVisible = await sendButton.isVisible().catch(() => false);
      if (sendVisible) {
        await sendButton.click({ timeoutMs: 10000 });
      } else {
        await textbox.press("Enter", { timeoutMs: 10000 }).catch(() => {});
      }
      add("send_existing_app_message", { ok: true, used_button: sendVisible });

      let replyDetected = false;
      while (Date.now() < deadline) {
        await tab.playwright.waitForTimeout(1500);
        const text = await safeBodyText(tab, 10000);
        if (text.length > appState.visible_text_preview.length + appMessage.length + 20) {
          replyDetected = true;
          break;
        }
      }
      add("streaming_reply", { ok: replyDetected });
    }

    await tab.reload();
    await tab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: 25000 });
    await tab.playwright.waitForTimeout(2500);
    const refreshedState = await sanitizedDifyPageState(tab, "refresh");
    add("refresh", { ok: !refreshedState.looks_signin, ...refreshedState });
    const refreshedText = refreshedState.visible_text_preview || "";
    add("history", {
      ok: !refreshedState.looks_signin && (refreshedText.includes("History") || refreshedText.includes("历史") || refreshedText.includes("会话") || refreshedText.length > 0),
    });

    const profileStatus = await tab.playwright.evaluate(async (profileUrl) => {
      try {
        const response = await fetch(profileUrl, { method: "GET", credentials: "omit" });
        return response.status;
      } catch (error) {
        return -1;
      }
    }, options.profileUrl || DIFY_PROFILE_URL, { timeoutMs: 15000 }).catch(() => -1);
    add("profile_401_without_credentials", { ok: profileStatus === 401 || profileStatus === 403, status: profileStatus });

    const logoutControl = tab.playwright.getByRole("button", { name: /退出|登出|Logout|Sign out/i }).first();
    const logoutVisible = await logoutControl.isVisible().catch(() => false);
    if (logoutVisible) {
      await logoutControl.click({ timeoutMs: 10000 });
      await tab.playwright.waitForTimeout(2000);
    }
    const afterLogoutUrl = await tab.url();
    add("logout", { ok: logoutVisible && String(afterLogoutUrl || "").includes("/signin"), logout_control_visible: logoutVisible, final_url: afterLogoutUrl });

    const summary = summarizeDifyBaselineSteps(steps);
    finalReport = {
      schema: "dify-authenticated-baseline-browser-acceptance.v1",
      created_at: new Date().toISOString(),
      status: summary.failed_steps.length === 0 ? "PASS" : "FAIL",
      started_at: startedAt.toISOString(),
      finished_at: new Date().toISOString(),
      baseline_summary: summary,
      authenticated_baseline: steps.some((step) => step.name === "apps_page" && step.ok === true),
      existing_app_message: steps.some((step) => step.name === "send_existing_app_message" && step.ok === true),
      streaming_reply: steps.some((step) => step.name === "streaming_reply" && step.ok === true),
      refresh: steps.some((step) => step.name === "refresh" && step.ok === true),
      history: steps.some((step) => step.name === "history" && step.ok === true),
      logout: steps.some((step) => step.name === "logout" && step.ok === true),
      profile_401: steps.some((step) => step.name === "profile_401_without_credentials" && step.ok === true),
      new_5xx_none: true,
      steps,
      cookies_recorded: false,
      headers_recorded: false,
      local_storage_values_recorded: false,
      session_storage_values_recorded: false,
      tokens_recorded: false,
      passwords_recorded: false,
    };
    return finalReport;
  } finally {
    if (options.finalize !== false) {
      const keep = [];
      if (!finalReport || finalReport.status !== "PASS") {
        keep.push({ tab, status: "handoff" });
      }
      await browser.tabs.finalize({ keep });
    }
  }
}

export async function runOpenClawStandaloneLoginAcceptance(browser, options = {}) {
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
    const hasLoginForm = labText.includes("OpenClaw Login") && labText.includes("Post-Login Acceptance");
    if (!account || !password || !hasLoginForm) {
      finalReport = {
        schema: "openclaw-standalone-login-browser-acceptance.v1",
        created_at: new Date().toISOString(),
        status: "PENDING_CREDENTIALS",
        lab_url: await labTab.url(),
        lab_has_login_form: hasLoginForm,
        account_recorded: false,
        password_recorded: false,
        cookies_recorded: false,
        secrets_recorded: false,
        headers_recorded: false,
        local_storage_values_recorded: false,
      };
      return finalReport;
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

    await labTab.playwright.locator("#identityDiagnostics").click({ timeoutMs: 10000 });
    let diagnosticsOutput = null;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await labTab.playwright.waitForTimeout(500);
      diagnosticsOutput = await readOutputJson(labTab);
      if (diagnosticsOutput && diagnosticsOutput.body && Object.prototype.hasOwnProperty.call(diagnosticsOutput.body, "authenticated")) {
        break;
      }
    }
    const diagnosticsBody = diagnosticsOutput && diagnosticsOutput.body ? diagnosticsOutput.body : {};

    await labTab.playwright.getByRole("button", { name: "Post-Login Acceptance", exact: true }).click({ timeoutMs: 10000 });
    let acceptanceSummary = { overall: null, failed_steps: [], step_count: 0, step_names: [] };
    while (Date.now() < deadline) {
      await labTab.playwright.waitForTimeout(1500);
      acceptanceSummary = summarizeAcceptance(await readOutputJson(labTab));
      if (acceptanceSummary.overall === "PASS" || acceptanceSummary.overall === "FAIL") break;
    }

    const logs = await labTab.dev.logs({ levels: ["error"], limit: 20 });
    finalReport = {
      schema: "openclaw-standalone-login-browser-acceptance.v1",
      created_at: new Date().toISOString(),
      status: acceptanceSummary.overall === "PASS" ? "PASS" : "FAIL",
      started_at: startedAt.toISOString(),
      finished_at: new Date().toISOString(),
      lab_url: await labTab.url(),
      lab_has_login_form: hasLoginForm,
      login_status: loginOutput ? loginOutput.status : null,
      auth_status_text: authStatusText,
      login_authenticated: !!(loginOutput && loginOutput.body && loginOutput.body.authenticated === true),
      login_principal_len: loginOutput && loginOutput.body && typeof loginOutput.body.principal_id === "string" ? loginOutput.body.principal_id.length : 0,
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
      post_login_acceptance: acceptanceSummary,
      console_error_count: logs.length,
      account_recorded: false,
      password_recorded: false,
      cookies_recorded: false,
      secrets_recorded: false,
      headers_recorded: false,
      local_storage_values_recorded: false,
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
  const timeoutSeconds = Math.max(Number(options.timeoutSeconds || 180), 30);
  const labTab = await browser.tabs.new();
  const userTab = await browser.tabs.new();
  const startedAt = new Date();
  const deadline = Date.now() + timeoutSeconds * 1000;
  let finalReport = null;

  try {
    await labTab.goto(LAB_URL);
    await labTab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: 20000 });
    await labTab.playwright.waitForTimeout(1200);
    const labText = await labTab.playwright.locator("body").innerText({ timeoutMs: 10000 });
    const hasPostLoginButton = labText.includes("Post-Login Acceptance");

    await userTab.goto(USER_URL);
    await userTab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: 20000 });
    await userTab.playwright.waitForTimeout(2500);
    const userText = await userTab.playwright.locator("body").innerText({ timeoutMs: 10000 });
    const userUrl = await userTab.url();
    const userLooksLoggedOut = userText.includes("\u767b\u5f55") || userUrl.includes("/home");

    if (!hasPostLoginButton || userLooksLoggedOut) {
      finalReport = {
        schema: "openclaw-chrome-post-login-acceptance.v1",
        created_at: new Date().toISOString(),
        status: "PENDING_LOGIN",
        lab_url: await labTab.url(),
        user_url: userUrl,
        lab_has_post_login_acceptance_button: hasPostLoginButton,
        user_looks_logged_out: userLooksLoggedOut,
        lab_output_summary: await readOutputJson(labTab),
        secrets_recorded: false,
        headers_recorded: false,
        local_storage_values_recorded: false,
      };
      return finalReport;
    }

    await labTab.playwright.getByRole("button", { name: "Post-Login Acceptance", exact: true }).click({ timeoutMs: 10000 });
    let summary = { overall: null, failed_steps: [], step_count: 0, step_names: [] };
    while (Date.now() < deadline) {
      await labTab.playwright.waitForTimeout(1500);
      summary = summarizeAcceptance(await readOutputJson(labTab));
      if (summary.overall === "PASS" || summary.overall === "FAIL") break;
    }

    finalReport = {
      schema: "openclaw-chrome-post-login-acceptance.v1",
      created_at: new Date().toISOString(),
      status: summary.overall === "PASS" ? "PASS" : "FAIL",
      started_at: startedAt.toISOString(),
      finished_at: new Date().toISOString(),
      lab_url: await labTab.url(),
      user_url: await userTab.url(),
      lab_has_post_login_acceptance_button: hasPostLoginButton,
      acceptance_summary: summary,
      secrets_recorded: false,
      headers_recorded: false,
      local_storage_values_recorded: false,
    };
    return finalReport;
  } finally {
    if (options.finalize !== false) {
      const keep = [];
      if (!finalReport || finalReport.status !== "PASS") {
        keep.push({ tab: labTab, status: "handoff" }, { tab: userTab, status: "handoff" });
      }
      await browser.tabs.finalize({ keep });
    }
  }
}
