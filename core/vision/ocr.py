"""
`OcrEngine` — thread-safe singleton wrapper around PaddleOCR.

PaddleOCR is stateless from the caller's perspective but heavy to initialize
(loads multiple deep models, 500MB+ RAM). CLAUDE.md S5 grants OCR a single
explicit exception to the "no globals" rule, on the condition that the
shared instance is thread-safe.

PaddleOCR's `predict()` is not documented to be reentrant; in practice it
holds GPU/CPU state in the model objects. We serialize calls with a lock.
For workloads where OCR throughput becomes the bottleneck, swap the lock
for a pool of engines — but don't do that prematurely.

PaddleOCR is imported lazily inside the constructor so that just importing
`core.vision` doesn't pay the ~10s cold-start cost.
"""

from __future__ import annotations

import threading
from typing import List, Optional, Tuple

import numpy as np

from core.exceptions import OcrError
from core.logging_config import get_logger

log = get_logger(__name__)


_INSTANCE: Optional["OcrEngine"] = None
_INSTANCE_LOCK = threading.Lock()


class OcrEngine:
    """Thread-safe wrapper around a single PaddleOCR engine.

    Construct via `OcrEngine.instance()` rather than directly.
    """

    def __init__(self, lang: str = "ch") -> None:
        """Initialize a fresh PaddleOCR engine.

        Args:
            lang: PaddleOCR language code. ``"ch"`` covers both Chinese and
                English glyphs reasonably well, which matches the target
                game.

        Raises:
            OcrError: PaddleOCR import or initialization failed.
        """
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as e:
            raise OcrError(
                "paddleocr is required for OCR support. "
                "Install via `pip install paddleocr`."
            ) from e
        try:
            self._engine = PaddleOCR(lang=lang, use_angle_cls=True, show_log=False)
        except TypeError:
            # Newer paddleocr renamed parameters; try minimal init.
            self._engine = PaddleOCR(lang=lang)
        except Exception as e:  # noqa: BLE001 — engine init can raise anything
            raise OcrError(f"PaddleOCR init failed: {e!r}") from e
        self._call_lock = threading.Lock()
        log.info("OcrEngine ready (lang=%s)", lang)

    @classmethod
    def instance(cls, lang: str = "ch") -> "OcrEngine":
        """Return the process-wide singleton, building it lazily.

        Args:
            lang: Language code for the **first** call; ignored afterward.
                Mixing languages requires distinct engines; not supported now.

        Returns:
            The shared `OcrEngine`.

        Raises:
            OcrError: First-time init failed.
        """
        global _INSTANCE
        if _INSTANCE is None:
            with _INSTANCE_LOCK:
                if _INSTANCE is None:
                    _INSTANCE = cls(lang=lang)
        return _INSTANCE

    def recognize(self, image: np.ndarray) -> List[Tuple[str, float, Tuple[int, int, int, int]]]:
        """Run OCR on an image crop.

        Args:
            image: BGR ndarray, dtype uint8. Smaller crops are far faster;
                pass only the region you care about.

        Returns:
            List of ``(text, confidence, (x1, y1, x2, y2))``. Coordinates are
            relative to `image`. Empty list = no text detected.

        Raises:
            OcrError: Engine refused the input or raised internally.
        """
        if not isinstance(image, np.ndarray):
            raise OcrError(f"image must be ndarray, got {type(image).__name__}")
        if image.dtype != np.uint8:
            raise OcrError(f"image dtype must be uint8, got {image.dtype}")
        if image.ndim != 3 or image.shape[2] != 3:
            raise OcrError(f"image must be BGR (H, W, 3), got {image.shape}")

        try:
            with self._call_lock:
                raw = self._engine.ocr(image, cls=True)
        except Exception as e:  # noqa: BLE001
            raise OcrError(f"PaddleOCR call failed: {e!r}") from e

        return self._normalize_result(raw)

    def find_text(
        self,
        image: np.ndarray,
        keyword: str,
        min_confidence: float = 0.6,
        case_sensitive: bool = False,
    ) -> Optional[Tuple[int, int, int, int]]:
        """Return the bounding box of the first occurrence of `keyword`, if any.

        Args:
            image: Same constraints as `recognize`.
            keyword: Substring to look for in detected lines.
            min_confidence: Reject detections below this score.
            case_sensitive: Default False; matches the casual UI text we
                usually scan.

        Returns:
            ``(x1, y1, x2, y2)`` if found, else None.

        Raises:
            OcrError: Same as `recognize`.
        """
        needle = keyword if case_sensitive else keyword.lower()
        for text, conf, box in self.recognize(image):
            if conf < min_confidence:
                continue
            hay = text if case_sensitive else text.lower()
            if needle in hay:
                return box
        return None

    @staticmethod
    def _normalize_result(
        raw: object,
    ) -> List[Tuple[str, float, Tuple[int, int, int, int]]]:
        """Flatten PaddleOCR's nested return into a tidy list.

        PaddleOCR returns ``[[ [box, (text, conf)], ... ]]`` (extra outer list
        per image). We collapse that to one flat list and reduce the
        quadrilateral box to its axis-aligned bbox.
        """
        if not raw:
            return []
        # raw is list-of-pages; we always pass one page, but be defensive.
        pages = raw if isinstance(raw[0], list) else [raw]  # type: ignore[index]
        out: List[Tuple[str, float, Tuple[int, int, int, int]]] = []
        for page in pages:
            if not page:
                continue
            for line in page:
                try:
                    quad, (text, conf) = line
                    xs = [int(p[0]) for p in quad]
                    ys = [int(p[1]) for p in quad]
                    out.append(
                        (str(text), float(conf), (min(xs), min(ys), max(xs), max(ys)))
                    )
                except (TypeError, ValueError, IndexError) as e:
                    log.debug("skipped malformed OCR row: %r (%s)", line, e)
        return out
