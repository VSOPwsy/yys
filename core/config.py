"""
`core.config` — typed config loader for ``config/config.yaml``.

Why a separate module instead of just ``yaml.safe_load`` in main.py:

* Schema validation up front means a typo'd plugin name (or a negative
  ``daily_max_runtime_minutes``) blows up at startup with a clear message,
  not 30 minutes into the run with a stack trace from deep inside the
  scheduler.
* The dataclasses are the *contract* used by main.py, the long-run
  policy, the hotkey controller, etc. — they decouple "what is in the
  yaml" from "what the code reads".
* Tests can construct configs directly without touching disk.

Shape (matches ``config/config.yaml``)::

    AppConfig
    ├── global_ (GlobalConfig)
    │   ├── scheduler (SchedulerPolicyConfig)
    │   ├── humanize  (HumanizeConfig)
    │   └── hotkeys   (HotkeyConfig)
    └── accounts (list[AccountConfig])
        └── plugins (dict[str, PluginConfig])

Public surface: `load_config(path)` and `AppConfig` + nested dataclasses.
All other names are loader internals.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Any, Dict, List, Mapping, Optional, Sequence

import yaml

from core.exceptions import ConfigError

# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class SchedulerPolicyConfig:
    """Long-run scheduling policy. All durations in minutes / seconds as named."""

    daily_max_runtime_minutes: int = 480
    rest_every_minutes: int = 90
    rest_duration_minutes: int = 10
    inter_plugin_gap_seconds: float = 5.0
    concurrent_plugins: bool = False
    graceful_stop_timeout_seconds: float = 10.0


@dataclasses.dataclass(frozen=True)
class HumanizeConfig:
    """Humanize / throttle parameters shared by all accounts."""

    click_jitter_radius: int = 12
    # Fraction of each side of a matched button's bbox to inset before
    # uniformly sampling the click. ``0.1`` = sample the inner 80% along
    # each axis (5% off each edge). ``0.0`` = sample anywhere in the bbox.
    # Must be in ``[0, 0.5)``. The actual inset has a 2px hard minimum to
    # avoid edge-pixel clicks on tiny templates regardless of the fraction.
    bbox_margin: float = 0.1
    delay_variance: float = 0.5
    min_action_interval_ms: int = 400
    max_actions_per_minute: int = 60
    post_delay_variance: float = 0.3


@dataclasses.dataclass(frozen=True)
class HotkeyConfig:
    """OS-level hotkey bindings. Strings are keyboard-package syntax."""

    pause: str = "f9"
    stop: str = "f10"
    exit: str = "f12"
    backend: str = "keyboard"  # 'keyboard' or 'noop'


@dataclasses.dataclass(frozen=True)
class GlobalConfig:
    scheduler: SchedulerPolicyConfig = dataclasses.field(
        default_factory=SchedulerPolicyConfig
    )
    humanize: HumanizeConfig = dataclasses.field(default_factory=HumanizeConfig)
    hotkeys: HotkeyConfig = dataclasses.field(default_factory=HotkeyConfig)


@dataclasses.dataclass(frozen=True)
class EmulatorConfig:
    """Per-account emulator configuration. Currently only nemu is wired up."""

    backend: str = "nemu"  # 'nemu' or 'fake' (test mode)
    mumu_folder: str = "D:/Program Files/Netease/MuMu"
    instance_id: int = 0
    display_id: int = 0


@dataclasses.dataclass(frozen=True)
class PluginConfig:
    """Per-(account, plugin) tuning. `params` is plugin-specific extras."""

    enabled: bool = True
    params: Mapping[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class AccountConfig:
    id: str
    emulator: EmulatorConfig = dataclasses.field(default_factory=EmulatorConfig)
    plugins: Dict[str, PluginConfig] = dataclasses.field(default_factory=dict)

    @property
    def enabled_plugin_names(self) -> List[str]:
        """List of plugin names whose `enabled` is true. Stable order."""
        return sorted(name for name, cfg in self.plugins.items() if cfg.enabled)


@dataclasses.dataclass(frozen=True)
class AppConfig:
    """Top-level config — the object main.py orchestrates with."""

    global_: GlobalConfig = dataclasses.field(default_factory=GlobalConfig)
    accounts: List[AccountConfig] = dataclasses.field(default_factory=list)


# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #
def load_config(path: pathlib.Path | str) -> AppConfig:
    """Parse and validate a YAML config file.

    Args:
        path: Filesystem path to a YAML document matching the schema.

    Returns:
        Fully-populated, frozen `AppConfig`.

    Raises:
        ConfigError: file missing / not a mapping / unknown keys / invalid
            values / duplicate account ids / negative durations.
    """
    p = pathlib.Path(path)
    if not p.is_file():
        raise ConfigError(f"config file not found: {p}")
    try:
        with p.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"yaml parse error in {p}: {e}") from e

    if raw is None:
        raise ConfigError(f"config file {p} is empty")
    if not isinstance(raw, Mapping):
        raise ConfigError(
            f"config file {p} top-level must be a mapping, got {type(raw).__name__}"
        )

    global_cfg = _parse_global(raw.get("global", {}) or {}, path=p)
    accounts_raw = raw.get("accounts") or []
    if not isinstance(accounts_raw, Sequence) or isinstance(accounts_raw, str):
        raise ConfigError(
            f"config {p}: 'accounts' must be a list, got {type(accounts_raw).__name__}"
        )
    accounts = [_parse_account(a, idx, path=p) for idx, a in enumerate(accounts_raw)]

    seen_ids: Dict[str, int] = {}
    for idx, acc in enumerate(accounts):
        if acc.id in seen_ids:
            raise ConfigError(
                f"config {p}: duplicate account id {acc.id!r} at index {idx} "
                f"(also at index {seen_ids[acc.id]})"
            )
        seen_ids[acc.id] = idx

    return AppConfig(global_=global_cfg, accounts=accounts)


# --------------------------------------------------------------------------- #
# Per-section parsers
# --------------------------------------------------------------------------- #
def _parse_global(raw: Mapping[str, Any], *, path: pathlib.Path) -> GlobalConfig:
    return GlobalConfig(
        scheduler=_parse_scheduler(raw.get("scheduler", {}) or {}, path=path),
        humanize=_parse_humanize(raw.get("humanize", {}) or {}, path=path),
        hotkeys=_parse_hotkeys(raw.get("hotkeys", {}) or {}, path=path),
    )


def _parse_scheduler(
    raw: Mapping[str, Any],
    *,
    path: pathlib.Path,
) -> SchedulerPolicyConfig:
    fields = {f.name for f in dataclasses.fields(SchedulerPolicyConfig)}
    unknown = set(raw) - fields
    if unknown:
        raise ConfigError(
            f"config {path}: unknown scheduler keys {sorted(unknown)}"
        )
    cfg = SchedulerPolicyConfig(**{k: raw[k] for k in raw if k in fields})
    _require_positive(cfg.daily_max_runtime_minutes,
                      "scheduler.daily_max_runtime_minutes", path)
    _require_positive(cfg.rest_every_minutes, "scheduler.rest_every_minutes", path)
    _require_positive(cfg.rest_duration_minutes,
                      "scheduler.rest_duration_minutes", path)
    _require_nonnegative(cfg.inter_plugin_gap_seconds,
                         "scheduler.inter_plugin_gap_seconds", path)
    _require_positive(cfg.graceful_stop_timeout_seconds,
                      "scheduler.graceful_stop_timeout_seconds", path)
    return cfg


def _parse_humanize(
    raw: Mapping[str, Any],
    *,
    path: pathlib.Path,
) -> HumanizeConfig:
    fields = {f.name for f in dataclasses.fields(HumanizeConfig)}
    unknown = set(raw) - fields
    if unknown:
        raise ConfigError(
            f"config {path}: unknown humanize keys {sorted(unknown)}"
        )
    cfg = HumanizeConfig(**{k: raw[k] for k in raw if k in fields})
    _require_nonnegative(cfg.click_jitter_radius,
                         "humanize.click_jitter_radius", path)
    if not (0.0 <= cfg.bbox_margin < 0.5):
        raise ConfigError(
            f"config {path}: humanize.bbox_margin must be in [0, 0.5), "
            f"got {cfg.bbox_margin}"
        )
    _require_nonnegative(cfg.delay_variance, "humanize.delay_variance", path)
    _require_nonnegative(cfg.min_action_interval_ms,
                         "humanize.min_action_interval_ms", path)
    _require_nonnegative(cfg.max_actions_per_minute,
                         "humanize.max_actions_per_minute", path)
    _require_nonnegative(cfg.post_delay_variance,
                         "humanize.post_delay_variance", path)
    return cfg


def _parse_hotkeys(
    raw: Mapping[str, Any],
    *,
    path: pathlib.Path,
) -> HotkeyConfig:
    fields = {f.name for f in dataclasses.fields(HotkeyConfig)}
    unknown = set(raw) - fields
    if unknown:
        raise ConfigError(
            f"config {path}: unknown hotkeys keys {sorted(unknown)}"
        )
    cfg = HotkeyConfig(**{k: raw[k] for k in raw if k in fields})
    if cfg.backend not in ("keyboard", "noop"):
        raise ConfigError(
            f"config {path}: hotkeys.backend must be 'keyboard' or 'noop', "
            f"got {cfg.backend!r}"
        )
    return cfg


def _parse_account(
    raw: Mapping[str, Any],
    idx: int,
    *,
    path: pathlib.Path,
) -> AccountConfig:
    if not isinstance(raw, Mapping):
        raise ConfigError(
            f"config {path}: accounts[{idx}] must be a mapping, "
            f"got {type(raw).__name__}"
        )
    aid = raw.get("id")
    if not isinstance(aid, str) or not aid:
        raise ConfigError(
            f"config {path}: accounts[{idx}].id must be a non-empty string"
        )
    emulator = _parse_emulator(raw.get("emulator", {}) or {}, idx=idx, path=path)
    plugins_raw = raw.get("plugins", {}) or {}
    if not isinstance(plugins_raw, Mapping):
        raise ConfigError(
            f"config {path}: accounts[{idx}].plugins must be a mapping, "
            f"got {type(plugins_raw).__name__}"
        )
    plugins: Dict[str, PluginConfig] = {}
    for name, pcfg in plugins_raw.items():
        if not isinstance(name, str) or not name:
            raise ConfigError(
                f"config {path}: accounts[{idx}].plugins keys must be non-empty strings"
            )
        plugins[name] = _parse_plugin(pcfg or {}, idx=idx, plugin_name=name, path=path)
    return AccountConfig(id=aid, emulator=emulator, plugins=plugins)


def _parse_emulator(
    raw: Mapping[str, Any],
    *,
    idx: int,
    path: pathlib.Path,
) -> EmulatorConfig:
    fields = {f.name for f in dataclasses.fields(EmulatorConfig)}
    unknown = set(raw) - fields
    if unknown:
        raise ConfigError(
            f"config {path}: accounts[{idx}].emulator unknown keys {sorted(unknown)}"
        )
    cfg = EmulatorConfig(**{k: raw[k] for k in raw if k in fields})
    if cfg.backend not in ("nemu", "fake"):
        raise ConfigError(
            f"config {path}: accounts[{idx}].emulator.backend must be 'nemu' "
            f"or 'fake', got {cfg.backend!r}"
        )
    if cfg.instance_id < 0:
        raise ConfigError(
            f"config {path}: accounts[{idx}].emulator.instance_id must be >= 0"
        )
    if cfg.display_id < 0:
        raise ConfigError(
            f"config {path}: accounts[{idx}].emulator.display_id must be >= 0"
        )
    return cfg


def _parse_plugin(
    raw: Mapping[str, Any],
    *,
    idx: int,
    plugin_name: str,
    path: pathlib.Path,
) -> PluginConfig:
    if not isinstance(raw, Mapping):
        raise ConfigError(
            f"config {path}: accounts[{idx}].plugins[{plugin_name!r}] must be "
            f"a mapping, got {type(raw).__name__}"
        )
    enabled = bool(raw.get("enabled", True))
    params = dict(raw.get("params") or {})
    # Anything not "enabled" or "params" is a typo we want to surface.
    unknown = set(raw) - {"enabled", "params"}
    if unknown:
        raise ConfigError(
            f"config {path}: accounts[{idx}].plugins[{plugin_name!r}] "
            f"unknown keys {sorted(unknown)} (allowed: 'enabled', 'params')"
        )
    return PluginConfig(enabled=enabled, params=params)


# --------------------------------------------------------------------------- #
# Validators
# --------------------------------------------------------------------------- #
def _require_positive(value, label: str, path: pathlib.Path) -> None:
    if value is None or value <= 0:
        raise ConfigError(f"config {path}: {label} must be > 0, got {value!r}")


def _require_nonnegative(value, label: str, path: pathlib.Path) -> None:
    if value is None or value < 0:
        raise ConfigError(f"config {path}: {label} must be >= 0, got {value!r}")


__all__ = [
    "AccountConfig",
    "AppConfig",
    "EmulatorConfig",
    "GlobalConfig",
    "HotkeyConfig",
    "HumanizeConfig",
    "PluginConfig",
    "SchedulerPolicyConfig",
    "load_config",
]
