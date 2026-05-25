#!/usr/bin/env python3
"""
audio_skill.py — Companion tool for the `audio-qa-targeted` SKILL.

Subcommands:

  probe   : structural inspection of an audio (or audio-only YouTube) source.
            Returns JSON: duration, sample_rate, channels, captions_summary.

  listen  : targeted transcription of a specific [from, to] window.
            Default mode 'speech' (Whisper); also supports 'nonspeech'
            zero-shot tagging of acoustic events.

Why a separate `listen` instead of a generic `transcribe-all`?
This script is intentionally targeted — see SKILL.md, Common Pitfalls #1.

Dependencies:
    yt-dlp, ffmpeg on PATH.
    For speech mode: OPENAI_API_KEY (whisper-1) OR a local whisper.cpp binary
    pointed to by env WHISPER_BIN + WHISPER_MODEL.
    For nonspeech mode: openai (used as a generic zero-shot acoustic
    classifier through a small CLAP-style prompt fallback; replace with a
    proper CLAP / PANNs binding when available).

Examples:
    python3 audio_skill.py probe https://archive.org/download/.../foo.mp3
    python3 audio_skill.py listen file.mp3 --from 00:50 --to 01:30
    python3 audio_skill.py listen file.mp3 --from 32:00 --to 32:25 --mode nonspeech
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from pathlib import Path

DEFAULT_DIR = Path(tempfile.gettempdir()) / "aqa"


def _which_or_die(cmd: str):
    if shutil.which(cmd) is None:
        sys.exit(f"[audio_skill] required binary not on PATH: {cmd}")


def _parse_ts(s: str) -> float:
    s = str(s).strip()
    if ":" in s:
        parts = list(map(float, s.split(":")))
        while len(parts) < 3:
            parts.insert(0, 0)
        h, m, sec = parts
        return h * 3600 + m * 60 + sec
    return float(s)


def _fmt_ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _download_audio(url_or_path: str, workdir: Path) -> Path:
    p = Path(url_or_path)
    if p.exists():
        return p.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    # Try direct HTTP first (works for archive.org direct .mp3 links)
    if url_or_path.endswith((".mp3", ".m4a", ".wav", ".ogg", ".flac")):
        local = workdir / ("src" + Path(url_or_path).suffix)
        try:
            urllib.request.urlretrieve(url_or_path, local)
            return local
        except Exception:
            pass
    # Fall back to yt-dlp (covers YouTube audio-only, Bilibili, etc.)
    _which_or_die("yt-dlp")
    out_tmpl = str(workdir / "src.%(ext)s")
    subprocess.run([
        "yt-dlp", "-x", "--audio-format", "mp3", "--no-progress", "--quiet",
        "-o", out_tmpl, url_or_path,
    ], check=True)
    for fn in workdir.iterdir():
        if fn.name.startswith("src."):
            return fn
    sys.exit("[audio_skill] could not obtain audio file")


def _ffprobe(path: Path) -> dict:
    _which_or_die("ffprobe")
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(path),
    ], text=True)
    return json.loads(out)


def _slice_to_wav(src: Path, t0: float, t1: float, dst: Path):
    """Extract [t0, t1] from `src` as a 16-kHz mono wav."""
    _which_or_die("ffmpeg")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(t0), "-to", str(t1),
        "-i", str(src),
        "-ar", "16000", "-ac", "1",
        str(dst),
    ], check=True)


# ────────────────────────── Whisper transcription ──────────────────────────


def _whisper_openai(wav: Path) -> dict:
    """Transcribe a wav using OpenAI Whisper (whisper-1).
    Prefers OPENAI_NATIVE_API_KEY (native OpenAI), then OPENAI_API_KEY.
    Whisper-1 is an OpenAI-native endpoint — OpenRouter does NOT proxy it,
    so the key must be an actual sk- key from platform.openai.com.
    """
    api_key = os.environ.get("OPENAI_NATIVE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {}
    if api_key.startswith("sk-or-"):
        # This is an OpenRouter key, not a native OpenAI key — fail loud.
        print("[audio_skill] OPENAI_API_KEY looks like an OpenRouter key "
              "(starts with sk-or-); Whisper-1 needs a native OpenAI key. "
              "Set OPENAI_NATIVE_API_KEY=sk-... separately.", file=sys.stderr)
        return {}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)  # default base_url = OpenAI native
        with open(wav, "rb") as f:
            r = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        if hasattr(r, "model_dump"):
            return r.model_dump()
        return dict(r)
    except Exception as e:
        print(f"[audio_skill] OpenAI whisper failed: {e}", file=sys.stderr)
        return {}


def _whisper_local(wav: Path) -> dict:
    """Use whisper.cpp binary if env WHISPER_BIN + WHISPER_MODEL are set."""
    bin_path = os.environ.get("WHISPER_BIN")
    model_path = os.environ.get("WHISPER_MODEL")
    if not bin_path or not model_path:
        return {}
    out_dir = wav.parent
    proc = subprocess.run([
        bin_path, "-m", model_path, "-f", str(wav),
        "-of", str(out_dir / "out"), "-oj",
    ], capture_output=True, text=True)
    j = out_dir / "out.json"
    if j.exists():
        return json.loads(j.read_text())
    return {"_stderr": proc.stderr[:400]}


def _transcribe(wav: Path) -> dict:
    # Prefer local whisper.cpp if configured (faster, free)
    local = _whisper_local(wav)
    if local and "segments" in (local or {}):
        return local
    return _whisper_openai(wav)


def _segments_from(transcript: dict) -> list[tuple[float, float, str]]:
    if not transcript:
        return []
    segs = transcript.get("segments") or []
    out = []
    for s in segs:
        t0 = float(s.get("start", s.get("t0", 0)))
        t1 = float(s.get("end", s.get("t1", t0)))
        txt = (s.get("text") or "").strip()
        if txt:
            out.append((t0, t1, txt))
    return out


# ────────────────────────── Non-speech tagging ──────────────────────────


DEFAULT_NS_LABELS = [
    "music", "alarm", "applause", "dog_bark", "doorbell", "telephone_ring",
    "footsteps", "silence", "environment_noise", "speech_in_background",
    "instrument", "ringing", "engine_noise", "wind", "rain", "advertisement",
    "jingle",
]


def _classify_nonspeech_via_audio_model(wav: Path, labels: list[str]) -> list[dict]:
    """
    Zero-shot acoustic classification.
    We use an OpenAI-compatible Audio-LLM (e.g. Qwen2-Audio served via OpenRouter)
    when the env var AUDIO_LLM_MODEL is set. Otherwise we fall back to Whisper
    + simple keyword heuristics on the transcript (clearly weaker but works as
    a baseline).
    """
    model = os.environ.get("AUDIO_LLM_MODEL")  # e.g. "qwen/qwen2-audio-7b"
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    if model and api_key:
        try:
            import base64
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base)
            audio_b64 = base64.b64encode(wav.read_bytes()).decode("ascii")
            prompt = (
                "Listen to this short audio clip and return a JSON list of the "
                "most likely acoustic categories present, each with a score 0..1. "
                f"Candidate labels (you may also propose new ones): {labels}. "
                "Reply with ONLY a JSON array, no prose."
            )
            r = client.chat.completions.create(
                model=model, max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "input_audio", "input_audio": {
                            "data": audio_b64, "format": "wav"}},
                    ],
                }])
            content = r.choices[0].message.content.strip()
            content = content[content.find("["):content.rfind("]") + 1]
            arr = json.loads(content)
            arr.sort(key=lambda x: -float(x.get("score", 0)))
            return arr[:5]
        except Exception as e:
            print(f"[audio_skill] audio-LLM classify failed: {e}", file=sys.stderr)

    # Heuristic fallback via Whisper transcript: if Whisper returns near-empty
    # text on a clip, we assume music / nonspeech; else mark "speech".
    tx = _transcribe(wav)
    text = " ".join(s[2] for s in _segments_from(tx)).lower()
    if len(text) < 12:
        return [{"label": "music_or_silence", "score": 0.4,
                 "note": "Whisper returned <12 chars on clip; assume nonspeech."}]
    return [{"label": "speech_in_background", "score": 0.5,
             "note": "Heuristic fallback; install Qwen2-Audio for real classification."}]


# ────────────────────────── CLI commands ──────────────────────────


def cmd_probe(args):
    runid = uuid.uuid4().hex[:8]
    workdir = DEFAULT_DIR / runid
    workdir.mkdir(parents=True, exist_ok=True)
    src = _download_audio(args.url_or_path, workdir)
    info = _ffprobe(src)
    fmt = info.get("format", {})
    streams = info.get("streams", [])
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    out = {
        "audio_path_cached": str(src),
        "runid": runid,
        "duration_sec": round(float(fmt.get("duration", 0)), 2),
        "duration_hms": _fmt_ts(float(fmt.get("duration", 0))),
        "sample_rate": int(a.get("sample_rate", 0)) if a.get("sample_rate") else None,
        "channels": a.get("channels"),
        "codec_name": a.get("codec_name"),
    }
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    print()


def cmd_listen(args):
    runid = args.runid or uuid.uuid4().hex[:8]
    workdir = DEFAULT_DIR / runid
    workdir.mkdir(parents=True, exist_ok=True)

    # locate / download
    candidates = list(workdir.glob("src.*"))
    if candidates:
        src = candidates[0]
    else:
        src = _download_audio(args.url_or_path, workdir)

    t0 = _parse_ts(getattr(args, "from"))
    t1 = _parse_ts(args.to)
    if t1 <= t0:
        sys.exit("[audio_skill] --to must be greater than --from")

    wav = workdir / f"win_{int(t0):06d}_{int(t1):06d}.wav"
    _slice_to_wav(src, t0, t1, wav)

    if args.mode == "speech":
        tx = _transcribe(wav)
        segs = _segments_from(tx)
        # shift segment timestamps to absolute timeline
        abs_segs = [{
            "t_start": _fmt_ts(t0 + s[0]),
            "t_end": _fmt_ts(t0 + s[1]),
            "text": s[2],
        } for s in segs]
        full_text = " ".join(s[2] for s in segs)
        out = {
            "runid": runid,
            "from": _fmt_ts(t0),
            "to": _fmt_ts(t1),
            "mode": "speech",
            "transcript_text": full_text,
            "segments": abs_segs,
        }
    else:
        labels = args.labels.split(",") if args.labels else DEFAULT_NS_LABELS
        labels = [l.strip() for l in labels if l.strip()]
        top = _classify_nonspeech_via_audio_model(wav, labels)
        out = {
            "runid": runid,
            "from": _fmt_ts(t0),
            "to": _fmt_ts(t1),
            "mode": "nonspeech",
            "top_labels": top,
        }

    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    print()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("probe", help="structural inspection")
    pp.add_argument("url_or_path")
    pp.set_defaults(func=cmd_probe)

    lp = sub.add_parser("listen", help="targeted transcription / classification")
    lp.add_argument("url_or_path")
    lp.add_argument("--from", dest="from", required=True, help="start mm:ss")
    lp.add_argument("--to", required=True, help="end mm:ss")
    lp.add_argument("--mode", choices=["speech", "nonspeech"], default="speech")
    lp.add_argument("--labels", default=None,
                    help="comma-separated labels for nonspeech mode")
    lp.add_argument("--runid", default=None,
                    help="reuse a probe runid to avoid re-downloading")
    lp.set_defaults(func=cmd_listen)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
