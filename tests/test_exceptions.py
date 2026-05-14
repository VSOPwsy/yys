"""Hierarchy & taxonomy checks on `core.exceptions`."""

import pytest

from core.exceptions import (
    BackendConnectionLost,
    BackendNotAvailable,
    BotError,
    InputBackendError,
    MatchTimeout,
    NavigationError,
    OcrError,
    PluginError,
    TemplateNotFound,
    VisionError,
)


@pytest.mark.parametrize(
    "subclass,parent",
    [
        (InputBackendError, BotError),
        (BackendNotAvailable, InputBackendError),
        (BackendConnectionLost, InputBackendError),
        (VisionError, BotError),
        (TemplateNotFound, VisionError),
        (MatchTimeout, VisionError),
        (OcrError, VisionError),
        (NavigationError, BotError),
        (PluginError, BotError),
    ],
)
def test_hierarchy(subclass, parent):
    assert issubclass(subclass, parent)
    assert issubclass(subclass, BotError)


def test_subclasses_carry_messages():
    e = TemplateNotFound("missing template foo")
    assert "missing template foo" in str(e)


def test_can_catch_at_root():
    with pytest.raises(BotError):
        raise MatchTimeout("nope")
