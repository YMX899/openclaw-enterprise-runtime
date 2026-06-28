import { EnterpriseRuntimeError } from "../errors.js";

export class ModelKeyPoolError extends EnterpriseRuntimeError {
  constructor(
    code: "MODEL_KEY_POOL_BUSY" | "MODEL_KEY_POOL_EXHAUSTED" | "MODEL_KEY_AUTH_FAILED",
    message: string,
    details?: Record<string, unknown>,
  ) {
    super(code, message, details);
  }
}
