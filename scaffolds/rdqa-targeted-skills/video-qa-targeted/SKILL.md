---
name: video-qa-targeted
description: "Answer a question about a specific video by reasoning about where the answer lives, watching only that part, and self-reflecting before returning. Use whenever the agent is asked about visual content, scoreboard/HUD values, on-screen text, demonstrated procedures, or temporal events inside a single video file or URL."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [video, multimodal, vision, qa, cot, self-reflection]
    related_skills: [audio-qa-targeted, youtube-content]
---

# Targeted Video QA

## Overview

A reasoning-driven video QA workflow. The agent does NOT watch the whole
video and does NOT rely on title/description metadata. Instead it:

1. **Probes** the video for cheap structural signals (duration, captions, chapters).
2. **Reasons** about *where* in the video the answer is most likely to live.
3. **Watches only that part** by extracting frames + captions at predicted timestamps.
4. **Self-reflects** on whether the sampled evidence actually answers the query.
5. **Iterates** if confidence is low — expand the window, try other timestamps, or sample more densely.
6. **Returns** the answer with a timestamp citation.

This is the baseline that paper §X uses as the reference video-QA scaffold.

## When to Use

- The user provides a video URL or a video file and asks a fine-grained
  question about its visual or audio-visual content.
- The question implies a particular region of the video (e.g. *"at 3:53"*,
  *"during the closing credits"*, *"when the lead first changes hands"*).
- The answer is a closed-form value (a number, name, date, on-screen text,
  short verdict).

Don't use for:

- Open-ended summarization (use `youtube-content` skill instead).
- Questions that need only video metadata (title, channel, view count).
- Questions answerable from public web pages without watching the video.

## Tools / Dependencies

```bash
# one-time
pip install yt-dlp pillow openai
# ffmpeg must be on PATH (Mac: brew install ffmpeg)
```

## Workflow

`SKILL_DIR` is the directory containing this SKILL.md.

### Step 1 — Probe (free, ~3 s)

Get cheap structural signals before deciding what to watch.

```bash
python3 SKILL_DIR/scripts/video_skill.py probe "<URL_or_path>"
# Returns JSON: {duration_sec, fps, has_captions, captions_summary, chapters}
```

The probe extracts captions if present (subtitle file or YouTube auto-caption)
and produces a 200-word condensed summary that is *only* used for locating —
**not** as the answer source.

### Step 2 — Locate (agent reasoning, no tool call)

Write an explicit CoT block before calling any sampler. Required template:

```
## Locate
- query intent: <one sentence>
- structural clue from probe: <duration / chapters / caption summary>
- predicted answer region(s):
    * t1 = <mm:ss> — rationale: <why>
    * t2 = <mm:ss> — rationale: <why>
    * t3 = <mm:ss> — rationale: <why>
- ranked confidence: t1 > t2 > t3
- window size to sample: <seconds>
```

Heuristics:

| Question pattern | Predicted region |
|---|---|
| *"at MM:SS"* / *"after K minutes"* | exactly that timestamp |
| *"on the opening / title / first card"* | 0:00–0:30 |
| *"in the closing credits"* | last 60 s |
| *"final score"* / *"at the end"* | last 5–10% of duration |
| *"first time X is mentioned"* | scan early window first, then mid |
| *"when did X change"* | sample at chapter boundaries |
| *"the n-th step of a tutorial"* | use chapters[n] if present; else linearly spaced |
| *"in the cave / shop / level / scene Y"* | scan **6 log-spaced** timestamps; mid-game segments are dense, late-game sparse |
| No clue at all | **6 log-spaced** timestamps (5 %, 12 %, 22 %, 35 %, 55 %, 80 % of duration) |

**Default density**: 6 candidate timestamps, not 3. Fine-grained queries (a
specific HUD label, a single name in credits, one passing shot of a sign)
miss with sparse sampling; the cost of 6 vs 3 windows is one extra
vision-analyze call but cuts iter-2 work in half.

Prefer **6 narrow windows** over 1 wide window when uncertain.

### Step 3 — Sample frames + captions

```bash
python3 SKILL_DIR/scripts/video_skill.py sample "<URL_or_path>" \
    --timestamps 00:53,02:10,04:35 \
    --window 4         \   # seconds around each timestamp
    --fps 1            \   # frame sampling rate inside window
    --max-frames 6
```

Returns a JSON with, per timestamp:

```json
{
  "ts": "00:53",
  "frames": ["/tmp/vqa/frame_00m53s_0.jpg", "..."],
  "caption_window": "[00:50] she picks up a red backpack and walks..."
}
```

Frames are stored on disk. Pass these paths to a vision-capable model
(`vision_analyze` tool) along with the original query.

### Step 4 — Analyze (vision MLLM)

For each `(ts, frames, caption_window)` triple, call the vision tool with
a focused prompt:

```
Question: <original query>
This is the video region around timestamp <ts>. Caption excerpt:
"<caption_window>"
Frames attached.

Reply in JSON:
{
  "evidence_in_frame": <true|false>,
  "extracted_answer": "<string or null>",
  "confidence": <0..1>,
  "rationale": "<one sentence>"
}
```

Run sequentially across timestamps; **stop early** the moment one window
returns `evidence_in_frame=true` with confidence ≥ 0.7.

### Step 5 — Self-reflect

Before emitting the final answer, write the reflection block:

```
## Reflect
- best window: t = <hh:mm:ss>
- extracted answer: <value>
- supporting evidence: caption "<...>" + frame at <ts>
- did the evidence answer the *literal* query? <yes/no>
- could the answer be from a different region? <list other candidates>
- residual uncertainty: <low/medium/high>
```

If residual uncertainty is **medium or high**, re-locate (Step 2) with
a different region set and repeat. Hard cap at **3 iterations** of
Step 2–4.

### Step 6 — Return

Emit final answer in the structured form the harness expects, including
a `evidence_timestamp` field. Without a timestamp citation the answer is
considered un-grounded.

```json
{
  "answer_value": "Cloud Services",
  "evidence_timestamp": "00:52",
  "evidence_frame": "/tmp/vqa/frame_00m52s_2.jpg",
  "confidence": 0.86
}
```

## Iteration Policy

- Iteration 1: **6 candidate timestamps (log-distributed)**, **12-second windows**,
  1 fps (~3-4 frames per window). Wider windows on the blind first pass
  catch transient labels (HUD prompts, lower-thirds that linger 3-6 s).
- Iteration 2 (only if iter 1 confidence < 0.7): 4 candidates clustered
  around the best-scoring iter-1 timestamp at ±10 s, ±30 s, ±60 s; 6-second
  windows, 2 fps. Goal is to confirm/deny the iter-1 lead.
- Iteration 3 (only if iter 2 confidence < 0.6): 8 candidates filling in
  the gaps the previous iterations missed, 8-second windows, 2 fps. Last
  resort.

Total budget cap: ~32 frames analyzed per question. Above that, return
the best-found answer with a low-confidence flag rather than burning more.

## Anti-Hallucination Protocol

Vision MLLMs frequently invent text that "looks like it could be" on
small / blurry on-screen labels (faint HUD overlays, lower-thirds, end
credits). When `vision_analyze` reports `evidence_in_frame=true`:

1. The wrapper performs **per-frame independent analysis**: each frame is
   read separately rather than as a stack.
2. The wrapper requires **≥2 frames from the SAME window** to yield the
   identical (case-insensitive, punctuation-stripped) `extracted_answer`
   before reporting `confirmed=true`.
3. If only 1 frame yields a positive read while others say "not visible"
   or yield a different answer, the wrapper returns `confirmed=false`
   and the agent should treat it as a hallucination candidate.

The agent should therefore prefer windows where **≥2 frames agree** over
windows with a single high-confidence single-frame read.

## Common Pitfalls

1. **Watching the whole video.** This skill is targeted by design. Do not
   call the sampler with `--all` or extract more than ~24 frames per question.
2. **Answering from caption summary alone.** The summary is for *locating*.
   The answer must be grounded in the sampled frames or the caption window
   at the chosen timestamp. If a question asks about visual content (HUD
   readout, on-screen text, color, gesture), captions alone are insufficient.
3. **Trusting the URL's title.** YouTube titles often contain the answer
   text verbatim and tempt the model to bypass the video. The harness flags
   any trajectory that visits the URL but never extracts a frame as
   `web_leak`. Always invoke the `sample` step.
4. **Skipping the Locate CoT.** Without the explicit timestamp prediction,
   the model defaults to a single mid-video sample, which fails on credits
   / opening / final-score questions.
5. **No reflection.** Without Step 5 the model returns the first plausible
   frame. Tasks with distractor scenes (e.g. multiple scoreboards across
   the video) need explicit cross-window comparison.

## Verification Checklist

- [ ] Probe was called and its output cited in the Locate block.
- [ ] Locate block lists ≥ 2 candidate timestamps with rationale.
- [ ] Sample step ran and produced JPG file paths.
- [ ] Vision tool was called on at least one frame.
- [ ] Reflect block explicitly states confidence ≥ 0.7.
- [ ] Final answer includes `evidence_timestamp`.

## One-Shot Recipe — Credits Scroll Question

> "*In the closing credits of <URL>, who is credited as cinematographer?*"

```
1. probe URL → duration = 24:13, captions=yes
2. Locate: closing credits → sample from 23:30 to 24:00 (window 30 s, fps 1)
3. sample URL --timestamps 23:35,23:45,23:55 --window 10 --fps 1
4. vision_analyze each window with the query
5. reflect: 23:45 frame shows "Cinematographer — Jane Doe", confidence 0.92
6. return {"answer_value": "Jane Doe", "evidence_timestamp": "23:45", ...}
```

## One-Shot Recipe — HUD Score Question

> "*At 3:53 of the YouTube video 'Epitaph | 2', what score is shown on the HUD?*"

```
1. probe URL (don't actually need it — timestamp is given, but still grab caps)
2. Locate: exact ts → t = 03:53, window 2 s, fps 2
3. sample URL --timestamps 03:53 --window 2 --fps 2 --max-frames 4
4. vision_analyze: "extract HUD numbers visible in these frames"
5. reflect: 4/4 frames show 13–7, confidence 0.95
6. return {"answer_value": "13-7", "evidence_timestamp": "03:53", ...}
```
