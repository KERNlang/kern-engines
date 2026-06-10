"""Cover for the EMPTY-SETTLE GUARD added to ``ask`` / ``ask_stream`` done-detection.

The scraper's done-detection used to be a single test: ``_watchdog_settled`` ->
"the stream has gone idle past the (escalated) watchdog threshold, take the
region." But the watchdog can legitimately report SETTLED on a frame whose
extracted answer is EMPTY:

  - claude is still warming up: only the spinner/"Channelling..." chrome is on
    screen, no response marker yet, and the pre-marker 4x bar has elapsed
    (claude looked "idle" because it paused mid-tool-loop);
  - the response marker is present but everything after it is chrome — a
    full-width divider + the input bar — so ``extract_response`` crops to "".

Old behaviour: ``ask`` returned that empty string as the answer — a SILENT EMPTY
RESPONSE. Downstream (the daemon -> TS wrapper -> agon) that empty string is a
*successful* reply (``ok: true, text: ""``), so the failure was invisible.

The guard composes a second condition onto the settle: ``_watchdog_settled(...)
AND extract_response(...) is non-empty``. A settled-but-empty frame is no longer
"done" — the pump keeps waiting to the hard timeout. The worst case becomes an
HONEST timeout (daemon emits ``ok: false, kind: "timeout"`` -> the TS wrapper
*rejects* -> agon sees an error it can retry/surface), strictly better than a
silently-empty success.

This file pins that composed predicate directly. The guard itself lives inside
the ``ask`` / ``ask_stream`` ``done()`` closures (which need the live PTY buffer
and can't be unit-driven end to end), but its logic is exactly
``settled and bool(extract)`` over the two module-level functions — so we
reconstruct that conjunction here over the real CLAUDE config and assert:

  1. settled-but-empty frame  -> NOT done (guard holds);
  2. content arrives later    -> done, with that content;
  3. a never-content frame stays not-done at every idle bar (-> hard timeout),
  4. and the happy path is unaffected (a content frame settles exactly as the
     bare watchdog would have).

Run: ``python3 -m pytest tests -q`` from ``kern_engines/py``.
"""

from __future__ import annotations

from kern_engines.cli.configs import CLAUDE
from kern_engines.cli.pty_session import extract_response, _watchdog_settled

_IDLE = CLAUDE.response_idle_ms  # 2000ms as shipped
_MARKER = CLAUDE.response_marker  # the response glyph (⏺)
_DIVIDER = "─" * 40  # the full-width transcript/chrome divider claude paints


def _settled(buf: str, idle_ms: float) -> bool:
    return _watchdog_settled(buf, idle_ms, CLAUDE, _IDLE)


def _done(buf: str, idle_ms: float) -> bool:
    """The exact done-predicate the guard installs in ask()/ask_stream():
    the watchdog must settle AND the settled frame must extract to non-empty."""
    return _settled(buf, idle_ms) and bool(extract_response(buf, CLAUDE))


# -- 1. settled-but-empty frames are NOT accepted as done --------------------


def test_no_marker_spinner_settles_watchdog_but_guard_holds():
    # claude warming up: only spinner chrome, no marker. The pre-marker 4x bar
    # has elapsed, so the bare watchdog reports SETTLED — but the frame extracts
    # to nothing. The guard must NOT accept it (old code returned "").
    buf = "  Channelling (3s tokens) esc to interrupt"
    assert _MARKER not in buf
    assert _settled(buf, _IDLE * 4 + 1) is True       # watchdog alone: settled
    assert extract_response(buf, CLAUDE) == ""         # ...but empty
    assert _done(buf, _IDLE * 4 + 1) is False          # guard: still not done


def test_marker_then_only_chrome_settles_watchdog_but_guard_holds():
    # Marker is on screen but everything after it is chrome (divider + input
    # bar) — the answer region crops to "". Watchdog settles on the 1x bar; the
    # guard rejects the empty extract.
    buf = _MARKER + "\n" + _DIVIDER + "\n❯ ? for shortcuts"
    assert _settled(buf, _IDLE + 1) is True
    assert extract_response(buf, CLAUDE) == ""
    assert _done(buf, _IDLE + 1) is False


def test_marker_immediately_followed_by_divider_guard_holds():
    # Marker directly abutting the divider — empty answer region.
    buf = _MARKER + " " + _DIVIDER
    assert _settled(buf, _IDLE + 1) is True
    assert extract_response(buf, CLAUDE) == ""
    assert _done(buf, _IDLE + 1) is False


# -- 2. content arriving later flips the guard to done -----------------------


def test_content_arriving_later_makes_guard_done_with_that_content():
    # Same conversation, two snapshots: before real content (empty region) and
    # after claude prints the reply. The guard holds on the first, fires on the
    # second, and the second's done implies the extracted answer.
    empty = _MARKER + " " + _DIVIDER
    full = _MARKER + " Here is the answer.\n" + _DIVIDER + "\n❯ ? for shortcuts"

    assert _done(empty, _IDLE + 1) is False
    assert _done(full, _IDLE + 1) is True
    assert extract_response(full, CLAUDE) == "Here is the answer."


# -- 3. a frame that NEVER produces content stays not-done (-> hard timeout) --


def test_never_content_frame_is_not_done_at_any_idle_bar():
    # The silent-failure shape (marker + only chrome) must stay not-done no
    # matter how long the stream sits idle — that's what routes the call to the
    # hard timeout (PtySessionTimeout) instead of returning "". We sweep well
    # past every escalation bar (1x / 3x / 4x) to prove the guard, not a timing
    # quirk, is what holds it.
    buf = _MARKER + "\n" + _DIVIDER + "\n❯ ? for shortcuts"
    for mult in (1, 3, 4, 10):
        assert _done(buf, _IDLE * mult + 1) is False, f"{mult}x should not be done"


# -- 4. happy path unchanged: content settles exactly as the bare watchdog ---


def test_happy_path_content_settles_identically_to_bare_watchdog():
    # Once marker + content exist, extract is non-empty, so the guard's extra
    # condition is a no-op: the done-predicate matches the bare watchdog at
    # every idle value. The guard cannot deadlock or delay the happy path.
    for buf in (
        _MARKER + " PONG",
        _MARKER + ' {"status":"ok","n":3}',
        _MARKER + " done.",
    ):
        for idle in (_IDLE - 1, _IDLE, _IDLE + 1, _IDLE * 2, _IDLE * 4 + 1):
            assert _done(buf, idle) == _settled(buf, idle), (repr(buf), idle)
