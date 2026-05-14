"""TemplateMatcher: end-to-end on synthetic frames."""

import cv2
import numpy as np
import pytest

from core.exceptions import VisionError
from core.vision.button import Button
from core.vision.template_matcher import TemplateMatcher
from core.vision.template_repository import TemplateRepository


@pytest.fixture
def repo_with_dot(tmp_path):
    """A 20x20 patterned template, plus helpers to embed it in a screenshot.

    The template must not be uniform — TM_CCOEFF_NORMED is degenerate (zero
    variance => NaN/1.0 everywhere) on flat color, so we draw a clear pattern.
    """
    template = np.zeros((20, 20, 3), dtype=np.uint8)
    cv2.rectangle(template, (0, 0), (19, 19), (255, 255, 255), thickness=1)
    cv2.line(template, (0, 0), (19, 19), (0, 0, 255), 2)
    cv2.line(template, (19, 0), (0, 19), (0, 255, 0), 2)
    cv2.circle(template, (10, 10), 4, (255, 255, 0), -1)
    cv2.imwrite(str(tmp_path / "dot.png"), template)
    repo = TemplateRepository(root=tmp_path)
    return repo, template


def _make_screen_with(template, x, y):
    screen = np.zeros((480, 640, 3), dtype=np.uint8)
    h, w = template.shape[:2]
    screen[y : y + h, x : x + w] = template
    return screen


def test_find_returns_center(repo_with_dot):
    repo, template = repo_with_dot
    matcher = TemplateMatcher(repo)
    screen = _make_screen_with(template, 100, 50)
    point = matcher.find(screen, Button.simple("dot"))
    assert point is not None
    cx, cy = point
    # Center of a 20x20 template placed at (100, 50) is (110, 60).
    assert abs(cx - 110) <= 1
    assert abs(cy - 60) <= 1


def test_find_returns_none_below_threshold(repo_with_dot):
    repo, _ = repo_with_dot
    matcher = TemplateMatcher(repo)
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    assert matcher.find(blank, Button.simple("dot", threshold=0.95)) is None


def test_click_offset_applied(repo_with_dot):
    repo, template = repo_with_dot
    matcher = TemplateMatcher(repo)
    screen = _make_screen_with(template, 100, 50)
    button = Button(template="dot", click_offset=(7, -3))
    cx, cy = matcher.find(screen, button)
    assert abs(cx - (110 + 7)) <= 1
    assert abs(cy - (60 - 3)) <= 1


def test_region_restricts_search(repo_with_dot):
    repo, template = repo_with_dot
    matcher = TemplateMatcher(repo)
    screen = _make_screen_with(template, 100, 50)
    # Search a region that excludes the template — must miss.
    button = Button(template="dot", region=(0, 200, 200, 400))
    assert matcher.find(screen, button) is None
    # Region that includes it — must hit and respect the region offset math.
    button2 = Button(template="dot", region=(80, 30, 200, 200))
    point = matcher.find(screen, button2)
    assert point is not None
    cx, cy = point
    assert abs(cx - 110) <= 1
    assert abs(cy - 60) <= 1


def test_find_all_deduplicates(repo_with_dot):
    repo, template = repo_with_dot
    matcher = TemplateMatcher(repo)
    screen = np.zeros((480, 640, 3), dtype=np.uint8)
    # Place three copies far apart.
    for x, y in [(20, 20), (200, 100), (400, 300)]:
        h, w = template.shape[:2]
        screen[y : y + h, x : x + w] = template
    hits = matcher.find_all(screen, Button.simple("dot"))
    assert len(hits) == 3


def test_screenshot_dtype_validation(repo_with_dot):
    repo, _ = repo_with_dot
    matcher = TemplateMatcher(repo)
    with pytest.raises(VisionError):
        matcher.find(np.zeros((10, 10, 3), dtype=np.float32), Button.simple("dot"))
    with pytest.raises(VisionError):
        matcher.find(np.zeros((10, 10), dtype=np.uint8), Button.simple("dot"))
