"""
`TemplateRepository` — loads template PNGs from disk, caches them in memory.

Templates are immutable game-UI sprites, so the repository is **shared across
accounts**. This is an explicit exception to the multi-account isolation rule
(CLAUDE.md S5): per-account state must isolate, but per-game *content* may
share. Screenshots are still per-account.

The repository keeps templates indexed by **logical name** (relative path
under ``templates/`` without the ``.png`` suffix). Files with an alpha
channel are preserved with their alpha intact so callers can choose to
treat alpha as a match mask (see `TemplateMatcher`).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from core.cache.lru import TTLCache
from core.exceptions import TemplateNotFound
from core.logging_config import get_logger

log = get_logger(__name__)

# Templates almost never change at runtime; an enormous TTL is fine. We still
# use TTLCache so the same primitive serves both this and the screenshot
# cache (different instance, different TTL).
_TEMPLATE_TTL = 60 * 60 * 24


class TemplateRepository:
    """File-backed template loader.

    One instance per process is typically enough, since the file tree is
    shared. Callers may pass their own root for tests.
    """

    def __init__(self, root: Optional[Path] = None, max_cached: int = 512) -> None:
        """Construct a repository rooted at `root`.

        Args:
            root: Templates directory. Defaults to ``<project>/templates``.
            max_cached: Upper bound on number of templates kept in memory.
                Each template is ~tens of KB; 512 is generous.

        Raises:
            ValueError: If `max_cached <= 0`.
        """
        if root is None:
            root = Path(__file__).resolve().parents[2] / "templates"
        self._root = Path(root)
        self._cache: TTLCache[str, np.ndarray] = TTLCache(
            max_size=max_cached, default_ttl=float(_TEMPLATE_TTL)
        )
        self._load_lock = threading.Lock()

    @property
    def root(self) -> Path:
        """Resolved templates root."""
        return self._root

    def resolve(self, name: str) -> Path:
        """Map a logical template name to its on-disk path.

        Args:
            name: Logical name. Forward slashes are accepted on every
                platform. Trailing ``.png`` is tolerated and stripped.

        Returns:
            Absolute `Path` (may not exist; this is a pure path computation).
        """
        cleaned = name.replace("\\", "/").lstrip("/")
        if cleaned.lower().endswith(".png"):
            cleaned = cleaned[:-4]
        return self._root.joinpath(*cleaned.split("/")).with_suffix(".png")

    def get(self, name: str) -> np.ndarray:
        """Return the cached template array for `name`.

        Args:
            name: Logical template name. See `resolve`.

        Returns:
            ndarray, dtype uint8. Shape ``(H, W, 3)`` for BGR templates,
            ``(H, W, 4)`` for BGRA templates with alpha preserved.

        Raises:
            TemplateNotFound: File missing or unreadable.
        """
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        # Hold a per-repo load lock so a stampede of concurrent first-access
        # only hits the disk once.
        with self._load_lock:
            cached = self._cache.get(name)
            if cached is not None:
                return cached
            cached = self._load_from_disk(name)
            self._cache.set(name, cached)
            return cached

    def load(self, name: str) -> np.ndarray:
        """Alias for `get`. Kept for readability at call sites."""
        return self.get(name)

    def invalidate(self, name: Optional[str] = None) -> None:
        """Drop one or all cached templates.

        Args:
            name: If provided, drop only that entry. If None, clear the
                whole cache. Useful when a developer regenerates a template
                in `dev_tools/template_extractor.py` and wants the next
                match to pick up the new pixels.
        """
        if name is None:
            self._cache.clear()
        else:
            self._cache.invalidate(name)

    def _load_from_disk(self, name: str) -> np.ndarray:
        path = self.resolve(name)
        if not path.is_file():
            raise TemplateNotFound(
                f"Template '{name}' not found at expected path: {path}"
            )
        # IMREAD_UNCHANGED preserves alpha when present.
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise TemplateNotFound(
                f"Template '{name}' could not be decoded by cv2 at {path}"
            )
        log.debug("loaded template %s shape=%s", name, img.shape)
        return img
