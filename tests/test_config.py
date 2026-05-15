"""Unit tests for `core.config.load_config`."""

from __future__ import annotations

import textwrap

import pytest

from core.config import (
    AccountConfig,
    AppConfig,
    HumanizeConfig,
    load_config,
)
from core.exceptions import ConfigError


def _write(tmp_path, content: str) -> str:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return str(p)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_minimal_valid_config(tmp_path):
    path = _write(tmp_path, """
        accounts:
          - id: main
            emulator:
              backend: nemu
              mumu_folder: C:/MuMu
              instance_id: 0
            plugins:
              daily_reward:
                enabled: true
    """)
    cfg = load_config(path)
    assert isinstance(cfg, AppConfig)
    assert len(cfg.accounts) == 1
    acc = cfg.accounts[0]
    assert acc.id == "main"
    assert acc.emulator.mumu_folder == "C:/MuMu"
    assert acc.enabled_plugin_names == ["daily_reward"]


def test_defaults_filled_in_when_global_missing(tmp_path):
    path = _write(tmp_path, """
        accounts:
          - id: only
            emulator:
              backend: nemu
              mumu_folder: C:/MuMu
            plugins: {}
    """)
    cfg = load_config(path)
    # The whole `global:` section was elided — should fall back to defaults.
    assert cfg.global_.scheduler.daily_max_runtime_minutes == 480
    assert cfg.global_.humanize.click_jitter_radius == 12
    assert cfg.global_.humanize.bbox_margin == 0.1
    assert cfg.global_.hotkeys.pause == "f9"


def test_two_accounts_listed_in_yaml_order(tmp_path):
    path = _write(tmp_path, """
        accounts:
          - id: main
            emulator: {backend: nemu, mumu_folder: C:/MuMu, instance_id: 0}
            plugins: {}
          - id: alt1
            emulator: {backend: nemu, mumu_folder: C:/MuMu, instance_id: 1}
            plugins: {}
    """)
    cfg = load_config(path)
    assert [a.id for a in cfg.accounts] == ["main", "alt1"]


# --------------------------------------------------------------------------- #
# Validation errors
# --------------------------------------------------------------------------- #
def test_missing_file_raises():
    with pytest.raises(ConfigError):
        load_config("nonexistent.yaml")


def test_empty_file_raises(tmp_path):
    path = _write(tmp_path, "")
    with pytest.raises(ConfigError):
        load_config(path)


def test_top_level_not_mapping_raises(tmp_path):
    path = _write(tmp_path, "- 1\n- 2\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_account_missing_id_raises(tmp_path):
    path = _write(tmp_path, """
        accounts:
          - emulator: {backend: nemu, mumu_folder: C:/MuMu}
            plugins: {}
    """)
    with pytest.raises(ConfigError):
        load_config(path)


def test_duplicate_account_ids_raise(tmp_path):
    path = _write(tmp_path, """
        accounts:
          - id: main
            emulator: {backend: nemu, mumu_folder: C:/MuMu}
            plugins: {}
          - id: main
            emulator: {backend: nemu, mumu_folder: C:/MuMu, instance_id: 1}
            plugins: {}
    """)
    with pytest.raises(ConfigError, match="duplicate account id"):
        load_config(path)


def test_unknown_scheduler_key_raises(tmp_path):
    path = _write(tmp_path, """
        global:
          scheduler:
            whoops: 1
        accounts: []
    """)
    with pytest.raises(ConfigError, match="unknown scheduler keys"):
        load_config(path)


def test_negative_runtime_cap_raises(tmp_path):
    path = _write(tmp_path, """
        global:
          scheduler:
            daily_max_runtime_minutes: -5
        accounts: []
    """)
    with pytest.raises(ConfigError):
        load_config(path)


def test_bbox_margin_out_of_range_raises(tmp_path):
    # bbox_margin must be in [0, 0.5); 0.5+ would inset away the whole bbox.
    path = _write(tmp_path, """
        global:
          humanize:
            bbox_margin: 0.5
        accounts: []
    """)
    with pytest.raises(ConfigError, match="bbox_margin"):
        load_config(path)


def test_bbox_margin_negative_raises(tmp_path):
    path = _write(tmp_path, """
        global:
          humanize:
            bbox_margin: -0.1
        accounts: []
    """)
    with pytest.raises(ConfigError, match="bbox_margin"):
        load_config(path)


def test_bbox_margin_zero_is_valid(tmp_path):
    # 0.0 is allowed — means "sample anywhere in bbox, no inset".
    path = _write(tmp_path, """
        global:
          humanize:
            bbox_margin: 0.0
        accounts: []
    """)
    cfg = load_config(path)
    assert cfg.global_.humanize.bbox_margin == 0.0


def test_unknown_plugin_key_raises(tmp_path):
    path = _write(tmp_path, """
        accounts:
          - id: main
            emulator: {backend: nemu, mumu_folder: C:/MuMu}
            plugins:
              daily_reward:
                enabled: true
                wat: nope
    """)
    with pytest.raises(ConfigError, match="unknown keys"):
        load_config(path)


def test_invalid_hotkey_backend_raises(tmp_path):
    path = _write(tmp_path, """
        global:
          hotkeys:
            backend: invalid
        accounts: []
    """)
    with pytest.raises(ConfigError, match="hotkeys.backend"):
        load_config(path)


def test_invalid_emulator_backend_raises(tmp_path):
    path = _write(tmp_path, """
        accounts:
          - id: main
            emulator: {backend: scrcpy, mumu_folder: C:/MuMu}
            plugins: {}
    """)
    with pytest.raises(ConfigError):
        load_config(path)


def test_disabled_plugin_not_in_enabled_names(tmp_path):
    path = _write(tmp_path, """
        accounts:
          - id: main
            emulator: {backend: nemu, mumu_folder: C:/MuMu}
            plugins:
              daily_reward: {enabled: false}
              soul_dungeon: {enabled: true}
    """)
    cfg = load_config(path)
    assert cfg.accounts[0].enabled_plugin_names == ["soul_dungeon"]
