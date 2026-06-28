import fs from "node:fs/promises";
import JSON5 from "json5";
import { EnterpriseRuntimeError } from "../errors.js";
import type { EnterpriseRuntimeConfigFile } from "./types.js";

function assertConfigFileShape(value: unknown): asserts value is EnterpriseRuntimeConfigFile {
  if (!value || typeof value !== "object") {
    throw new EnterpriseRuntimeError("RUNTIME_CONFIG_REQUIRED", "runtime config must be an object");
  }
  const cfg = value as Partial<EnterpriseRuntimeConfigFile>;
  if (!Array.isArray(cfg.runtimeConfigs)) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_REQUIRED",
      "runtime config requires runtimeConfigs[]",
    );
  }
  if (!Array.isArray(cfg.modelProfiles)) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_REQUIRED",
      "runtime config requires modelProfiles[]",
    );
  }
}

export async function loadEnterpriseRuntimeConfigFile(
  configPath: string,
): Promise<EnterpriseRuntimeConfigFile> {
  let text: string;
  try {
    text = await fs.readFile(configPath, "utf8");
  } catch {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_NOT_FOUND",
      `runtime config not found: ${configPath}`,
    );
  }
  try {
    const parsed = JSON5.parse(text) as unknown;
    assertConfigFileShape(parsed);
    return parsed;
  } catch (err) {
    if (err instanceof EnterpriseRuntimeError) {
      throw err;
    }
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_REQUIRED",
      `runtime config parse failed: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
}
