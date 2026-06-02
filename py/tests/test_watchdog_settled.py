"""Direct unit cover for the single watchdog gate ``_watchdog_settled``.

``test_extract_response.py`` / ``test_raw_byte_replay.py`` pin the *read* half
of the one watchdog gate (``extract_response`` / ``_settled_frame`` -- what region
to take once settled). This file pins the *timing* half: ``_watchdog_settled`` --
WHEN the stream is judged settled enough to extract. That decision is escalated,
not flat, and the three branches each carry a different idle multiplier:

  (a) response marker NOT yet in the buffer  -> hold at 4x ``response_idle_ms``
      (claude is likely paused mid-tool-loop; firing early scrapes chrome).
  (b) marker present but the post-marker tail looks structurally incomplete
      (unbalanced ``{``/``[`` or a cliffhanger ``:`` / ``,``)  -> hold at 3x
      (claude streams large replies in bursts, 8+ s between segments).
  (c) marker present and the tail looks complete  -> the normal 1x idle bar.

A regression that flattens the escalation (e.g. drops the 4x pre-marker hold and
starts emitting chrome scraps, or stops waiting for balanced JSON) surfaces HERE
as a failing assertion rather than as a silent garbage dispatch in prod.

Run: ``python3 -m pytest tests -q`` from ``kern_engines/py``.
"""

from __future__ import annotations

from kern_engines.cli.configs import CLAUDE
from kern_engines.cli.pty_session import _looks_incomplete, _watchdog_settled

# The CLAUDE exec-mode idle base the gate multiplies against. Pin the test math
# to the real config value so a config change that moves the base is caught too.
_IDLE = CLAUDE.response_idle_ms  # 2000ms as shipped
_MARKER = CLAUDE.response_marker  # the response glyph


def _settled(buf: str, idle_ms: float) -> bool:
    return _watchdog_settled(buf, idle_ms, CLAUDE, _IDLE)


# -- branch (a): no marker in buffer -> 4x hold ------------------------------


def test_no_marker_holds_until_4x_idle():
    # Pre-marker: claude paused mid-tool-loop, only chrome/spinner on screen.
    buf = "  spin Channelling (3s tokens)"
    assert _MARKER not in buf
    # Below and AT the 4x bar -> not settled (must keep waiting).
    assert _settled(buf, _IDLE * 4 - 1) is False
    assert _settled(buf, _IDLE * 4) is False
    # Strictly past the 4x bar -> settled (claude has visibly stopped).
    assert _settled(buf, _IDLE * 4 + 1) is True


def test_no_marker_not_settled_at_lower_multiples():
    # A bare 1x/3x idle must NOT settle a marker-less buffer -- that's the whole
    # point of the elevated pre-marker bar (otherwise we'd extract chrome).
    buf = "spinner only, no reply yet"
    assert _settled(buf, _IDLE) is False
    assert _settled(buf, _IDLE * 3) is False


# -- branch (b): marker + structurally-incomplete tail -> 3x hold ------------


def test_marker_unbalanced_braces_holds_until_3x_idle():
    # Open object, no close -- claude is mid-emit of a JSON block.
    buf = _MARKER + ' {"findings":[' + '{"file":"a.ts"'
    tail = buf[buf.index(_MARKER) + len(_MARKER):]
    assert _looks_incomplete(tail) is True
    assert _settled(buf, _IDLE) is False          # 1x not enough
    assert _settled(buf, _IDLE * 3) is False       # at the bar, still held
    assert _settled(buf, _IDLE * 3 + 1) is True    # past 3x -> settled


def test_marker_cliffhanger_colon_holds_until_3x_idle():
    # Trailing ':' -> claude is about to emit the value. Incomplete.
    buf = _MARKER + ' The result is:'
    tail = buf[buf.index(_MARKER) + len(_MARKER):]
    assert _looks_incomplete(tail) is True
    assert _settled(buf, _IDLE) is False
    assert _settled(buf, _IDLE * 3 + 1) is True


def test_marker_cliffhanger_comma_and_open_bracket_incomplete():
    for cliff in (",", "[", "{", "("):
        buf = _MARKER + " partial" + cliff
        assert _settled(buf, _IDLE) is False, repr(cliff) + " should hold at 1x"
        assert _settled(buf, _IDLE * 3 + 1) is True, repr(cliff) + " should settle past 3x"


# -- branch (c): marker + complete/balanced tail -> 1x idle ------------------


def test_marker_complete_tail_settles_at_1x_idle():
    buf = _MARKER + ' {"status":"ok","n":3}'
    tail = buf[buf.index(_MARKER) + len(_MARKER):]
    assert _looks_incomplete(tail) is False
    assert _settled(buf, _IDLE - 1) is False       # below 1x -> still settling
    assert _settled(buf, _IDLE) is False           # AT the bar (strict >)
    assert _settled(buf, _IDLE + 1) is True        # past 1x -> settled


def test_marker_plain_prose_settles_at_1x_idle():
    # A balanced, non-cliffhanger plain-text reply settles on the normal bar.
    buf = _MARKER + " PONG"
    assert _settled(buf, _IDLE - 1) is False
    assert _settled(buf, _IDLE + 1) is True


def test_complete_tail_does_not_require_3x():
    # Guard the escalation boundary: a complete tail settles strictly between
    # 1x and 3x, proving branch (c) is NOT subject to the 3x incomplete hold.
    buf = _MARKER + " done."
    assert _settled(buf, _IDLE * 2) is True


# -- anchor handling: trailing TUI status must not skew the brace count ------


def test_done_tail_anchor_strips_status_before_completeness_check():
    # A balanced reply followed by the input-bar arrow chrome ("\n<arrow> ..."):
    # the anchor cut must drop the chrome so the brace count stays balanced and
    # the gate settles on the 1x bar (not held at 3x by chrome cliffhangers).
    buf = _MARKER + ' {"ok":true}\n' + "❯ ? for shortcuts"
    assert _settled(buf, _IDLE + 1) is True
    assert _settled(buf, _IDLE - 1) is False
