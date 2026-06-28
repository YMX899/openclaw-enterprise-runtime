import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { RuntimeRunSpec } from "../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import {
  ENTERPRISE_RUNTIME_DEFAULT_LOGS_ENV,
  ENTERPRISE_RUNTIME_DEFAULT_TMP_ENV,
  ENTERPRISE_RUNTIME_LEGACY_LOGS_ENV,
  ENTERPRISE_RUNTIME_LEGACY_TMP_ENV,
} from "./constants.js";
import { EnterpriseRuntimeError } from "./errors.js";
import type { RuntimeDirs } from "./types.js";

const CONFIG_ENV = "OPENCLAW_ENTERPRISE_RUNTIME_CONFIG";
const LEGACY_CONFIG_ENV = "OPENCLAW_RUNTIME_CONFIG_PATH";

function envValue(env: NodeJS.ProcessEnv, key: string): string | undefined {
  const value = env[key]?.trim();
  return value || undefined;
}

async function realpathDir(input: string, code: "RUNTIME_WORKSPACE_NOT_FOUND") {
  try {
    const resolved = await fs.realpath(input);
    const stat = await fs.stat(resolved);
    if (!stat.isDirectory()) {
      throw new Error("not a directory");
    }
    return resolved;
  } catch {
    throw new EnterpriseRuntimeError(code, `workspace not found or not a directory: ${input}`);
  }
}

async function mkdirRealpath(input: string): Promise<string> {
  await fs.mkdir(input, { recursive: true });
  return await fs.realpath(input);
}

function assertOutsideWorkspace(params: { label: string; target: string; workspaceRoot: string }) {
  const relative = path.relative(params.workspaceRoot, params.target);
  if (!relative || (!relative.startsWith("..") && !path.isAbsolute(relative))) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_WORKSPACE_FORBIDDEN",
      `${params.label} must not be inside workspace`,
      { target: params.target, workspaceRoot: params.workspaceRoot },
    );
  }
}

export function resolveEnterpriseRuntimeConfigPath(
  spec: RuntimeRunSpec,
  env: NodeJS.ProcessEnv = process.env,
): string {
  const configPath =
    spec.runtime?.configPath ?? envValue(env, CONFIG_ENV) ?? envValue(env, LEGACY_CONFIG_ENV);
  if (!configPath) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_REQUIRED",
      `runtime config path required; pass runtime.configPath or set ${CONFIG_ENV}`,
    );
  }
  return path.resolve(configPath);
}

export async function resolveRuntimeWorkspace(spec: RuntimeRunSpec): Promise<{
  root: string;
  queueKey: string;
}> {
  const raw = spec.workspace.realPath.trim();
  if (!raw) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_WORKSPACE_REQUIRED",
      "workspace.realPath is required",
    );
  }
  const root = await realpathDir(raw, "RUNTIME_WORKSPACE_NOT_FOUND");
  return { root, queueKey: root };
}

export async function resolveRuntimeDirs(params: {
  spec: RuntimeRunSpec;
  workspaceRoot: string;
  configStateDir?: string;
  configLogsDir?: string;
  configTmpRoot?: string;
  env?: NodeJS.ProcessEnv;
}): Promise<RuntimeDirs> {
  const env = params.env ?? process.env;
  const stateDirRaw =
    params.spec.runtime?.stateDir ?? params.configStateDir ?? envValue(env, "OPENCLAW_STATE_DIR");
  if (!stateDirRaw) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_REQUIRED",
      "runtime.stateDir or OPENCLAW_STATE_DIR is required",
    );
  }
  const logsDirRaw =
    params.spec.runtime?.logsDir ??
    params.configLogsDir ??
    envValue(env, ENTERPRISE_RUNTIME_DEFAULT_LOGS_ENV) ??
    envValue(env, ENTERPRISE_RUNTIME_LEGACY_LOGS_ENV) ??
    path.join(stateDirRaw, "enterprise-runtime", "logs");
  const tmpRootRaw =
    params.spec.runtime?.tmpRoot ??
    params.configTmpRoot ??
    envValue(env, ENTERPRISE_RUNTIME_DEFAULT_TMP_ENV) ??
    envValue(env, ENTERPRISE_RUNTIME_LEGACY_TMP_ENV) ??
    path.join(os.tmpdir(), "openclaw-enterprise-runtime");
  const stateDir = await mkdirRealpath(path.resolve(stateDirRaw));
  const logsDir = await mkdirRealpath(path.resolve(logsDirRaw));
  const tmpRoot = await mkdirRealpath(path.resolve(tmpRootRaw));

  assertOutsideWorkspace({
    label: "stateDir",
    target: stateDir,
    workspaceRoot: params.workspaceRoot,
  });
  assertOutsideWorkspace({
    label: "logsDir",
    target: logsDir,
    workspaceRoot: params.workspaceRoot,
  });
  assertOutsideWorkspace({
    label: "tmpRoot",
    target: tmpRoot,
    workspaceRoot: params.workspaceRoot,
  });

  const runDir = await mkdirRealpath(path.join(logsDir, "runs", params.spec.runId));
  const tmpDir = await mkdirRealpath(path.join(tmpRoot, "runs", params.spec.runId));
  return {
    stateDir,
    configPath: resolveEnterpriseRuntimeConfigPath(params.spec, env),
    logsDir,
    tmpDir,
    runDir,
  };
}

export async function assertRuntimeAttachmentsInsideWorkspace(
  spec: RuntimeRunSpec,
  workspaceRoot: string,
): Promise<void> {
  for (const attachment of spec.input.attachments ?? []) {
    let realPath: string;
    try {
      realPath = await fs.realpath(attachment.path);
    } catch {
      throw new EnterpriseRuntimeError(
        "RUNTIME_WORKSPACE_FORBIDDEN",
        `attachment not found: ${attachment.path}`,
      );
    }
    const relative = path.relative(workspaceRoot, realPath);
    if (relative.startsWith("..") || path.isAbsolute(relative)) {
      throw new EnterpriseRuntimeError(
        "RUNTIME_WORKSPACE_FORBIDDEN",
        "attachment must be inside workspace",
        { attachment: attachment.name, path: realPath, workspaceRoot },
      );
    }
  }
}
