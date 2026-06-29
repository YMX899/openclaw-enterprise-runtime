import fs from "node:fs";
import path from "node:path";
import type { RuntimeRunResult } from "../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import { ENTERPRISE_RUNTIME_SESSION_NAMESPACE } from "./constants.js";
import type { RuntimeRunContext } from "./types.js";

export function resolveEnterpriseRuntimeSessionStorePath(stateDir: string): string {
  return path.join(
    stateDir,
    "agents",
    ENTERPRISE_RUNTIME_SESSION_NAMESPACE,
    "sessions",
    "sessions.json",
  );
}

export function resolveEnterpriseRuntimeSessionsDir(stateDir: string): string {
  return path.dirname(resolveEnterpriseRuntimeSessionStorePath(stateDir));
}

type SessionStoreEntry = {
  sessionId?: unknown;
  sessionFile?: unknown;
};

function normalizeNonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function readSessionEntryFromStore(params: {
  storePath: string;
  sessionKey: string;
}): SessionStoreEntry | undefined {
  try {
    const parsed = JSON.parse(fs.readFileSync(params.storePath, "utf8")) as Record<
      string,
      SessionStoreEntry | undefined
    >;
    return parsed[params.sessionKey];
  } catch {
    return undefined;
  }
}

function isPathInsideDir(params: { filePath: string; dir: string }): boolean {
  const dirPath = path.resolve(params.dir);
  const candidatePath = path.resolve(params.filePath);
  const relative = path.relative(dirPath, candidatePath);
  return Boolean(relative) && !relative.startsWith("..") && !path.isAbsolute(relative);
}

function normalizeSessionFileInsideStore(params: {
  storePath: string;
  sessionFile: unknown;
}): string | undefined {
  const sessionFile = normalizeNonEmptyString(params.sessionFile);
  if (!sessionFile) {
    return undefined;
  }
  const sessionsDir = path.dirname(params.storePath);
  const resolved = path.isAbsolute(sessionFile)
    ? path.resolve(sessionFile)
    : path.resolve(sessionsDir, sessionFile);
  return isPathInsideDir({ filePath: resolved, dir: sessionsDir }) ? resolved : undefined;
}

function resolveSessionFileFromStore(params: {
  storePath: string;
  sessionKey: string;
}): string | undefined {
  const entry = readSessionEntryFromStore(params);
  return normalizeSessionFileInsideStore({
    storePath: params.storePath,
    sessionFile: entry?.sessionFile,
  });
}

function resolveSessionIdFromStore(params: {
  storePath: string;
  sessionKey: string;
}): string | undefined {
  return normalizeNonEmptyString(readSessionEntryFromStore(params)?.sessionId);
}

export function buildEnterpriseRuntimeSessionResult(params: {
  ctx: RuntimeRunContext;
  sessionFile?: unknown;
  sessionId?: unknown;
}): RuntimeRunResult["session"] {
  const storePath = resolveEnterpriseRuntimeSessionStorePath(params.ctx.dirs.stateDir);
  const sessionId =
    normalizeNonEmptyString(params.sessionId) ??
    params.ctx.session.sessionId ??
    resolveSessionIdFromStore({ storePath, sessionKey: params.ctx.session.sessionKey });
  const filePath =
    normalizeSessionFileInsideStore({ storePath, sessionFile: params.sessionFile }) ??
    resolveSessionFileFromStore({ storePath, sessionKey: params.ctx.session.sessionKey });
  return {
    namespace: params.ctx.session.namespace,
    storePath,
    ...(sessionId ? { sessionId } : {}),
    ...(filePath ? { filePath } : {}),
  };
}
