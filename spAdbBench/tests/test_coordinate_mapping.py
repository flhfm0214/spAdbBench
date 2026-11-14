from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect, QSize

from adbtool.channels.scrcpy_control import map_click


def test_letterbox_mapping_ignores_bars():
    image = QRect(0, 0, 1000, 500)
    widget = QSize(400, 400)

    assert map_click(QPoint(200, 200), widget, image) == pytest.approx((0.5, 0.5))
    assert map_click(QPoint(200, 20), widget, image) is None
    assert map_click(QPoint(10, 200), widget, image) == pytest.approx((0.025, 0.5))


def test_pillarbox_mapping_ignores_side_bars():
    image = QRect(0, 0, 500, 1000)
    widget = QSize(400, 400)

    assert map_click(QPoint(20, 200), widget, image) is None
    assert map_click(QPoint(200, 200), widget, image) == pytest.approx((0.5, 0.5))
    assert map_click(QPoint(200, 10), widget, image) == pytest.approx((0.5, 0.025))


def test_zero_size_image_returns_none():
    assert map_click(QPoint(1, 1), QSize(400, 400), QRect(0, 0, 0, 0)) is None
    assert map_click(QPoint(1, 1), QSize(0, 0), QRect(0, 0, 100, 100)) is None
