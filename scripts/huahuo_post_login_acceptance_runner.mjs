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
