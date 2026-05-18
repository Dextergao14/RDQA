/**
 * Probe what tools the live OpenClaw Gateway exposes to runs, by trying a few
 * RPC methods through the SDK transport. None of these are guaranteed to exist
 * — we just want to find one that returns the active tool list.
 */
import { OpenClaw } from "@openclaw/sdk";

async function tryRpc(client: { request<T>(m: string, p?: unknown): Promise<T> }, method: string, params: unknown = {}): Promise<void> {
  try {
    const out = await client.request<unknown>(method, params);
    console.log(`\n=== ${method} ===`);
    console.log(JSON.stringify(out, null, 2).slice(0, 2500));
  } catch (err) {
    console.log(`\n=== ${method} ===  ERROR: ${err instanceof Error ? err.message : String(err)}`);
  }
}

async function main(): Promise<void> {
  const client = new OpenClaw({}) as unknown as {
    request<T>(m: string, p?: unknown): Promise<T>;
    close(): Promise<void>;
  };
  try {
    await tryRpc(client, "tools.list");
    await tryRpc(client, "tools.list", { agentId: "main" });
    await tryRpc(client, "agents.list");
    await tryRpc(client, "agents.get", { agentId: "main" });
    await tryRpc(client, "skills.list");
    await tryRpc(client, "toolsets.list");
    await tryRpc(client, "config.schema.lookup", { path: "agents.defaults" });
  } finally {
    await client.close();
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.stack ?? err.message : err);
  process.exitCode = 1;
});
