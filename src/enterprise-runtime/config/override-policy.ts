import type {
  RuntimeModelOverride,
  RuntimeRunSpec,
} from "../../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import { EnterpriseRuntimeError } from "../errors.js";
import type { RuntimeConfig } from "./types.js";

const THINKING_ORDER = ["off", "minimal", "low", "medium", "high", "adaptive", "xhigh", "max"];
const SHELL_TOOLS = new Set(["exec", "bash", "process", "shell.exec"]);
const MUTATING_TOOLS = new Set([
  "write",
  "edit",
  "apply_patch",
  "exec",
  "bash",
  "process",
  "shell.exec",
]);

function hasValue<T>(value: T | undefined): value is T {
  return value !== undefined;
}

function assertAllowed(value: string | undefined, allowed: string[] | undefined, field: string) {
  if (value && allowed && !allowed.includes(value)) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
      `${field} override is not allowed`,
      { field, value },
    );
  }
}

function assertModelOverrideAllowed(config: RuntimeConfig, override?: RuntimeModelOverride) {
  if (!override) {
    return;
  }
  const policy = config.overridePolicy?.model;
  const allowedFields = new Set(policy?.allowedFields ?? []);
  for (const key of Object.keys(override) as Array<keyof RuntimeModelOverride>) {
    if (!allowedFields.has(key)) {
      throw new EnterpriseRuntimeError(
        "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
        `model override '${String(key)}' is not allowed`,
        { field: key },
      );
    }
  }
  assertAllowed(override.provider, policy?.allowedProviders, "provider");
  assertAllowed(override.model, policy?.allowedModels, "model");
  assertAllowed(override.modelProfileId, policy?.allowedModelProfileIds, "modelProfileId");
  assertAllowed(override.authPoolId, policy?.allowedAuthPoolIds, "authPoolId");
  if (
    override.thinking &&
    policy?.allowedThinking &&
    !policy.allowedThinking.includes(override.thinking)
  ) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
      "thinking override is not allowed",
    );
  }
  if (override.thinking && config.overridePolicy?.model?.allowedThinking?.length === undefined) {
    const max = config.model.thinking;
    if (max && THINKING_ORDER.indexOf(override.thinking) > THINKING_ORDER.indexOf(max)) {
      throw new EnterpriseRuntimeError(
        "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
        "thinking override exceeds runtime config",
      );
    }
  }
  if (
    hasValue(override.timeoutSeconds) &&
    hasValue(policy?.maxTimeoutSeconds) &&
    override.timeoutSeconds > policy.maxTimeoutSeconds
  ) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
      "timeoutSeconds override exceeds policy",
    );
  }
  if (
    hasValue(override.maxTokens) &&
    hasValue(policy?.maxTokens) &&
    override.maxTokens > policy.maxTokens
  ) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
      "maxTokens override exceeds policy",
    );
  }
  if (override.params) {
    const allowedParams = new Set(policy?.allowParams ?? []);
    for (const key of Object.keys(override.params)) {
      if (!allowedParams.has(key)) {
        throw new EnterpriseRuntimeError(
          "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
          `model param override '${key}' is not allowed`,
        );
      }
    }
  }
}

function assertToolOverrideAllowed(config: RuntimeConfig, spec: RuntimeRunSpec) {
  const allow = spec.tools?.allow ?? [];
  const deny = spec.tools?.deny ?? [];
  const policy = config.overridePolicy?.tools;
  if (allow.length && policy?.allowRuntimeAllowList !== true) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
      "tools.allow override is not allowed",
    );
  }
  if (deny.length && policy?.allowRuntimeDenyList !== true) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
      "tools.deny override is not allowed",
    );
  }
  const allowedToolNames = new Set(policy?.allowedToolNames ?? []);
  if (allowedToolNames.size) {
    for (const tool of [...allow, ...deny]) {
      if (!allowedToolNames.has(tool)) {
        throw new EnterpriseRuntimeError(
          "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
          `tool override '${tool}' is not allowed`,
        );
      }
    }
  }
}

function assertPluginOverrideAllowed(config: RuntimeConfig, spec: RuntimeRunSpec) {
  const enabled = spec.plugins?.enabled ?? [];
  const disabled = spec.plugins?.disabled ?? [];
  const policy = config.overridePolicy?.plugins;
  if (enabled.length && policy?.allowEnable !== true) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
      "plugins.enabled override is not allowed",
    );
  }
  if (disabled.length && policy?.allowDisable !== true) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
      "plugins.disabled override is not allowed",
    );
  }
  const allowedPluginIds = new Set(policy?.allowedPluginIds ?? []);
  if (allowedPluginIds.size) {
    for (const plugin of [...enabled, ...disabled]) {
      if (!allowedPluginIds.has(plugin)) {
        throw new EnterpriseRuntimeError(
          "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
          `plugin override '${plugin}' is not allowed`,
        );
      }
    }
  }
}

export function assertRuntimeOverridesAllowed(config: RuntimeConfig, spec: RuntimeRunSpec): void {
  assertModelOverrideAllowed(config, spec.modelOverride);
  assertToolOverrideAllowed(config, spec);
  assertPluginOverrideAllowed(config, spec);
}

export function assertEnterpriseShellPolicy(params: {
  toolsAllow?: string[];
  sandboxed: boolean;
}): void {
  if (params.sandboxed) {
    return;
  }
  const requested = params.toolsAllow ?? [];
  if (requested.some((tool) => SHELL_TOOLS.has(tool))) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_SANDBOX_REQUIRED",
      "enterprise runtime shell tools require sandbox",
    );
  }
}

export function assertReadModeTools(toolsAllow: string[] | undefined): void {
  for (const tool of toolsAllow ?? []) {
    if (MUTATING_TOOLS.has(tool)) {
      throw new EnterpriseRuntimeError(
        "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN",
        `read access mode cannot enable mutating tool '${tool}'`,
      );
    }
  }
}

export function stripReadModeMutatingTools(tools: string[] | undefined): string[] | undefined {
  if (!tools) {
    return undefined;
  }
  return tools.filter((tool) => !MUTATING_TOOLS.has(tool));
}
