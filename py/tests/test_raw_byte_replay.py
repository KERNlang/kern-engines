"""Raw-PTY-byte replay cover for the Claude scraper.

Unlike ``test_extract_response.py`` (which pins post-ANSI-strip STRINGS), this
replays the ACTUAL raw bytes a pty would deliver -- real ESC/CSI cursor moves,
spinner dingbats, full-width box dividers, redraw frames -- through the WHOLE
pipeline (``strip_ansi_bytes`` then ``extract_response``). That exercises the
byte-plumbing layer the string fixtures skip, so a regression in movement-CSI
handling, OSC/short-escape stripping, or UTF-8 decode surfaces HERE.

The fixtures under ``tests/fixtures/*.synth.raw`` are SYNTHESIZED (see
``generate_raw_fixtures.py`` for why: the claude binary is present but only
drivable under an interactive TTY, which the build harness lacks and which would
bill real subscription credits). They reproduce one wire SHAPE each, taken from
the live captures documented in ``pty_session.py`` and ``test_extract_response.py``.

Run: ``python3 -m pytest tests -q`` from ``kern_engines/py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kern_engines.cli.configs import CLAUDE
from kern_engines.cli.pty_session import extract_response, strip_ansi_bytes

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _cases():
    raws = sorted(_FIXTURES.glob("*.synth.raw"))
    assert raws, f"no .synth.raw fixtures found under {_FIXTURES}"
    out = []
    for raw_path in raws:
        exp_path = raw_path.with_suffix("").with_suffix(".synth.expected")
        assert exp_path.exists(), f"missing expected for {raw_path.name}"
        out.append(pytest.param(raw_path, exp_path, id=raw_path.stem))
    return out


@pytest.mark.parametrize("raw_path,exp_path", _cases())
def test_raw_byte_replay(raw_path: Path, exp_path: Path):
    raw = raw_path.read_bytes()
    expected = exp_path.read_text(encoding="utf-8")
    stripped = strip_ansi_bytes(raw)
    got = extract_response(stripped, CLAUDE)
    assert got == expected, (
        f"\nfixture : {raw_path.name}"
        f"\nexpected: {expected!r}"
        f"\ngot     : {got!r}"
        f"\nstripped: {stripped!r}"
    )


def test_all_eight_shapes_present():
    # Guard that the full shape matrix is covered -- one fixture per heuristic
    # the parser targets (movement-CSI, spinner-glyph, divider, brace/json,
    # chrome-drift, redraw-dedupe, statusline, input-arrow).
    stems = {p.stem for p in _FIXTURES.glob("*.synth.raw")}
    assert len(stems) == 8, f"expected 8 shape fixtures, found {sorted(stems)}"
