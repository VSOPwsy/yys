"""ScreenRecognizer: callable recognizer, Button coercion, ambiguity logging."""

from __future__ import annotations

import logging

import numpy as np

from core.navigation import GameGraph
from core.navigation.recognizer import ScreenRecognizer


def _no_action(_ctx):  # noqa: ANN001
    pass


def test_callable_recognizer_used_directly():
    g = GameGraph()
    g.add_vertex("a", recognizer=lambda shot: shot.sum() == 0)
    g.add_vertex("b", recognizer=lambda shot: shot.sum() != 0)
    rec = ScreenRecognizer()
    zero = np.zeros((4, 4, 3), dtype=np.uint8)
    nonzero = np.ones((4, 4, 3), dtype=np.uint8)
    assert rec.detect_current(zero, g) == "a"
    assert rec.detect_current(nonzero, g) == "b"


def test_no_match_returns_none():
    g = GameGraph()
    g.add_vertex("a", recognizer=lambda shot: False)
    rec = ScreenRecognizer()
    assert rec.detect_current(np.zeros((4, 4, 3), dtype=np.uint8), g) is None


def test_recognizerless_vertex_is_skipped():
    g = GameGraph()
    g.add_vertex("a", recognizer=None)
    g.add_vertex("b", recognizer=lambda shot: True)
    rec = ScreenRecognizer()
    assert rec.detect_current(np.zeros((4, 4, 3), dtype=np.uint8), g) == "b"


def test_ambiguity_logs_warning(caplog):
    g = GameGraph()
    g.add_vertex("a", recognizer=lambda shot: True)
    g.add_vertex("b", recognizer=lambda shot: True)
    rec = ScreenRecognizer()
    with caplog.at_level(logging.WARNING):
        result = rec.detect_current(np.zeros((4, 4, 3), dtype=np.uint8), g)
    assert result in ("a", "b")
    assert any("ambiguous" in r.message for r in caplog.records)


def test_invalid_recognizer_logs_and_skips(caplog):
    g = GameGraph()
    g.add_vertex("a", recognizer=12345)  # not a Button/str/callable
    g.add_vertex("b", recognizer=lambda shot: True)
    rec = ScreenRecognizer()
    with caplog.at_level(logging.WARNING):
        result = rec.detect_current(np.zeros((4, 4, 3), dtype=np.uint8), g)
    assert result == "b"
    assert any("invalid" in r.message for r in caplog.records)
