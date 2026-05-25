#!/usr/bin/env python3
"""
video_skill.py — Companion tool for the `video-qa-targeted` SKILL.

Three subcommands:

  probe   : cheap structural inspection of a video (duration, fps, captions).
            Returns JSON the agent reads before deciding where to watch.

  sample  : extract a small set of frames + a caption window at predicted
            timestamps. Frames are written to /tmp/vqa/<runid>/ as JPGs.

  caption : extract just the caption/subtitle text for a [start, end] window.

The agent does the CoT (locate, analyze, reflect) outside this script.

Dependencies:
    yt-dlp, ffmpeg on PATH, pillow (for resize)

Examples:
    python3 video_skill.py probe https://youtu.be/xxxx
    python3 video_skill.py sample https://youtu.be/xxxx --timestamps 00:53,02:10 --window 4 --fps 1
    python3 video_skill.py caption https://youtu.be/xxxx --from 00:50 --to 01:00
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

DEFAULT_FRAME_DIR = Path(tempfile.gettempdir()) / "vqa"


def _which_or_die(cmd: str):
    if shutil.which(cmd) is None:
        sys.exit(f"[video_skill] required binary not on PATH: {cmd}")


def _parse_ts(s: str) -> float:
    """Accept 'mm:ss', 'hh:mm:ss', or seconds as float."""
    s = str(s).strip()
    if ':' in s:
        parts = list(map(float, s.split(':')))
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


def _download_video(url_or_path: str, workdir: Path) -> Path:
    """If `url_or_path` is a URL, fetch with yt-dlp; else return the path."""
    p = Path(url_or_path)
    if p.exists():
        return p.resolve()
    _which_or_die("yt-dlp")
    out_tmpl = str(workdir / "src.%(ext)s")
    cmd = ["yt-dlp", "-f", "best[ext=mp4]/best",
           "--no-progress", "--quiet", "-o", out_tmpl, url_or_path]
    subprocess.run(cmd, check=True)
    # find the produced file
    for fn in workdir.iterdir():
        if fn.name.startswith("src."):
            return fn
    sys.exit("[video_skill] yt-dlp succeeded but produced no file?")


def _try_download_subs(url: str, workdir: Path) -> Path | None:
    """Try to grab auto-captions or manual subs. Returns path or None."""
    try:
        out_tmpl = str(workdir / "caps.%(ext)s")
        subprocess.run(
            ["yt-dlp", "--skip-download",
             "--write-auto-subs", "--write-subs",
             "--sub-lang", "en.*",
             "--convert-subs", "srt",
             "--no-progress", "--quiet",
             "-o", out_tmpl, url],
            check=False)
        for fn in workdir.iterdir():
            if fn.suffix == ".srt":
                return fn
    except Exception:
        return None
    return None


def _parse_srt(srt_path: Path) -> list[tuple[float, float, str]]:
    """Returns [(start_sec, end_sec, text), ...] from an SRT file."""
    if not srt_path.exists():
        return []
    text = srt_path.read_text(encoding="utf-8", errors="ignore")
    entries = []
    blocks = re.split(r"\n\s*\n", text.strip())
    ts_re = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")
    for blk in blocks:
        lines = blk.strip().splitlines()
        if not lines: continue
        # find first line with timestamps
        for i, ln in enumerate(lines):
            m = ts_re.search(ln)
            if m:
                h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
                t1 = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
                t2 = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
                txt = " ".join(lines[i + 1:]).strip()
                if txt:
                    entries.append((t1, t2, txt))
                break
    return entries


def _ffprobe_duration(media_path: Path) -> float:
    _which_or_die("ffprobe")
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)],
        text=True)
    return float(out.strip())


def _ffprobe_fps(media_path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate",
         "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)],
        text=True).strip()
    try:
        if "/" in out:
            a, b = out.split("/")
            return float(a) / float(b) if float(b) else 0.0
        return float(out)
    except Exception:
        return 0.0


def _condense_captions(entries: list[tuple[float, float, str]], max_chars: int = 1600) -> str:
    """Tiny summary of captions for the *locate* step. NOT used as answer source."""
    if not entries:
        return ""
    # naive: take 1 line every ~30 s
    last_t = -999
    chunks = []
    for t, _, txt in entries:
        if t - last_t >= 25.0:
            chunks.append(f"[{_fmt_ts(t)}] {txt}")
            last_t = t
        if sum(len(c) for c in chunks) > max_chars:
            break
    return "\n".join(chunks)


def _caption_window(entries, start_sec, end_sec, max_chars=600):
    out = []
    for t1, t2, txt in entries:
        if t2 < start_sec or t1 > end_sec:
            continue
        out.append(f"[{_fmt_ts(t1)}] {txt}")
    s = "\n".join(out)
    return s if len(s) <= max_chars else s[:max_chars] + "…"


def cmd_probe(args):
    runid = uuid.uuid4().hex[:8]
    workdir = DEFAULT_FRAME_DIR / runid
    workdir.mkdir(parents=True, exist_ok=True)
    video_path = _download_video(args.url_or_path, workdir)
    duration = _ffprobe_duration(video_path)
    fps = _ffprobe_fps(video_path)

    captions = []
    if not Path(args.url_or_path).exists():
        srt = _try_download_subs(args.url_or_path, workdir)
        if srt: captions = _parse_srt(srt)

    out = {
        "video_path_cached": str(video_path),
        "runid": runid,
        "duration_sec": round(duration, 2),
        "duration_hms": _fmt_ts(duration),
        "fps": round(fps, 3),
        "has_captions": bool(captions),
        "captions_summary": _condense_captions(captions),
        "n_caption_segments": len(captions),
    }
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    print()


def _extract_frame(video_path: Path, ts_sec: float, out_path: Path, max_dim: int = 1280):
    """Extract one frame at ts_sec, optionally resize to max_dim."""
    cmd = [
        "ffmpeg", "-loglevel", "error", "-y",
        "-ss", str(ts_sec), "-i", str(video_path),
        "-frames:v", "1",
        "-vf", f"scale='if(gt(iw,ih),min({max_dim},iw),-1)':'if(gt(iw,ih),-1,min({max_dim},ih))'",
        "-q:v", "3",
        str(out_path),
    ]
    subprocess.run(cmd, check=False)


def cmd_sample(args):
    runid = args.runid or uuid.uuid4().hex[:8]
    workdir = DEFAULT_FRAME_DIR / runid
    workdir.mkdir(parents=True, exist_ok=True)

    # locate video (re-uses cache if probe was done with this runid)
    cached = workdir / "src.mp4"
    if not cached.exists():
        cached = _download_video(args.url_or_path, workdir)

    # captions
    captions = []
    if not Path(args.url_or_path).exists():
        srt_candidates = list(workdir.glob("*.srt"))
        if srt_candidates:
            captions = _parse_srt(srt_candidates[0])
        else:
            srt = _try_download_subs(args.url_or_path, workdir)
            if srt: captions = _parse_srt(srt)

    timestamps = [_parse_ts(t) for t in args.timestamps.split(",")]
    window = float(args.window)
    fps = float(args.fps)
    max_frames = int(args.max_frames)

    out = {"runid": runid, "windows": []}
    for ts in timestamps:
        start = max(0.0, ts - window / 2)
        end = ts + window / 2
        # how many frames inside the window
        n = max(1, min(max_frames, int(window * fps)))
        if n == 1:
            samples = [ts]
        else:
            step = (end - start) / (n - 1)
            samples = [start + i * step for i in range(n)]

        frames = []
        for i, s in enumerate(samples):
            fp = workdir / f"frame_{int(ts // 60):02d}m{int(ts % 60):02d}s_{i}.jpg"
            _extract_frame(cached, s, fp)
            if fp.exists():
                frames.append(str(fp))

        cap = _caption_window(captions, start, end) if captions else ""
        out["windows"].append({
            "ts": _fmt_ts(ts),
            "ts_sec": round(ts, 2),
            "window_sec": window,
            "n_frames": len(frames),
            "frames": frames,
            "caption_window": cap,
        })

    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    print()


def cmd_caption(args):
    """Just dump caption text in a specific window. No frame extraction."""
    runid = args.runid or uuid.uuid4().hex[:8]
    workdir = DEFAULT_FRAME_DIR / runid
    workdir.mkdir(parents=True, exist_ok=True)
    captions = []
    if not Path(args.url_or_path).exists():
        srt = list(workdir.glob("*.srt"))
        if srt:
            captions = _parse_srt(srt[0])
        else:
            s = _try_download_subs(args.url_or_path, workdir)
            if s: captions = _parse_srt(s)
    start_sec = _parse_ts(getattr(args, "from"))
    end_sec = _parse_ts(args.to)
    txt = _caption_window(captions, start_sec, end_sec)
    json.dump({"from": _fmt_ts(start_sec), "to": _fmt_ts(end_sec),
               "caption": txt}, sys.stdout, indent=2, ensure_ascii=False)
    print()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("probe", help="extract structural signals")
    pp.add_argument("url_or_path")
    pp.set_defaults(func=cmd_probe)

    sp = sub.add_parser("sample", help="extract frames + captions at timestamps")
    sp.add_argument("url_or_path")
    sp.add_argument("--timestamps", required=True,
                    help="comma-separated, mm:ss or seconds, e.g. 00:53,02:10,04:35")
    sp.add_argument("--window", default=4.0, type=float,
                    help="seconds around each timestamp (default 4)")
    sp.add_argument("--fps", default=1.0, type=float,
                    help="frame sample rate inside window (default 1)")
    sp.add_argument("--max-frames", default=6, type=int,
                    help="cap on frames per window (default 6)")
    sp.add_argument("--runid", default=None,
                    help="reuse a probe runid to avoid re-downloading")
    sp.set_defaults(func=cmd_sample)

    cp = sub.add_parser("caption", help="dump captions for a [from,to] window")
    cp.add_argument("url_or_path")
    cp.add_argument("--from", dest="from", required=True, help="start mm:ss")
    cp.add_argument("--to", required=True, help="end mm:ss")
    cp.add_argument("--runid", default=None)
    cp.set_defaults(func=cmd_caption)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
