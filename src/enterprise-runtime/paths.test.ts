import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { RuntimeRunSpec } from "../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import type { EnterpriseRuntimeConfigFile, RuntimeConfig } from "./config/types.js";
import { resolveRuntimeDirs, resolveRuntimeStoreDirs, resolveRuntimeWorkspace } from "./paths.js";

let tempRoot: string | undefined;

async function makeTempRoot(): Promise<string> {
  tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-enterprise-runtime-paths-"));
  return tempRoot;
}

function runtimeSpec(workspaceDir: string): RuntimeRunSpec {
  return {
    runId: "run-1",
    tenantId: "tenant-1",
    userId: "user-1",
    workspaceId: "workspace-1",
    threadId: "thread-1",
    runtimeConfigId: "coding-default",
    workspace: {
      realPath: workspaceDir,
      accessMode: "write",
    },
    productSession: {
      threadId: "thread-1",
      openclawSessionKey:
        "runtime:tenant:tenant-1:user:user-1:workspace:workspace-1:thread:thread-1",
    },
    runtime: {
      configPath: path.join(path.dirname(workspaceDir), "runtime.json"),
    },
    input: {
      message: "hello",
    },
  };
}

function configFile(params: {
  runtimeConfig: RuntimeConfig;
  sessionStores?: EnterpriseRuntimeConfigFile["sessionStores"];
  artifactStores?: EnterpriseRuntimeConfigFile["artifactStores"];
}): EnterpriseRuntimeConfigFile {
  return {
    runtimeConfigs: [params.runtimeConfig],
    modelProfiles: [{ id: "profile-1", provider: "openai", model: "gpt-5" }],
    ...(params.sessionStores ? { sessionStores: params.sessionStores } : {}),
    ...(params.artifactStores ? { artifactStores: params.artifactStores } : {}),
  };
}

describe("enterprise runtime paths", () => {
  afterEach(async () => {
    if (tempRoot) {
      await fs.rm(tempRoot, { recursive: true, force: true });
      tempRoot = undefined;
    }
  });

  it("uses file session and artifact stores as runtime directory defaults", async () => {
    const root = await makeTempRoot();
    const workspaceDir = path.join(root, "workspace");
    await fs.mkdir(workspaceDir, { recursive: true });
    const runtimeConfig: RuntimeConfig = {
      id: "coding-default",
      sessionStoreId: "session-file",
      artifactStoreId: "artifact-file",
      model: { modelProfileId: "profile-1" },
    };
    const storeDirs = resolveRuntimeStoreDirs({
      runtimeConfig,
      configFile: configFile({
        runtimeConfig,
        sessionStores: [
          { id: "session-file", type: "file", rootDir: path.join(root, "state-from-store") },
        ],
        artifactStores: [
          {
            id: "artifact-file",
            type: "file",
            logsDir: path.join(root, "logs-from-store"),
            tmpRoot: path.join(root, "tmp-from-store"),
          },
        ],
      }),
    });

    const workspace = await resolveRuntimeWorkspace(runtimeSpec(workspaceDir));
    const dirs = await resolveRuntimeDirs({
      spec: runtimeSpec(workspaceDir),
      workspaceRoot: workspace.root,
      configStateDir: storeDirs.stateDir,
      configLogsDir: storeDirs.logsDir,
      configTmpRoot: storeDirs.tmpRoot,
      env: {},
    });

    expect(dirs.stateDir).toBe(await fs.realpath(path.join(root, "state-from-store")));
    expect(dirs.logsDir).toBe(await fs.realpath(path.join(root, "logs-from-store")));
    expect(dirs.runDir).toBe(
      await fs.realpath(path.join(root, "logs-from-store", "runs", "run-1")),
    );
    expect(dirs.tmpDir).toBe(await fs.realpath(path.join(root, "tmp-from-store", "runs", "run-1")));
  });

  it("keeps explicit runtime directories above configured stores", () => {
    const runtimeConfig: RuntimeConfig = {
      id: "coding-default",
      stateDir: "/explicit/state",
      logsDir: "/explicit/logs",
      tmpRoot: "/explicit/tmp",
      sessionStoreId: "session-file",
      artifactStoreId: "artifact-file",
      model: { modelProfileId: "profile-1" },
    };

    expect(
      resolveRuntimeStoreDirs({
        runtimeConfig,
        configFile: configFile({
          runtimeConfig,
          sessionStores: [{ id: "session-file", type: "file", rootDir: "/store/state" }],
          artifactStores: [
            {
              id: "artifact-file",
              type: "file",
              logsDir: "/store/logs",
              tmpRoot: "/store/tmp",
            },
          ],
        }),
      }),
    ).toEqual({
      stateDir: "/explicit/state",
      logsDir: "/explicit/logs",
      tmpRoot: "/explicit/tmp",
    });
  });

  it("fails closed for managed store backends that are not implemented by the current file backend", () => {
    const runtimeConfig: RuntimeConfig = {
      id: "coding-default",
      sessionStoreId: "session-db",
      model: { modelProfileId: "profile-1" },
    };

    expect(() =>
      resolveRuntimeStoreDirs({
        runtimeConfig,
        configFile: configFile({
          runtimeConfig,
          sessionStores: [
            {
              id: "session-db",
              type: "database",
              connectionRef: "env:DATABASE_URL",
            },
          ],
        }),
      }),
    ).toThrow(/type database is not supported by the current file backend/);
  });
});
