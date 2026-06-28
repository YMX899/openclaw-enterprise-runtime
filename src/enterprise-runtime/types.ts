import type { RuntimeRunSpec } from "../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import type { ProviderCredentialPool, ResolvedRuntimeConfigSnapshot } from "./config/types.js";
import type { ENTERPRISE_RUNTIME_SESSION_NAMESPACE } from "./constants.js";
import type { ModelKeyLease } from "./model-broker/types.js";

export type WorkspaceBoundary = {
  root: string;
  accessMode: "read" | "write";
  toolsAllow?: string[];
  toolsDeny?: string[];
};

export type RuntimeDirs = {
  stateDir: string;
  configPath: string;
  logsDir: string;
  tmpDir: string;
  runDir: string;
};

export type RuntimeRunContext = {
  runId: string;
  tenantId: string;
  userId: string;
  workspaceId: string;
  threadId: string;
  spec: RuntimeRunSpec;
  workspace: {
    root: string;
    queueKey: string;
    accessMode: "read" | "write";
  };
  session: {
    namespace: typeof ENTERPRISE_RUNTIME_SESSION_NAMESPACE;
    sessionKey: string;
    sessionId?: string;
  };
  input: RuntimeRunSpec["input"];
  configSnapshot: ResolvedRuntimeConfigSnapshot;
  credentialPools?: ProviderCredentialPool[];
  modelKeyLease?: ModelKeyLease;
  dirs: RuntimeDirs;
  boundary: WorkspaceBoundary;
  abortSignal?: AbortSignal;
};
