"""TemplateRepository: loading, caching, error paths."""

import cv2
import numpy as np
import pytest

from core.exceptions import TemplateNotFound
from core.vision.template_repository import TemplateRepository


@pytest.fixture
def temp_template_root(tmp_path):
    (tmp_path / "icons").mkdir()
    img = np.zeros((8, 8, 3), dtype=np.uint8)
    img[:, :, 1] = 255  # green
    assert cv2.imwrite(str(tmp_path / "icons" / "ok.png"), img)
    return tmp_path


def test_get_returns_array(temp_template_root):
    repo = TemplateRepository(root=temp_template_root)
    arr = repo.get("icons/ok")
    assert arr.shape == (8, 8, 3)
    assert arr.dtype == np.uint8


def test_get_accepts_png_suffix(temp_template_root):
    repo = TemplateRepository(root=temp_template_root)
    arr1 = repo.get("icons/ok")
    arr2 = repo.get("icons/ok.png")
    assert np.array_equal(arr1, arr2)


def test_missing_template_raises(temp_template_root):
    repo = TemplateRepository(root=temp_template_root)
    with pytest.raises(TemplateNotFound):
        repo.get("icons/nope")


def test_cache_hits_avoid_disk(temp_template_root, monkeypatch):
    repo = TemplateRepository(root=temp_template_root)
    repo.get("icons/ok")  # priming load

    calls = []
    real_imread = cv2.imread

    def spy(*args, **kwargs):
        calls.append(args)
        return real_imread(*args, **kwargs)

    monkeypatch.setattr(cv2, "imread", spy)
    repo.get("icons/ok")
    repo.get("icons/ok")
    assert calls == []


def test_invalidate_one(temp_template_root):
    repo = TemplateRepository(root=temp_template_root)
    repo.get("icons/ok")
    assert repo.invalidate("icons/ok") is None  # no return value contract


def test_resolve_normalizes_separators(tmp_path):
    repo = TemplateRepository(root=tmp_path)
    p = repo.resolve("a\\b/c")
    assert p.suffix == ".png"
    assert "a" in p.parts and "b" in p.parts and "c.png" in p.parts


def test_alpha_template_preserves_channels(tmp_path):
    img = np.zeros((4, 4, 4), dtype=np.uint8)
    img[:, :, 3] = 128
    assert cv2.imwrite(str(tmp_path / "x.png"), img)
    repo = TemplateRepository(root=tmp_path)
    arr = repo.get("x")
    assert arr.shape == (4, 4, 4)
