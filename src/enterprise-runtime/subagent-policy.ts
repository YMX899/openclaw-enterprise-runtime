import { normalizeToolName } from "../agents/tool-policy.js";

export const ENTERPRISE_RUNTIME_SUBAGENT_DENYLIST = [
  "sessions_spawn",
  "sessions_yield",
  "sessions_list",
  "sessions_history",
  "sessions_send",
  "subagents",
  "agents_list",
] as const;

const ENTERPRISE_RUNTIME_SUBAGENT_DENYSET = new Set(
  ENTERPRISE_RUNTIME_SUBAGENT_DENYLIST.map((toolName) => normalizeToolName(toolName)),
);

function uniqueToolNames(values: Iterable<string>): string[] {
  const next: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const normalized = normalizeToolName(value);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    next.push(normalized);
  }
  return next;
}

export function applyEnterpriseRuntimeSubagentToolPolicy(tools: {
  allow?: string[];
  deny?: string[];
}): {
  allow?: string[];
  deny: string[];
} {
  const allow =
    tools.allow === undefined
      ? undefined
      : uniqueToolNames(
          tools.allow.filter(
            (toolName) => !ENTERPRISE_RUNTIME_SUBAGENT_DENYSET.has(normalizeToolName(toolName)),
          ),
        );
  return {
    ...(allow === undefined ? {} : { allow }),
    deny: uniqueToolNames([...(tools.deny ?? []), ...ENTERPRISE_RUNTIME_SUBAGENT_DENYLIST]),
  };
}
