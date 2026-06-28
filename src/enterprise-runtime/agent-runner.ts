import type { RuntimeRunResult } from "../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import { agentCommandFromIngress } from "../agents/agent-command.js";
import type { AgentCommandIngressOpts } from "../agents/command/types.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { defaultRuntime } from "../runtime.js";
import { buildEnterpriseRunOpenClawConfig } from "./config/run-config.js";
import { ENTERPRISE_RUNTIME_SESSION_NAMESPACE } from "./constants.js";
import type { RuntimeRunContext } from "./types.js";

function finalAnswerFromAgentResult(
  result: Awaited<ReturnType<typeof agentCommandFromIngress>>,
): string | undefined {
  const payloads = Array.isArray(result?.payloads) ? result.payloads : [];
  const text = payloads
    .map((payload) => (typeof payload?.text === "string" ? payload.text : ""))
    .filter(Boolean)
    .join("\n\n")
    .trim();
  return text || undefined;
}

export async function runEnterpriseAgent(
  ctx: RuntimeRunContext,
  baseConfig: OpenClawConfig,
): Promise<{
  result: RuntimeRunResult;
  rawAgentResult: Awaited<ReturnType<typeof agentCommandFromIngress>>;
}> {
  const runConfig = buildEnterpriseRunOpenClawConfig({
    baseConfig,
    snapshot: ctx.configSnapshot,
    lease: ctx.modelKeyLease,
  });
  const agentOpts: AgentCommandIngressOpts = {
    message: ctx.input.message,
    transcriptMessage: ctx.input.message,
    sessionKey: ctx.session.sessionKey,
    sessionStoreNamespace: ENTERPRISE_RUNTIME_SESSION_NAMESPACE,
    workspaceDir: ctx.workspace.root,
    cwd: ctx.workspace.root,
    runId: ctx.runId,
    provider: ctx.configSnapshot.model.provider,
    model: ctx.configSnapshot.model.model,
    thinking: ctx.configSnapshot.model.thinking,
    timeout:
      ctx.configSnapshot.model.timeoutSeconds !== undefined
        ? String(ctx.configSnapshot.model.timeoutSeconds)
        : undefined,
    promptMode: ctx.configSnapshot.prompt?.mode,
    extraSystemPrompt: ctx.configSnapshot.prompt?.extraSystemPrompt,
    toolsAllow: ctx.configSnapshot.tools.allow,
    senderIsOwner: true,
    allowModelOverride: true,
    deliver: false,
    sessionEffects: "visible",
    suppressPromptPersistence: false,
    abortSignal: ctx.abortSignal,
    enterpriseRuntime: {
      runContext: ctx,
      sessionStoreNamespace: ENTERPRISE_RUNTIME_SESSION_NAMESPACE,
      resolvedConfigSnapshotId: ctx.configSnapshot.snapshotId,
      suppressWorkspaceFallback: true,
      config: runConfig,
    },
    cleanupBundleMcpOnRunEnd: true,
  };
  const rawAgentResult = await agentCommandFromIngress(agentOpts, defaultRuntime);
  const finalAnswer = finalAnswerFromAgentResult(rawAgentResult);
  return {
    rawAgentResult,
    result: {
      runId: ctx.runId,
      status: "succeeded",
      threadId: ctx.threadId,
      openclawSessionKey: ctx.session.sessionKey,
      workspaceDir: ctx.workspace.root,
      resolvedConfigSnapshotId: ctx.configSnapshot.snapshotId,
      finalAnswer,
      logs: {
        eventsPath: `${ctx.dirs.runDir}/events.jsonl`,
        accessDenyPath: `${ctx.dirs.runDir}/access-deny.jsonl`,
      },
      usage: {
        provider: ctx.configSnapshot.model.provider,
        model: ctx.configSnapshot.model.model,
        authPoolId: ctx.configSnapshot.model.authPoolId,
        keyId: ctx.modelKeyLease?.keyId,
      },
    },
  };
}
