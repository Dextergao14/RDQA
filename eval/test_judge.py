#!/usr/bin/env python3
"""Unit tests for eval/judge.py exact_match (no API key, no network).

Run: python3 eval/test_judge.py
The judge imports openai at module level, so it is stubbed here before
importing judge — exact_match itself never touches the API.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_stub = types.ModuleType("openai")


class _OpenAI:  # pragma: no cover - stub only
    def __init__(self, *args, **kwargs):
        pass


_stub.OpenAI = _OpenAI
sys.modules.setdefault("openai", _stub)

import judge  # noqa: E402


# (prediction, variants, expected) — False cases go to the LLM judge.
CASES = [
    # Word-boundary matching: short answers must not match inside words.
    ("I could not find it", ["C"], False),
    ("I could not find it", ["No"], False),
    ("The answer is C.", ["C"], True),
    ("no, it was not", ["No"], True),
    ("FY 2025", ["Fiscal Year 2025", "FY 2025"], True),
    ("2025", ["20251"], False),
    ("U.S. Army", ["us army"], True),
    ("The source is studio.blender.org", ["studio.blender.org"], True),
    # This one no longer exact-matches: under the spaced normalization only
    # full-string equality is allowed, and the delete-normalization glues
    # "Pan/Tilt/Zoom" into one token. It falls through to the LLM judge,
    # which accepts it (the judge prompt counts containing the ground
    # truth as true) — the same category as plurals and abbreviations.
    ("Panasonic AW-RP150 Pan Tilt Zoom controller", ["Pan/Tilt/Zoom"], False),
    ("The price is \u20b11,200", ["1200"], True),
    ("\u20b1500", ["500 pesos"], True),
    ("dresses", ["dress"], False),
    ("pastas", ["pasta"], False),
    ("Teleport", ["teleporters"], False),
    ("", ["C"], False),
    ("100-22-10-396", ["100-22-10-396"], True),
    # Spaced normalization must not let a fragment match a
    # punctuation-joined answer: only full-string equality there.
    ("1", ["1,200"], False),
    ("200", ["1,200"], False),
    ("2", ["2.5"], False),
    ("14", ["3.14"], False),
    ("2025", ["2025-2026"], False),
    ("U", ["U.S."], False),
    ("D", ["Ph.D."], False),
    ("e", ["e.g."], False),
    ("studio", ["studio.blender.org"], False),
    ("org", ["studio.blender.org"], False),
    ("Pan", ["Pan/Tilt/Zoom"], False),
    ("and", ["and/or"], False),
    ("well", ["well-known"], False),
    ("user", ["user_name"], False),
    ("123", ["AB-123"], False),
    ("t", ["don't"], False),
    ("s", ["dog's"], False),
    ("F", ["90\u00b0F"], False),
    # Positive controls for spaced equality (must still match).
    ("studio.blender.org", ["studio blender org"], True),
    ("studio blender org", ["studio.blender.org"], True),
    ("Pan/Tilt/Zoom", ["pan tilt zoom"], True),
    ("1,200", ["1200"], True),
]


def main() -> int:
    failures = []
    for i, (pred, variants, expected) in enumerate(CASES, 1):
        got = judge.exact_match(pred, variants)
        if got != expected:
            failures.append((i, pred, variants, expected, got))
    for i, pred, variants, expected, got in failures:
        print(f"FAIL #{i}: exact_match({pred!r}, {variants!r}) "
              f"= {got}, expected {expected}")
    print(f"{len(CASES) - len(failures)}/{len(CASES)} exact_match tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
