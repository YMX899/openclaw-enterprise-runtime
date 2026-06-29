export type EnterpriseRuntimeErrorCode =
  | "RUNTIME_INVALID_SPEC"
  | "RUNTIME_WORKSPACE_REQUIRED"
  | "RUNTIME_WORKSPACE_NOT_FOUND"
  | "RUNTIME_WORKSPACE_FORBIDDEN"
  | "RUNTIME_SESSION_KEY_REQUIRED"
  | "RUNTIME_CONFIG_REQUIRED"
  | "RUNTIME_CONFIG_NOT_FOUND"
  | "RUNTIME_CONFIG_VERSION_MISMATCH"
  | "RUNTIME_CONFIG_OVERRIDE_FORBIDDEN"
  | "RUNTIME_MODEL_PROFILE_NOT_FOUND"
  | "RUNTIME_MODEL_INPUT_UNSUPPORTED"
  | "RUNTIME_SANDBOX_REQUIRED"
  | "RUNTIME_TIMEOUT"
  | "RUNTIME_RUN_STALLED"
  | "RUNTIME_INTERNAL_ERROR"
  | "MODEL_KEY_POOL_BUSY"
  | "MODEL_KEY_POOL_EXHAUSTED"
  | "MODEL_KEY_AUTH_FAILED";

export class EnterpriseRuntimeError extends Error {
  constructor(
    readonly code: EnterpriseRuntimeErrorCode,
    message: string,
    readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "EnterpriseRuntimeError";
  }
}

export function toRuntimeError(error: unknown): { code: string; message: string } {
  if (error instanceof EnterpriseRuntimeError) {
    return { code: error.code, message: error.message };
  }
  if (error instanceof Error) {
    return { code: "RUNTIME_INTERNAL_ERROR", message: error.message };
  }
  return { code: "RUNTIME_INTERNAL_ERROR", message: String(error) };
}
