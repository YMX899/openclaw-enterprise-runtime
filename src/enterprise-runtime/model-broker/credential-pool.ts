import fs from "node:fs";
import { ModelKeyPoolError } from "./errors.js";

export function resolveSecretRef(secretRef: string, env: NodeJS.ProcessEnv = process.env): string {
  const trimmed = secretRef.trim();
  if (trimmed.startsWith("env:")) {
    const name = trimmed.slice("env:".length).trim();
    const value = env[name]?.trim();
    if (!value) {
      throw new ModelKeyPoolError("MODEL_KEY_AUTH_FAILED", `missing credential env: ${name}`);
    }
    return value;
  }
  if (trimmed.startsWith("file:")) {
    const file = trimmed.slice("file:".length).trim();
    const value = fs.readFileSync(file, "utf8").trim();
    if (!value) {
      throw new ModelKeyPoolError("MODEL_KEY_AUTH_FAILED", `empty credential file: ${file}`);
    }
    return value;
  }
  throw new ModelKeyPoolError(
    "MODEL_KEY_AUTH_FAILED",
    `unsupported credential secretRef: ${trimmed.split(":", 1)[0] || "(empty)"}`,
  );
}
