#!/usr/bin/env python3
"""
pdf_skill.py — Companion tool for the `pdf-qa-targeted` SKILL.

Subcommands:
    probe   : download + ffprobe-equivalent for PDFs (n_pages + page1 preview)
    extract : pdftotext for a specific page list only

Dependencies:
    poppler-utils (pdfinfo, pdftotext) on PATH.

Examples:
    python3 pdf_skill.py probe https://example.com/foo.pdf
    python3 pdf_skill.py extract https://example.com/foo.pdf --pages 1,2,7
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

DEFAULT_DIR = Path(tempfile.gettempdir()) / "pqa"


def _which_or_die(cmd):
    if shutil.which(cmd) is None:
        sys.exit(f"[pdf_skill] required binary not on PATH: {cmd}")


def _download(url_or_path, workdir):
    p = Path(url_or_path)
    if p.exists():
        return p.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    dst = workdir / "src.pdf"
    req = urllib.request.Request(url_or_path,
                                  headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f)
    return dst


def _pdf_npages(pdf_path):
    _which_or_die("pdfinfo")
    out = subprocess.check_output(["pdfinfo", str(pdf_path)],
                                  text=True, errors="ignore")
    for ln in out.splitlines():
        if ln.startswith("Pages:"):
            return int(ln.split(":", 1)[1].strip())
    return 0


def _extract_page(pdf_path, page_n):
    _which_or_die("pdftotext")
    out = subprocess.check_output(
        ["pdftotext", "-layout", "-f", str(page_n), "-l", str(page_n),
         str(pdf_path), "-"],
        text=True, errors="ignore")
    return out.strip()


def cmd_probe(args):
    runid = uuid.uuid4().hex[:8]
    workdir = DEFAULT_DIR / runid
    pdf = _download(args.url_or_path, workdir)
    n_pages = _pdf_npages(pdf)
    page1 = _extract_page(pdf, 1) if n_pages else ""
    out = {
        "runid": runid,
        "pdf_path_cached": str(pdf),
        "n_pages": n_pages,
        "page1_preview": page1[:2000],
    }
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    print()


def cmd_extract(args):
    runid = args.runid or uuid.uuid4().hex[:8]
    workdir = DEFAULT_DIR / runid
    workdir.mkdir(parents=True, exist_ok=True)
    cached = workdir / "src.pdf"
    pdf = cached if cached.exists() else _download(args.url_or_path, workdir)
    pages = [int(x) for x in args.pages.split(",") if x.strip().isdigit()]
    n_pages = _pdf_npages(pdf)
    out_pages = []
    for p in pages:
        if p < 1 or p > n_pages:
            out_pages.append({"page": p, "text": "", "_error": "out of range"})
            continue
        text = _extract_page(pdf, p)
        out_pages.append({"page": p, "text": text[:6000]})
    out = {"runid": runid, "n_pages_total": n_pages, "pages": out_pages}
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    print()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("probe")
    pp.add_argument("url_or_path")
    pp.set_defaults(func=cmd_probe)
    ep = sub.add_parser("extract")
    ep.add_argument("url_or_path")
    ep.add_argument("--pages", required=True, help="comma-separated 1-indexed")
    ep.add_argument("--runid", default=None)
    ep.set_defaults(func=cmd_extract)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
