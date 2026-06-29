import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type { RuntimeRunSpec } from "../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import { resolveRuntimeAttachments } from "./attachments.js";
import { EnterpriseRuntimeError } from "./errors.js";

function baseSpec(attachments: RuntimeRunSpec["input"]["attachments"]): RuntimeRunSpec {
  return {
    runId: "run-attachments",
    tenantId: "tenant",
    userId: "user",
    workspaceId: "workspace",
    threadId: "thread",
    runtimeConfigId: "coding-default",
    workspace: {
      realPath: "/workspace",
      accessMode: "write",
    },
    productSession: {
      threadId: "thread",
      openclawSessionKey: "runtime:tenant:user:workspace:thread",
    },
    input: {
      message: "hello",
      attachments,
    },
  };
}

async function withTempWorkspace<T>(fn: (workspaceRoot: string) => Promise<T>): Promise<T> {
  const workspaceRoot = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-runtime-attachments-"));
  try {
    return await fn(workspaceRoot);
  } finally {
    await fs.rm(workspaceRoot, { recursive: true, force: true });
  }
}

describe("resolveRuntimeAttachments", () => {
  it("rejects declared image attachments whose bytes are not an image", async () => {
    await withTempWorkspace(async (workspaceRoot) => {
      const fakeImage = path.join(workspaceRoot, "not-a-real-image.png");
      await fs.writeFile(fakeImage, "not a real image", "utf8");

      await expect(
        resolveRuntimeAttachments({
          workspaceRoot,
          spec: baseSpec([{ name: "fake", path: fakeImage, kind: "image/png" }]),
        }),
      ).rejects.toMatchObject<Partial<EnterpriseRuntimeError>>({
        code: "RUNTIME_INVALID_SPEC",
      });
    });
  });

  it("accepts a PNG attachment detected from magic bytes", async () => {
    await withTempWorkspace(async (workspaceRoot) => {
      const image = path.join(workspaceRoot, "tiny.png");
      await fs.writeFile(
        image,
        Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x00]),
      );

      const attachments = await resolveRuntimeAttachments({
        workspaceRoot,
        spec: baseSpec([{ name: "tiny", path: image, kind: "image" }]),
      });

      expect(attachments).toHaveLength(1);
      expect(attachments[0]?.mimeType).toBe("image/png");
      expect(attachments[0]?.image?.mimeType).toBe("image/png");
    });
  });
});
