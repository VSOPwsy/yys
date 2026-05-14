"""Button dataclass validation + ergonomics."""

import pytest

from core.vision.button import Button


def test_simple_constructs_with_defaults():
    b = Button.simple("main_menu/profile_btn")
    assert b.template == "main_menu/profile_btn"
    assert b.threshold == 0.85
    assert b.region is None
    assert b.display_name == "main_menu/profile_btn"


def test_in_region_carries_region():
    b = Button.in_region("a/b", (0, 0, 100, 100))
    assert b.region == (0, 0, 100, 100)


def test_with_clones_with_overrides():
    b1 = Button.simple("a/b", post_delay=0.5)
    b2 = b1.with_(post_delay=1.5)
    assert b1.post_delay == 0.5  # immutable original untouched
    assert b2.post_delay == 1.5
    assert b1.template == b2.template


def test_explicit_name_overrides_display():
    b = Button.simple("path/x", name="profile")
    assert b.display_name == "profile"


@pytest.mark.parametrize("bad", [-0.1, 0.0, 1.5])
def test_invalid_threshold(bad):
    with pytest.raises(ValueError, match="threshold"):
        Button(template="a", threshold=bad)


def test_invalid_region():
    with pytest.raises(ValueError, match="region"):
        Button(template="a", region=(10, 10, 5, 5))


def test_empty_template_rejected():
    with pytest.raises(ValueError, match="template"):
        Button(template="")


def test_button_is_hashable():
    # Frozen dataclasses are hashable; we want to use Buttons as cache keys.
    b1 = Button.simple("a/b")
    b2 = Button.simple("a/b")
    assert hash(b1) == hash(b2)
    assert {b1, b2} == {b1}
