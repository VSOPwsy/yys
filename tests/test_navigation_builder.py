"""DSL: subgraph() / root_graph() context, vertex(), edge(), external()."""

from __future__ import annotations

import random
from unittest.mock import patch

import pytest

from core.exceptions import GraphValidationError, MatchTimeout
from core.navigation import (
    GameGraph,
    edge,
    external,
    root_graph,
    subgraph,
    vertex,
)
from core.navigation.builder import (
    NavigationContext,
    click_button_with_expand,
)
from core.vision.button import Button


def _no_action(_ctx):  # noqa: ANN001
    pass


# --------------------------------------------------------------------------- #
# Helpers for action-factory tests
# --------------------------------------------------------------------------- #
class _StubBackend:
    """Minimal backend stand-in for testing actions.

    Tracks calls to `find`, `click`, `click_xy` so tests can assert on
    sequence. `find` returns whatever the test sets in `find_returns`
    (a list — popped front to back; empty defaults to None).
    """

    def __init__(self, find_returns=None):
        self.find_returns = list(find_returns or [])
        self.calls: list[tuple] = []

    def find(self, button):
        self.calls.append(("find", button))
        if self.find_returns:
            return self.find_returns.pop(0)
        return None

    def click(self, button):
        self.calls.append(("click", button))
        # Mirror real `InputBackend.click(Button)` semantics: if not visible,
        # raise MatchTimeout. We treat "next find_returns is None" as the
        # signal; otherwise pretend the click succeeded.
        if self.find_returns and self.find_returns[0] is None:
            self.find_returns.pop(0)
            raise MatchTimeout(f"stub: {button} not visible")
        return (0, 0)

    def click_xy(self, x, y, *, randomize=True):
        self.calls.append(("click_xy", (x, y), randomize))


def _ctx(backend):
    return NavigationContext(backend=backend)


_TEST_BUTTON = Button.simple("test/btn", name="test button")


def test_subgraph_prefixes_bare_vertex_ids():
    with subgraph("plugin") as g:
        vertex("entry")
        vertex("exit")
    assert g.has_vertex("plugin.entry")
    assert g.has_vertex("plugin.exit")
    assert g.vertex_owner("plugin.entry") == "plugin"


def test_subgraph_prefixes_bare_edge_endpoints():
    with subgraph("plugin") as g:
        vertex("a")
        vertex("b")
        edge("a", "b", action=_no_action)
    assert g.has_edge("plugin.a", "plugin.b")


def test_subgraph_keeps_dotted_edge_endpoints_verbatim():
    with subgraph("plugin") as g:
        vertex("a")
        edge("a", "other.entry", action=_no_action)
    assert g.has_edge("plugin.a", "other.entry")


def test_external_strips_namespace_for_root_refs():
    """`external("main_menu")` (no dot) must stay bare — used to reach root."""
    with subgraph("plugin") as g:
        vertex("a")
        edge("a", external("main_menu"), action=_no_action)
    assert g.has_edge("plugin.a", "main_menu")


def test_external_works_with_dotted_names_too():
    with subgraph("plugin") as g:
        vertex("a")
        edge("a", external("other.entry"), action=_no_action)
    assert g.has_edge("plugin.a", "other.entry")


def test_root_graph_no_prefix():
    with root_graph() as g:
        vertex("main_menu")
        vertex("profile")
        edge("main_menu", "profile", action=_no_action)
    assert g.has_vertex("main_menu")
    assert g.has_vertex("profile")
    assert g.has_edge("main_menu", "profile")
    # owner defaults to "main" in the root graph.
    assert g.vertex_owner("main_menu") == "main"


def test_calls_outside_context_fail():
    with pytest.raises(GraphValidationError):
        vertex("oops")
    with pytest.raises(GraphValidationError):
        edge("a", "b", action=_no_action)


def test_subgraph_requires_non_empty_namespace():
    with pytest.raises(ValueError):
        with subgraph(""):  # type: ignore[arg-type]
            pass


def test_external_requires_non_empty_name():
    with pytest.raises(ValueError):
        external("")


def test_nested_contexts_use_innermost():
    with subgraph("outer", graph=GameGraph()) as outer_g:
        vertex("a")  # registers outer.a
        with subgraph("inner", graph=GameGraph()) as inner_g:
            vertex("a")  # registers inner.a in inner_g
        # back in outer
        vertex("b")
    assert outer_g.has_vertex("outer.a")
    assert outer_g.has_vertex("outer.b")
    assert inner_g.has_vertex("inner.a")
    assert not inner_g.has_vertex("outer.a")


# --------------------------------------------------------------------------- #
# click_button_with_expand
# --------------------------------------------------------------------------- #
_REGION = (100, 200, 300, 400)


def test_click_button_with_expand_visible_skips_expand():
    """Button visible on first find — skip the hotspot tap, click directly."""
    backend = _StubBackend(find_returns=[(150, 250)])  # visible
    action = click_button_with_expand(_TEST_BUTTON, _REGION)
    with patch("core.navigation.builder.time.sleep") as sleep:
        action(_ctx(backend))
    # find -> click; no click_xy, no sleep.
    assert [c[0] for c in backend.calls] == ["find", "click"]
    sleep.assert_not_called()


def test_click_button_with_expand_hidden_taps_then_clicks():
    """Button not visible — tap hotspot, wait, then click."""
    backend = _StubBackend(find_returns=[None])  # hidden on first find
    action = click_button_with_expand(
        _TEST_BUTTON, _REGION, wait_after_expand=0.5,
    )
    with patch("core.navigation.builder.time.sleep") as sleep:
        action(_ctx(backend))
    kinds = [c[0] for c in backend.calls]
    # find (None) -> click_xy in region -> click.
    assert kinds == ["find", "click_xy", "click"]
    # The click_xy coordinates must be inside the region rect.
    _, (x, y), _ = backend.calls[1]
    x1, y1, x2, y2 = _REGION
    assert x1 <= x <= x2 and y1 <= y <= y2
    sleep.assert_called_once_with(0.5)


def test_click_button_with_expand_propagates_match_timeout_after_expand():
    """If expand didn't help, MatchTimeout from final click propagates."""
    # find -> None (hidden) -> after expand, find -> None again from click()
    backend = _StubBackend(find_returns=[None, None])
    action = click_button_with_expand(_TEST_BUTTON, _REGION)
    with patch("core.navigation.builder.time.sleep"):
        with pytest.raises(MatchTimeout):
            action(_ctx(backend))


def test_click_button_with_expand_uses_rng_for_hotspot_jitter():
    """Two invocations with different rng seeds pick different points."""
    # Make the helper deterministic per call via the module-level random.
    # We snapshot two seeds and confirm at least one differs (the rect
    # is 200x200 so collisions are vanishingly rare).
    points = []
    for seed in (1, 2):
        backend = _StubBackend(find_returns=[None])
        random.seed(seed)
        action = click_button_with_expand(_TEST_BUTTON, _REGION)
        with patch("core.navigation.builder.time.sleep"):
            action(_ctx(backend))
        points.append(backend.calls[1][1])  # the click_xy (x, y)
    assert points[0] != points[1]


def test_click_button_with_expand_rejects_negative_wait():
    with pytest.raises(ValueError, match="wait_after_expand"):
        click_button_with_expand(_TEST_BUTTON, _REGION, wait_after_expand=-1.0)


def test_click_button_with_expand_passes_randomize_to_hotspot_tap():
    """`randomize=False` should propagate to `backend.click_xy`."""
    backend = _StubBackend(find_returns=[None])
    action = click_button_with_expand(_TEST_BUTTON, _REGION, randomize=False)
    with patch("core.navigation.builder.time.sleep"):
        action(_ctx(backend))
    _, _, randomize = backend.calls[1]
    assert randomize is False
