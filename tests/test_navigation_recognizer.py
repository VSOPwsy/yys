"""ScreenRecognizer: callable recognizer, Button coercion, ambiguity logging."""

from __future__ import annotations

import logging

import numpy as np

from core.navigation import GameGraph
from core.navigation.recognizer import ScreenRecognizer
from core.vision.template_matcher import TemplateMatcher


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


def test_two_arg_callable_receives_matcher():
    """Composite recognizers can accept (screenshot, matcher) so they don't
    need to closure-capture a matcher at graph-build time."""
    received: list = []

    def rec_with_matcher(shot, matcher):
        received.append(matcher)
        return True

    g = GameGraph()
    g.add_vertex("a", recognizer=rec_with_matcher)
    custom_matcher = TemplateMatcher()
    rec = ScreenRecognizer(matcher=custom_matcher)
    assert rec.detect_current(np.zeros((4, 4, 3), dtype=np.uint8), g) == "a"
    assert received == [custom_matcher]


def test_one_arg_callable_still_works():
    """Existing 1-arg callable convention must remain backward compatible."""
    def rec_one_arg(shot):
        return shot.sum() == 0

    g = GameGraph()
    g.add_vertex("a", recognizer=rec_one_arg)
    rec = ScreenRecognizer()
    assert rec.detect_current(np.zeros((4, 4, 3), dtype=np.uint8), g) == "a"
    assert rec.detect_current(np.ones((4, 4, 3), dtype=np.uint8), g) is None


def test_two_arg_callable_default_second_arg_falls_back_to_one_arg():
    """A second positional arg with a default value should NOT trigger the
    2-arg path — only required positional args count, so authors can keep
    a single-arg convention even when their function has optional knobs."""
    calls: list = []

    def rec_with_default(shot, debug=False):
        calls.append((shot.shape, debug))
        return True

    g = GameGraph()
    g.add_vertex("a", recognizer=rec_with_default)
    rec = ScreenRecognizer()
    assert rec.detect_current(np.zeros((4, 4, 3), dtype=np.uint8), g) == "a"
    # Called with 1 arg, debug stayed at its default False.
    assert calls == [((4, 4, 3), False)]
