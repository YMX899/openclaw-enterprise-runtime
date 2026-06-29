import { EnterpriseRuntimeError } from "./errors.js";

type StalledScope = "workspace" | "session";

type StalledRun = {
  scope: StalledScope;
  key: string;
  runId: string;
  stalledAt: string;
};

type StalledEntry = {
  scope: StalledScope;
  key: string;
};

const stalledRuns = new Map<string, StalledRun>();

function stalledKey(entry: StalledEntry): string {
  return `${entry.scope}\0${entry.key}`;
}

export function assertNoStalledRuntimeRun(entries: StalledEntry[]): void {
  for (const entry of entries) {
    const stalled = stalledRuns.get(stalledKey(entry));
    if (!stalled) {
      continue;
    }
    throw new EnterpriseRuntimeError(
      "RUNTIME_RUN_STALLED",
      `previous ${entry.scope} run is still shutting down after timeout`,
      {
        scope: entry.scope,
        runId: stalled.runId,
        stalledAt: stalled.stalledAt,
      },
    );
  }
}

export function markRuntimeRunStalled(params: { entries: StalledEntry[]; runId: string }): void {
  const stalledAt = new Date().toISOString();
  for (const entry of params.entries) {
    stalledRuns.set(stalledKey(entry), {
      ...entry,
      runId: params.runId,
      stalledAt,
    });
  }
}

export function clearRuntimeRunStalled(params: { entries: StalledEntry[]; runId: string }): void {
  for (const entry of params.entries) {
    const key = stalledKey(entry);
    const stalled = stalledRuns.get(key);
    if (stalled?.runId === params.runId) {
      stalledRuns.delete(key);
    }
  }
}

export function getStalledRuntimeRunCountForTest(): number {
  return stalledRuns.size;
}

export function resetStalledRuntimeRunsForTest(): void {
  stalledRuns.clear();
}
