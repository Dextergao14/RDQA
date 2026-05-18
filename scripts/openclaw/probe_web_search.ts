/**
 * Single-prompt probe: explicitly demand web_search and verify the tool is
 * actually invoked.
 */
import { OpenClaw } from "@openclaw/sdk";

const PROMPT = `Search the web and tell me what year Tesla, Inc. was founded.
You MUST call web_search at least once before answering.
Do NOT answer from memory.`;

async function main(): Promise<void> {
  const client = new OpenClaw({}) as unknown as {
    runs: { create(p: Record<string, unknown>): Promise<{ events(): AsyncIterable<Record<string, unknown>>; wait(opts?: { timeoutMs?: number }): Promise<Record<string, unknown>> }> };
    close(): Promise<void>;
  };
  try {
    console.log(`Prompt:\n${PROMPT}\n`);
    const run = await client.runs.create({
      input: PROMPT,
      model: "openrouter/qwen/qwen3-235b-a22b",
      timeoutMs: 120_000,
      sessionKey: `probe-websearch-${Date.now()}`,
    });
    const events: Record<string, unknown>[] = [];
    const collect = (async () => {
      for await (const ev of run.events()) {
        events.push(ev);
        const t = ev.type as string;
        if (t === "run.completed" || t === "run.failed" || t === "run.timed_out" || t === "run.cancelled") break;
      }
    })();
    await run.wait({ timeoutMs: 120_000 });
    await collect;

    const counts: Record<string, number> = {};
    for (const e of events) counts[e.type as string] = (counts[e.type as string] || 0) + 1;
    console.log("event counts:", counts);

    const toolEvents = events.filter((e) => (e.type as string).startsWith("tool.call"));
    console.log(`\ntool.call events: ${toolEvents.length}`);
    for (const e of toolEvents) {
      const data = e.data as Record<string, unknown>;
      console.log(`  - ${e.type}  name=${data.name}  title=${data.title}`);
    }

    const lastDelta = [...events].reverse().find((e) => e.type === "assistant.delta") as Record<string, unknown> | undefined;
    const text = (lastDelta?.data as { text?: string } | undefined)?.text;
    console.log(`\nfinal answer (first 600 chars):\n${text?.slice(0, 600) ?? "(none)"}`);
  } finally {
    await client.close();
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.stack ?? err.message : err);
  process.exitCode = 1;
});
