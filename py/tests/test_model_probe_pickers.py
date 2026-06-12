"""Unit tests for the per-engine /model picker parsers in model_probe.

The claude fixture is a REAL captured screen (ANSI-stripped pty scrape,
including the row-fusion garbling pty captures suffer), taken 2026-06-12 from
claude with the Fable-era picker — the regression where the ✔(current) sat on
a "Fable 5" row the brand regex didn't know, so the row and the current marker
both vanished.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kern_engines.cli.model_probe import parse_claude_picker  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def test_claude_fable_picker_marks_current() -> None:
    parsed = parse_claude_picker(_load("claude_model_picker_fable.txt"))
    ids = [m["id"] for m in parsed["models"]]
    assert ids == ["opus", "fable", "sonnet", "sonnet[1m]", "haiku"]
    current = [m for m in parsed["models"] if m["current"]]
    assert len(current) == 1
    assert current[0]["id"] == "fable"
    assert current[0]["name"] == "Fable 5"
    assert parsed["current"] == "Fable 5"


def test_claude_pre_fable_picker_still_parses() -> None:
    # Synthetic pre-Fable screen (the shape the parser was written against):
    # ✔ on the Sonnet row, no Fable family present.
    screen = (
        "Select model  Switch between Claude models.  "
        " 1. Default (recommended)  Opus 4.8 · Best for everyday tasks  "
        " 2. Sonnet ✔ Sonnet 4.6 · Efficient for routine tasks  "
        " 3. Sonnet (1M context)  Sonnet 4.6 with 1M context · Draws from usage credits  "
        " 4. Haiku  Haiku 4.5 · Fastest for quick answers  "
        " Enter to confirm · Esc to cancel"
    )
    parsed = parse_claude_picker(screen)
    ids = [m["id"] for m in parsed["models"]]
    assert ids == ["opus", "sonnet", "sonnet[1m]", "haiku"]
    assert parsed["current"] == "Sonnet 4.6"
    assert [m["id"] for m in parsed["models"] if m["current"]] == ["sonnet"]


def test_claude_picker_anchors_on_last_select_model() -> None:
    # The slash-command autocomplete also paints "Select model" text; the
    # parser must anchor on the LAST occurrence (the actual picker).
    noise = "/model Select model and reasoning effort  "
    screen = noise + _load("claude_model_picker_fable.txt")
    parsed = parse_claude_picker(screen)
    assert parsed["current"] == "Fable 5"
    assert len(parsed["models"]) == 5
