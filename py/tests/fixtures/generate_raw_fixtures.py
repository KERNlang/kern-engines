"""Generate SYNTHESIZED raw-PTY-byte golden fixtures for the Claude scraper.

WHY SYNTHESIZED (not live-captured): the Claude CLI binary IS present in the
build environment, but it can only be exercised live under an interactive TTY,
which (a) is unavailable to the automated harness this runs in (``tty`` reports
"not a tty"), and (b) would incur real subscription billing per dispatch and
depends on a model actually replying -- not a deterministic, replayable golden.
So instead of pinning post-ANSI-strip strings (what tests/test_extract_response.py
already does), these fixtures emit the ACTUAL raw bytes the pty would deliver --
real ESC/CSI cursor-movement, spinner dingbats, full-width box dividers, and
redraw frames -- one fixture per byte SHAPE the parser must survive. Replaying
them through ``strip_ansi_bytes`` + ``extract_response`` exercises the whole
pipeline end-to-end (the byte plumbing the string fixtures skip), so a future
parser change that mishandles a real movement-CSI or spinner shape shows up as
a failing replay here.

Each fixture filename ends in ``.synth.raw`` to make the synthesized origin
obvious on disk; the matching ``.synth.expected`` holds the clean transcript
the parser must return. The byte shapes below are reconstructed from the live
captures documented in ``pty_session.py`` (the comments next to each regex) and
in ``tests/test_extract_response.py`` (the 2026-05-29 claude TUI v2.1.156
captures), so they faithfully reproduce real wire shapes even though the bytes
were assembled here rather than recorded off a socket.

Run ``python3 tests/fixtures/generate_raw_fixtures.py`` from ``py/`` to (re)write
the fixtures. ``tests/test_raw_byte_replay.py`` reads them and asserts the parse.
"""

from __future__ import annotations

from pathlib import Path

# -- raw-byte building blocks (real terminal control sequences) --------------

ESC = b"\x1b"
CSI = ESC + b"["


def cup(row: int, col: int) -> bytes:
    """Cursor-position move ESC[<row>;<col>H -- the movement CSI the TUI uses to
    wrap a long line across rows (NOT a literal newline). strip_ansi_bytes turns
    each into a single space so wrapped words don't fuse together."""
    return CSI + f"{row};{col}H".encode()


ERASE_LINE = CSI + b"K"
ERASE_DISPLAY = CSI + b"2J"
HIDE_CURSOR = CSI + b"?25l"
SHOW_CURSOR = CSI + b"?25h"
SGR_RESET = CSI + b"0m"
SGR_BOLD = CSI + b"1m"

MARKER = "⏺".encode()            # claude response marker (black circle for record)
DIV = ("─" * 160).encode()      # full-width box divider U+2500 -> crop boundary
ARROW = "❯".encode()            # input-bar prompt arrow U+276F
ELLIP = "…".encode()            # spinner-label trailing ellipsis
MIDDOT = "·".encode()
DOWN_ARR = "↓".encode()
UP_ARR = "↑".encode()
LEFT_ARR = "←".encode()
HIGH_DOT = "●".encode()
SPIN = ["✶".encode(), "✽".encode(), "✷".encode(), "✻".encode()]


def _frame(*parts: bytes) -> bytes:
    return b"".join(parts)


# -- one fixture per byte SHAPE the parser targets ---------------------------


def shape_movement_csi_wrap():
    """SHAPE: movement-CSI -> space. A long answer the TUI wraps across rows via
    cursor-position CSIs (ESC[r;cH) instead of newlines. Stripping movement CSIs
    to empty would fuse words ("loopcondition causesreading"); the parser must
    substitute a single space so the sentence stays readable."""
    raw = _frame(
        HIDE_CURSOR, SGR_BOLD,
        MARKER, b" Off-by-one in loop",
        cup(7, 1), b"condition causes",
        cup(8, 1), b"reading past the end",
        SGR_RESET,
        cup(10, 1), DIV, b"\r\n",
        b"  ", SPIN[3], b" Worked for 1s  ", ARROW, b"  ? for shortcuts",
        SHOW_CURSOR,
    )
    return raw, "Off-by-one in loop condition causes reading past the end"


def shape_spinner_glyph_same_row():
    """SHAPE: _SPINNER_GLYPH line cut. Spinner painted to the RIGHT of the reply
    on the SAME row; after movement->space merge the line is
    "PONG  <spin> Channelling... (1s ...)". Cut at the first spinner glyph,
    keep "PONG"."""
    raw = _frame(
        HIDE_CURSOR,
        MARKER, b" PONG", cup(5, 12), SPIN[1],
        b" Channelling", ELLIP, b" (1s ", MIDDOT, b" ", DOWN_ARR, b" 1 tokens)    ", ARROW, b"   ",
        b"\r\n", DIV, b"\r\n",
        b" esc to interrupt ", HIGH_DOT, b" high ", MIDDOT, b" /effort\r\n",
        SHOW_CURSOR,
    )
    return raw, "PONG"


def shape_divider_crop():
    """SHAPE: divider crop / _crop_to_transcript. A full-width U+2500 divider
    separates the transcript from the bottom chrome (status line + input bar).
    Every byte past the first 8+ box-char run is chrome and must be dropped."""
    raw = _frame(
        MARKER, b" The answer is 42.\r\n",
        DIV, b"\r\n",
        b"  ", SPIN[0], b" Crunched for 2s  ", ARROW, b"  ? for shortcuts ", MIDDOT, b" ", LEFT_ARR, b" for agents\r\n",
        b" esc to interrupt\r\n",
    )
    return raw, "The answer is 42."


def shape_brace_balanced_json_segments():
    """SHAPE: brace-counting / segmented JSON. Claude streams a JSON block in
    segments with a redraw between; the final settled bytes carry one balanced
    object. The parser must return the whole object intact, not a mid-segment
    truncation."""
    raw = _frame(
        MARKER, b' {"status":"ok",', cup(6, 1), SPIN[2], b" Distilling", ELLIP, b" (1s)", ERASE_LINE, b"\r\n",
        ERASE_LINE, MARKER, b' {"status":"ok","n":3,"items":["a","b"]}  ', SPIN[1], b" Distilling", ELLIP, b" (2s)  ", ARROW,
        b"\r\n", DIV, b"\r\n",
        b"  ", SPIN[3], b" Worked for 2s  ", ARROW, b"  ? for shortcuts\r\n",
    )
    return raw, '{"status":"ok","n":3,"items":["a","b"]}'


def shape_chrome_verb_drift():
    """SHAPE: chrome_regex drift family "<verb> for <n>s". A completion status
    line using a verb that was NEVER in the hand-maintained blocklist (the drift
    that caused the original miss). The generic rule must still drop it."""
    raw = _frame(
        MARKER, b" Blue\r\n",
        DIV, b"\r\n",
        b"  ", SPIN[2], b" Frobnicated for 7s  ", ARROW, b"  ? for shortcuts\r\n",
        b"  ", SPIN[0], b" Quuxified for 3s  ", ARROW, b"\r\n",
    )
    return raw, "Blue"


def shape_redraw_dedupe():
    """SHAPE: exact-line redraw dedupe. The TUI re-renders the SAME response
    segment once per spinner tick, emitting identical bytes each frame. Collapse
    the duplicates so the finding appears exactly once."""
    finding = b"- src/api/users.ts: divide() does not guard b===0"
    frames = []
    for i in range(4):
        frames += [
            ERASE_LINE, MARKER, b" ", finding, b"  ", SPIN[i % len(SPIN)],
            b" Pondering", ELLIP, b" (", str(i + 1).encode(), b"s)", b"\r\n",
        ]
    raw = _frame(*frames, DIV, b"\r\n", b"  ", SPIN[3], b" Worked for 4s  ", ARROW, b"\r\n")
    return raw, "- src/api/users.ts: divide() does not guard b===0"


def shape_personal_statusline_glyphs():
    """SHAPE: personal statusline / box + glyph chrome. The user's animated
    ~/.claude statusLine (context gauge + plugin glyphs) renders at the very
    bottom, past the divider; none of it is answer text and it must be dropped."""
    gauge = "| 🔮 [█████████░] 96% | 🛡️ 📖3 ✏️1 ✅".encode()
    raw = _frame(
        MARKER, b" The answer is 42.  ", SPIN[0], b" Pollinating", ELLIP, b" (2s ", MIDDOT, b" ", UP_ARR, b" 3 tokens)  ", ARROW,
        b"\r\n", DIV, b"\r\n",
        b"  ", SPIN[3], b" Crunched for 2s  ", ARROW, b"  ? for shortcuts ", MIDDOT, b" ", LEFT_ARR, b" for agents\r\n",
        gauge, b"\r\n",
    )
    return raw, "The answer is 42."


def shape_input_bar_arrow_merge():
    """SHAPE: input-bar arrow merged onto the answer row. The U+276F prompt arrow
    is painted onto the reply's row via a movement CSI; after merge the line is
    "Yellow <arrow> ? for shortcuts". Cut at the arrow, keep "Yellow"."""
    raw = _frame(
        MARKER, b" Yellow", cup(5, 40), ARROW, b" ? for shortcuts ", MIDDOT, b" ", LEFT_ARR, b" for agents",
        b"\r\n", DIV, b"\r\n",
        b"  ", SPIN[3], b" Worked for 1s  ", ARROW, b"\r\n",
    )
    return raw, "Yellow"


SHAPES = {
    "01_movement_csi_wrap": shape_movement_csi_wrap,
    "02_spinner_glyph_same_row": shape_spinner_glyph_same_row,
    "03_divider_crop": shape_divider_crop,
    "04_brace_balanced_json_segments": shape_brace_balanced_json_segments,
    "05_chrome_verb_drift": shape_chrome_verb_drift,
    "06_redraw_dedupe": shape_redraw_dedupe,
    "07_personal_statusline_glyphs": shape_personal_statusline_glyphs,
    "08_input_bar_arrow_merge": shape_input_bar_arrow_merge,
}


def fixtures_dir() -> Path:
    return Path(__file__).resolve().parent


def write_all() -> None:
    d = fixtures_dir()
    for name, fn in SHAPES.items():
        raw, expected = fn()
        (d / f"{name}.synth.raw").write_bytes(raw)
        (d / f"{name}.synth.expected").write_text(expected, encoding="utf-8")
        print(f"wrote {name}.synth.raw ({len(raw)}B) + .expected -> {expected!r}")


if __name__ == "__main__":
    write_all()
