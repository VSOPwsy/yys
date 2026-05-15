"""Unit tests for `NemuIpcBackend` — the parts we can exercise without a
real DLL.

The backend's constructor loads the DLL and connects, which can't run in CI,
so this file only covers the path-detection helper used to decide whether
Alas's legacy 90° rotation should be bypassed for the v5.0+ MuMu DLL.
Empirical correctness of the rotation itself is verified on a live emulator
via `dev_tools/ipc_smoke_test.py` — see CLAUDE.md §7.
"""

from pathlib import Path

from core.input_backend.nemu_backend import NemuIpcBackend


def _make_dll(root: Path, *parts: str) -> Path:
    """Create an empty file at root / parts and return its path."""
    p = root.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    return p


def test_rotation_bypass_skipped_when_only_classic_dll(tmp_path):
    # Classic MuMu install: only the legacy DLL path exists. Alas's
    # `convert_xy` rotation is correct here — we must NOT bypass.
    _make_dll(tmp_path, "shell", "sdk", "external_renderer_ipc.dll")
    assert NemuIpcBackend._needs_rotation_bypass(str(tmp_path)) is False


def test_rotation_bypass_enabled_when_only_v5_dll(tmp_path):
    # v5.0+ install: only the new DLL path exists. Alas loads v5, which
    # accepts ADB landscape coords directly. We must bypass `convert_xy`.
    _make_dll(tmp_path, "nx_device", "12.0", "shell", "sdk", "external_renderer_ipc.dll")
    assert NemuIpcBackend._needs_rotation_bypass(str(tmp_path)) is True


def test_rotation_bypass_skipped_when_both_dlls_present(tmp_path):
    # Both exist: Alas's loader iterates classic first, so it loads classic;
    # rotation is correct for that DLL. Bypass would break clicks.
    _make_dll(tmp_path, "shell", "sdk", "external_renderer_ipc.dll")
    _make_dll(tmp_path, "nx_device", "12.0", "shell", "sdk", "external_renderer_ipc.dll")
    assert NemuIpcBackend._needs_rotation_bypass(str(tmp_path)) is False


def test_rotation_bypass_skipped_when_no_dll(tmp_path):
    # Neither DLL present. Alas's constructor would raise NemuIpcIncompatible
    # before we get here, but the helper should still return False so the
    # bypass logic doesn't accidentally trigger on a half-installed MuMu.
    assert NemuIpcBackend._needs_rotation_bypass(str(tmp_path)) is False
