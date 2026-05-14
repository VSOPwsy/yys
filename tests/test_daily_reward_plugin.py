"""
End-to-end-ish tests for the daily_reward plugin.

These tests stub the navigator + backend rather than going through a
real emulator. They verify the *flow* — open panel → claim → confirm
→ return — and the soft-fail behavior on already-claimed.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from core.cache.manager import CacheManager
from core.exceptions import MatchTimeout
from core.scheduler.plugin_base import PluginContext
from plugins.daily_reward.plugin import DailyRewardPlugin


def _make_ctx(*, navigator=None, backend=None) -> PluginContext:
    return PluginContext(
        account_id="alice",
        backend=backend or MagicMock(),
        navigator=navigator or MagicMock(),
        matcher=MagicMock(),
        ocr=None,
        cache=CacheManager(account_id="alice"),
        logger=logging.getLogger("test.daily_reward"),
    )


# --------------------------------------------------------------------------- #
# Static / structural
# --------------------------------------------------------------------------- #
def test_plugin_has_required_metadata():
    p = DailyRewardPlugin()
    assert p.name == "daily_reward"
    assert "main_menu" in p.requires_vertices
    assert "daily_reward.sign_in_panel" in p.requires_vertices
    assert p.SAFE_VERTEX == "main_menu"


def test_build_subgraph_owns_only_sign_in_panel():
    from plugins.daily_reward.graph import build_subgraph
    g = build_subgraph()
    ids = list(g.vertex_ids())
    # Subgraph owns sign_in_panel — main_menu lives in the root graph
    # and only appears as a (ghost) edge endpoint here.
    assert ids == ["daily_reward.sign_in_panel"]


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_run_happy_path_claims_and_returns():
    p = DailyRewardPlugin()
    nav = MagicMock()
    backend = MagicMock()
    # Stub: not already claimed; claim button clicks fine; OCR off; confirm fine.
    backend.is_visible.return_value = False  # ALREADY_CLAIMED_ANCHOR absent
    backend.click.return_value = (123, 456)

    ctx = _make_ctx(navigator=nav, backend=backend)
    p.setup(ctx)
    p.run(ctx)

    # Navigator was called for the open + the return.
    targets = [call.args[0] for call in nav.goto.call_args_list]
    assert "daily_reward.sign_in_panel" in targets
    assert "main_menu" in targets
    assert p.claimed is True


# --------------------------------------------------------------------------- #
# Already claimed: short-circuit
# --------------------------------------------------------------------------- #
def test_run_short_circuits_when_already_claimed():
    p = DailyRewardPlugin()
    nav = MagicMock()
    backend = MagicMock()
    backend.is_visible.return_value = True  # already claimed today

    ctx = _make_ctx(navigator=nav, backend=backend)
    p.setup(ctx)
    p.run(ctx)

    # claim button was NOT clicked
    backend.click.assert_not_called()
    assert p.claimed is False
    # We still returned to main menu.
    targets = [call.args[0] for call in nav.goto.call_args_list]
    assert "main_menu" in targets


# --------------------------------------------------------------------------- #
# Claim button missing: graceful no-op
# --------------------------------------------------------------------------- #
def test_run_handles_claim_button_missing():
    p = DailyRewardPlugin()
    nav = MagicMock()
    backend = MagicMock()
    backend.is_visible.return_value = False

    # First click() (CLAIM_TODAY_BTN) raises MatchTimeout; subsequent
    # CONFIRM_REWARD_BTN clicks are not reached because steps.claim_today
    # returns False and run() returns early.
    backend.click.side_effect = MatchTimeout("claim button not visible")

    ctx = _make_ctx(navigator=nav, backend=backend)
    p.setup(ctx)
    p.run(ctx)

    # Confirm: claimed stays False, we still navigated back home.
    assert p.claimed is False
    targets = [call.args[0] for call in nav.goto.call_args_list]
    assert "main_menu" in targets


# --------------------------------------------------------------------------- #
# Stop-aware: run() exits on should_stop()
# --------------------------------------------------------------------------- #
def test_run_returns_early_on_stop():
    p = DailyRewardPlugin()
    nav = MagicMock()
    backend = MagicMock()
    ctx = _make_ctx(navigator=nav, backend=backend)
    ctx._stop_event.set()  # stop before run starts
    p.setup(ctx)
    p.run(ctx)
    nav.goto.assert_not_called()
    assert p.claimed is False
