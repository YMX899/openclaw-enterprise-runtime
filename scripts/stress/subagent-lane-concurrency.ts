import { DEFAULT_SUBAGENT_MAX_CONCURRENT } from "../../src/config/agent-limits.js";
import { enqueueCommandInLane, resetCommandQueueStateForTest } from "../../src/process/command-queue.js";
import { CommandLane } from "../../src/process/lanes.js";
import { applyGatewayLaneConcurrency } from "../../src/gateway/server-lanes.js";

function createDeferred() {
  let resolve!: () => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<void>((resolveLocal, rejectLocal) => {
    resolve = resolveLocal;
    reject = rejectLocal;
  });
  return { promise, resolve, reject };
}

async function main() {
  const total = Number.parseInt(process.env.OPENCLAW_STRESS_AGENTS ?? "1000", 10);
  if (!Number.isSafeInteger(total) || total <= 0) {
    throw new Error("OPENCLAW_STRESS_AGENTS must be a positive integer");
  }
  if (total > DEFAULT_SUBAGENT_MAX_CONCURRENT) {
    throw new Error(
      `requested ${total} agents but default subagent concurrency is ${DEFAULT_SUBAGENT_MAX_CONCURRENT}`,
    );
  }

  resetCommandQueueStateForTest();
  applyGatewayLaneConcurrency({});

  let activeRuns = 0;
  let peakActiveRuns = 0;
  let startedRuns = 0;
  const allRunsStarted = createDeferred();
  const releaseRuns = createDeferred();

  const runs = Array.from({ length: total }, () =>
    enqueueCommandInLane(
      CommandLane.Subagent,
      async () => {
        activeRuns += 1;
        startedRuns += 1;
        peakActiveRuns = Math.max(peakActiveRuns, activeRuns);
        if (peakActiveRuns >= total) {
          allRunsStarted.resolve();
        }
        try {
          await releaseRuns.promise;
        } finally {
          activeRuns -= 1;
        }
      },
      { warnAfterMs: 30_000 },
    ),
  );

  const timeout = setTimeout(() => {
    allRunsStarted.reject(
      new Error(
        `timed out waiting for ${total} concurrent subagent runs; started=${startedRuns} peak=${peakActiveRuns}`,
      ),
    );
  }, 10_000);

  try {
    await allRunsStarted.promise;
  } finally {
    clearTimeout(timeout);
    releaseRuns.resolve();
  }
  await Promise.all(runs);

  if (peakActiveRuns !== total) {
    throw new Error(`expected peak concurrency ${total}, got ${peakActiveRuns}`);
  }
  console.log(
    JSON.stringify({
      ok: true,
      lane: CommandLane.Subagent,
      requested: total,
      defaultSubagentMaxConcurrent: DEFAULT_SUBAGENT_MAX_CONCURRENT,
      started: startedRuns,
      peakActive: peakActiveRuns,
    }),
  );
}

await main();
