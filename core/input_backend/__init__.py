"""Input backend layer (Strategy pattern). See `InputBackend`."""

from core.input_backend.base import InputBackend
from core.input_backend.factory import get_input_backend

__all__ = ["InputBackend", "get_input_backend"]
