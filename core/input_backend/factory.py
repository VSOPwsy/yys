"""
`get_input_backend` — single dispatch point for backend construction.

Plugins should call this exactly once per account, store the returned
backend on their context, and pass it down. Keeps `NemuIpcBackend`'s
import (and its vendor/alas baggage) out of plugin modules.
"""

from __future__ import annotations

from typing import Optional

from core.exceptions import BackendNotAvailable
from core.input_backend.base import InputBackend
from core.vision.template_matcher import TemplateMatcher


def get_input_backend(
    account_id: str,
    backend_name: str = "nemu",
    *,
    matcher: Optional[TemplateMatcher] = None,
    **kwargs: object,
) -> InputBackend:
    """Build the requested backend for the given account.

    Args:
        account_id: Per-account identity.
        backend_name: Strategy selector. Currently only ``"nemu"`` is wired
            up. Adding ``"scrcpy"`` etc. is a matter of importing and
            dispatching here.
        matcher: Optional shared TemplateMatcher.
        **kwargs: Forwarded to the concrete backend constructor.
            For ``"nemu"`` the required keys are ``mumu_folder`` (str) and
            optional ``instance_id`` (int, default 0), ``display_id`` (int,
            default 0).

    Returns:
        An unconnected `InputBackend`. Call `.connect()` (or use as a context
        manager) to open the transport.

    Raises:
        BackendNotAvailable: Unknown `backend_name`, missing required
            kwargs, or the chosen backend rejected its config.
    """
    name = backend_name.lower()
    if name == "nemu":
        from core.input_backend.nemu_backend import NemuIpcBackend

        try:
            mumu_folder = kwargs.pop("mumu_folder")
        except KeyError as e:
            raise BackendNotAvailable(
                "nemu backend requires 'mumu_folder' kwarg"
            ) from e
        instance_id = int(kwargs.pop("instance_id", 0))  # type: ignore[arg-type]
        display_id = int(kwargs.pop("display_id", 0))  # type: ignore[arg-type]
        if kwargs:
            raise BackendNotAvailable(
                f"nemu backend got unexpected kwargs: {sorted(kwargs)}"
            )
        return NemuIpcBackend(
            account_id=account_id,
            mumu_folder=str(mumu_folder),
            instance_id=instance_id,
            display_id=display_id,
            matcher=matcher,
        )

    raise BackendNotAvailable(
        f"Unknown backend {backend_name!r}. Known: ['nemu']."
    )
