---
name: audio-qa-targeted
description: "Answer a question about a specific audio file by reasoning about where the answer lives, listening only to that segment via on-demand transcription, and self-reflecting before returning. Use whenever the agent is asked about content inside an audio file (earnings call, podcast, hearing, broadcast) where the answer is a closed-form value such as a spoken phrase, a name, a date, a number, an event identifier, or a non-speech cue (alarm/tone/music)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [audio, asr, multimodal, qa, cot, self-reflection]
    related_skills: [video-qa-targeted, youtube-content]
---

# Targeted Audio QA

## Overview

Audio-modality counterpart to `video-qa-targeted`. The agent does NOT
transcribe the whole audio and does NOT answer from search snippets about
the audio's title. Instead it:

1. **Probes** the audio for duration, sample rate, channel info, and any
   pre-existing transcript or chapter list.
2. **Reasons** about *where* the answer is likely to live (opening remarks,
   Q&A section, after a topic transition, in a specific minute).
3. **Listens to only that part** by transcribing a small targeted window
   (Whisper) plus, when relevant, running a non-speech audio classifier.
4. **Self-reflects** on whether the transcript snippet actually answers
   the query.
5. **Iterates** if confidence is low.
6. **Returns** the answer with a timestamp citation.

## When to Use

- The user provides an audio URL or audio file and asks a fine-grained
  question whose answer is a single short string.
- The question implies a particular region of the audio (e.g.
  *"in the opening remarks"*, *"during the analyst Q&A"*, *"the first time
  X is mentioned"*, *"at 14:30"*).
- The question is about a non-speech cue (alarm, music, tone, environmental
  sound) — use the non-speech sub-flow below.

Don't use for:

- Open-ended audio summarization.
- Questions answerable from the audio's title or known metadata.
- Music transcription, song lyrics retrieval — out of scope.

## Tools / Dependencies

```bash
# one-time
pip install yt-dlp openai
# ffmpeg on PATH
# For Whisper: either OPENAI_API_KEY (whisper-1) or local whisper.cpp
```

Set one of:

- `OPENAI_API_KEY` — used by the script for `whisper-1` transcription.
- `WHISPER_BIN` — path to a local `whisper.cpp` binary, with `WHISPER_MODEL`
  pointing to a GGUF model.

## Workflow

`SKILL_DIR` is the directory containing this SKILL.md.

### Step 1 — Probe (free, ~2 s)

```bash
python3 SKILL_DIR/scripts/audio_skill.py probe "<URL_or_path>"
# Returns: {duration_sec, channels, sample_rate, has_existing_transcript, chapters}
```

For YouTube URLs (audio-only), the probe additionally tries to pull
auto-captions so the locate step can use a coarse caption summary.

### Step 2 — Locate (agent CoT, no tool call)

```
## Locate
- query intent: <one sentence>
- audio kind (earnings call / podcast / hearing / broadcast / interview): <which>
- structural clue: <duration / chapters / caption summary>
- predicted region(s):
    * t1 = <mm:ss>–<mm:ss> — rationale: <why>
    * t2 = <mm:ss>–<mm:ss> — rationale: <why>
- expected answer form: <number / name / verdict / non-speech-cue>
- transcription mode: speech | nonspeech
```

Heuristics:

| Question pattern | Predicted region |
|---|---|
| *"in the opening remarks"* | 0:00 – 3:00 |
| *"in prepared remarks"* | first 30–50 % |
| *"during the analyst Q&A"* | last 40–60 % |
| *"in the introduction / preamble"* | 0:00 – 1:00 |
| *"at MM:SS"* | exact ± 20 s window |
| *"how does the speaker close"* | last 60 s |
| *"the first time X is mentioned"* | scan first half densely |
| *"which song / what alarm / what tone"* | non-speech mode |

For non-speech questions, you must use `--mode nonspeech` (Step 3).

### Step 3 — Listen (targeted transcription / classification)

**Speech mode (default):**

```bash
python3 SKILL_DIR/scripts/audio_skill.py listen "<URL_or_path>" \
    --from 00:50 --to 01:30
# returns: {window, transcript_text, segments_with_ts}
```

Returns a Whisper transcript of the requested window. Each segment has a
`(t_start, t_end, text)` triple so the answer can be cited precisely.

**Non-speech mode:**

```bash
python3 SKILL_DIR/scripts/audio_skill.py listen "<URL_or_path>" \
    --from 03:40 --to 03:55 --mode nonspeech
# returns: {window, top_labels: [{label, score}, ...]}
```

Runs CLAP-style zero-shot classification against a default label set
(`alarm, music, applause, dog_bark, doorbell, telephone, footsteps,
silence, environment_noise, speech_in_background, instrument, ringing`).
If a custom label set is needed, pass `--labels "label1,label2,..."`.

### Step 4 — Self-reflect

```
## Reflect
- best window: <hh:mm:ss> to <hh:mm:ss>
- extracted answer: <value>
- supporting evidence: "<transcript quote>" OR top non-speech label + score
- did the transcript literally answer the query? <yes/no>
- did the question ask about *the recording itself* or about a public fact?
  (the latter is web-leak — sample again)
- residual uncertainty: <low/medium/high>
```

Common red flags during reflection:

- Transcript contains the answer but no timestamp citation → fail, re-listen
  with `--keep-segments` and quote the segment.
- Confidence is high but the transcript clearly continues across the
  window boundary → expand window by 15 s and re-listen.
- The query asked about a non-speech cue but you only ran speech mode →
  switch to nonspeech mode and re-listen the same window.

### Step 5 — Return

```json
{
  "answer_value": "Cloud Services",
  "evidence_timestamp_start": "00:53",
  "evidence_timestamp_end": "01:02",
  "evidence_quote": "growth was mainly driven by the cloud services segment",
  "confidence": 0.88
}
```

## Iteration Policy

- Iter 1: 1–2 windows of 60 s each at the most-likely region.
- Iter 2 (if iter 1 returns no answer or low confidence): expand windows
  to 120 s and add a 30-second probe at the *other* candidate region.
- Iter 3 (last resort): chunk the entire audio in 90-second non-overlapping
  windows and transcribe the first 4. Stop when one returns a confident
  answer.

Total transcription budget cap per question: **~6 minutes of audio**.
Above that, return best-found-answer with a low-confidence flag.

## Common Pitfalls

1. **Transcribing the whole audio.** Earnings calls are 30–60 minutes.
   Whisper-large on a full call costs ~60–80× more than a targeted 60 s
   window and obscures the agent's reasoning.
2. **Answering from a search snippet about the audio's title.** Most audio
   sources (earnings calls, public hearings, podcasts) are indexed —
   Google often returns the answer in a press release / transcript site.
   The PLR trace flags this as `web_leak`. Always invoke `listen` and
   cite a real transcript segment.
3. **Skipping non-speech mode for non-speech questions.** Whisper on a
   pure music or alarm clip returns either silence or a hallucination.
   Use `--mode nonspeech` for those.
4. **Forgetting to expand at boundaries.** If the predicted window is
   00:50–01:30 and the answer phrase begins at 01:29, Whisper may cut
   mid-word. Always re-listen with `--from <X-10>` if the chosen segment
   abuts the window edge.
5. **Trusting Whisper hallucinations on silent / music-only sections.**
   When Whisper returns generic boilerplate (*"Thanks for watching"*)
   on a region you know is not English speech, treat it as no-evidence
   and switch to non-speech mode.

## Verification Checklist

- [ ] Probe was called and its output cited in Locate.
- [ ] Locate block listed at least one timestamp window with a rationale.
- [ ] Listen step ran in the correct mode (speech vs nonspeech).
- [ ] Reflect block confirms the evidence is from the transcribed window,
      not from the title / metadata / web search.
- [ ] Final answer includes both `evidence_timestamp_start` and an
      `evidence_quote` (speech mode) or `top_label` (nonspeech mode).

## One-Shot Recipe — Earnings Call Opening

> *"In Snowflake's latest earnings call, what YoY revenue growth did the
> CFO announce in the opening remarks?"*

```
1. probe URL → duration = 51:30
2. Locate: "opening remarks" → 0:00–3:00
3. listen URL --from 00:00 --to 03:00
4. transcript shows: "[02:14] Revenue grew 28% year over year ..."
5. Reflect: literal answer, in window, confidence 0.90
6. return {"answer_value": "28%", "evidence_timestamp_start": "02:14", ...}
```

## One-Shot Recipe — Non-Speech Music Cue

> *"In this audio recording 'KPAY 1290 AM ... March 01 2017 09:00PM PST',
> what is the song that plays at 32:10?"*

```
1. probe URL → duration = 60:00, captions=none
2. Locate: exact ts → window 32:00–32:25, mode=nonspeech
3. listen URL --from 32:00 --to 32:25 --mode nonspeech --labels "song:<...>,music,jingle,advertisement,silence"
4. classifier returns top label: "music" (0.92)
5. switch to speech mode for the same window to look for a DJ announcement
6. listen URL --from 31:30 --to 32:30 (speech mode)
7. transcript: "[31:45] up next, Hymn for the Weekend by Coldplay..."
8. Reflect: confidence 0.88
9. return {"answer_value": "Hymn for the Weekend", "evidence_timestamp_start": "31:45", ...}
```
