# RDQA OpenClaw Runner

This folder contains the OpenClaw-only evaluation plumbing from `docs/openclaw_eval_plan.md`.

## What Is Automated

- `build_dataset.py` converts `data/rdqa_clean_part_*.json` into:
  - `data/openclaw_dataset.json`: prompt-only JSON for OpenClaw.
  - `data/openclaw_metadata.json`: hidden ground-truth/source/evidence sidecar for later scoring.
- `run_batch.ts` submits those prompts to OpenClaw Gateway via `@openclaw/sdk`, waits for runs, and writes per-task run output plus event traces.
- `run_batch.ts` also patches the active OpenClaw Gateway config so the RDQA benchmark system prompt lives in `agents.defaults.systemPromptOverride` on the OpenClaw side.

The OpenRouter API key is not stored in this repo. Configure it through OpenClaw onboarding or your OpenClaw config.

## Environment Split

Use Windows or WSL2 for dataset generation:

```bash
python scripts/openclaw/build_dataset.py
```

Use WSL2 for OpenClaw Gateway and the Node runner:

```bash
cd /mnt/d/Github/RDQA/scripts/openclaw
```

## One-Time OpenClaw Setup In WSL2

Keep the real OpenRouter key in a local ignored `.env` file:

```bash
cd /mnt/d/Github/RDQA
cp .env.example .env
# edit .env and fill OPENROUTER_API_KEY
set -a
source .env
set +a
```

```bash
nvm install 22
nvm use 22
npm install -g openclaw@latest
openclaw onboard --install-daemon
openclaw doctor
openclaw agent --agent main --model openrouter/qwen/qwen3-235b-a22b --message "say hello" --json
```

During onboarding, choose OpenRouter as the model provider and enter `OPENROUTER_API_KEY`.

## Install Runner Dependencies

`third_party/openclaw/` is a git submodule pinned to OpenClaw commit
`f066dd2` (= release `2026.5.12`, which matches the daemon installed by
`npm install -g openclaw@latest`). The SDK is `@openclaw/sdk` and is not
published to npm, so it must be built from the submodule before this runner
can install its `file:` dependency.

### Fresh checkout (teammates cloning the RDQA repo for the first time)

```bash
# 1. Clone with submodule contents
git clone --recurse-submodules <RDQA-repo-url>

# (If the repo was already cloned without --recurse-submodules:)
git submodule update --init --recursive
```

### Build the SDK + link this runner

```bash
# Build @openclaw/sdk from the submodule (~1 min)
cd third_party/openclaw
pnpm install
pnpm --filter @openclaw/sdk build

# Install runner deps; pnpm step above produced packages/sdk/dist/ which
# `file:../../third_party/openclaw/packages/sdk` will pick up.
cd ../../scripts/openclaw
npm install
```

### Pulling submodule updates later

The submodule URL is upstream OpenClaw (`https://github.com/openclaw/openclaw.git`).
If you ever bump to a newer OpenClaw version (e.g. when daemon upgrades):

```bash
cd third_party/openclaw
git fetch origin
git checkout <new-commit-or-tag>
cd ../..
pnpm -C third_party/openclaw --filter @openclaw/sdk build
git add third_party/openclaw     # stages the new pinned commit
git commit -m "Bump openclaw submodule to <version>"
```

> Do not commit `third_party/openclaw/node_modules` or
> `third_party/openclaw/packages/*/dist`; the submodule only tracks source.

## Smoke Test

```bash
cd /mnt/d/Github/RDQA
python scripts/openclaw/build_dataset.py --limit 20

cd /mnt/d/Github/RDQA/scripts/openclaw
npm run batch -- --model qwen --limit 20 --resume
```

Outputs go under:

```text
outputs/openclaw/qwen__qwen3-235b-a22b/
  results.jsonl
  predictions.json
  runs/<task_id>__<timestamp>.json
```

## Full Run

```bash
cd /mnt/d/Github/RDQA
python scripts/openclaw/build_dataset.py

cd /mnt/d/Github/RDQA/scripts/openclaw
npm run batch -- --model all --concurrency 1 --resume
```

Raise `--concurrency` only after the smoke test is stable and OpenRouter rate limits are known.

## Counts

The source files currently declare 1275 items in `dataset_meta.item_count`, but contain 1128 actual rows in `data[]`. The builder uses the actual `data[]` rows and reports the discrepancy.
