import fs from "node:fs/promises";
import path from "node:path";
import { ENTERPRISE_RUNTIME_CONFIG_SNAPSHOT_DIR } from "../constants.js";
import type { ResolvedRuntimeConfigSnapshot } from "./types.js";

export async function saveResolvedRuntimeConfigSnapshot(params: {
  stateDir: string;
  snapshot: ResolvedRuntimeConfigSnapshot;
}): Promise<string> {
  const dir = path.join(
    params.stateDir,
    "enterprise-runtime",
    ENTERPRISE_RUNTIME_CONFIG_SNAPSHOT_DIR,
  );
  await fs.mkdir(dir, { recursive: true });
  const filePath = path.join(dir, `${params.snapshot.runId}.json`);
  await fs.writeFile(filePath, JSON.stringify(params.snapshot, null, 2), {
    encoding: "utf8",
    mode: 0o600,
  });
  return filePath;
}
