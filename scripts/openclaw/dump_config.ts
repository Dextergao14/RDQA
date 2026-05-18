/**
 * Dump the live OpenClaw Gateway config so we can inspect which tools are enabled.
 *
 * What it does:
 *   - Connects to the running OpenClaw Gateway via @openclaw/sdk
 *   - Calls request("config.get", {}) (same path run_batch.ts uses to patch systemPromptOverride)
 *   - Pretty-prints config to stdout
 *
 * Usage: npm run dump-config
 */
import { OpenClaw } from "@openclaw/sdk";

async function main(): Promise<void> {
  const client = new OpenClaw({}) as unknown as {
    request<T>(method: string, params?: unknown): Promise<T>;
    close(): Promise<void>;
  };
  try {
    const snapshot = await client.request<{ config: unknown; hash?: string }>("config.get", {});
    process.stdout.write(JSON.stringify(snapshot, null, 2));
    process.stdout.write("\n");
  } finally {
    await client.close();
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.stack ?? err.message : err);
  process.exitCode = 1;
});
