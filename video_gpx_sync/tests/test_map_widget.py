import socket
from unittest.mock import Mock

import pytest
from PySide6.QtQuickWidgets import QQuickWidget

from app.map_widget import MapWidget


def _network_available() -> bool:
    try:
        socket.create_connection(("tile.openstreetmap.org", 443), timeout=3).close()
        return True
    except OSError:
        return False


NETWORK_AVAILABLE = _network_available()


@pytest.fixture
def widget(qtbot):
    w = MapWidget()
    qtbot.addWidget(w)
    return w


def test_calls_are_queued_before_ready(widget, monkeypatch) -> None:
    mock_root = Mock()
    monkeypatch.setattr(widget, "rootObject", lambda: mock_root)
    widget._is_ready = False
    widget._pending_calls = []

    widget.update_marker(35.0, 135.0)

    mock_root.updateMarker.assert_not_called()
    assert widget._pending_calls == [("updateMarker", (35.0, 135.0))]


def test_pending_calls_flush_on_ready(widget, monkeypatch) -> None:
    mock_root = Mock()
    monkeypatch.setattr(widget, "rootObject", lambda: mock_root)
    widget._is_ready = False
    widget._pending_calls = []

    widget.update_marker(35.0, 135.0)
    widget.hide_marker()
    widget._on_status_changed(QQuickWidget.Status.Ready)

    mock_root.updateMarker.assert_called_once_with(35.0, 135.0)
    mock_root.hideMarker.assert_called_once_with()
    assert widget._pending_calls == []


def test_calls_run_immediately_when_ready(widget, monkeypatch) -> None:
    mock_root = Mock()
    monkeypatch.setattr(widget, "rootObject", lambda: mock_root)
    widget._is_ready = True

    widget.load_gpx_route([(35.0, 135.0), (35.001, 135.001)])
    widget.update_route_ranges([True, False])
    widget.hide_marker()
    widget.clear()

    mock_root.loadRoute.assert_called_once_with([[35.0, 135.0], [35.001, 135.001]])
    mock_root.updateRouteRanges.assert_called_once_with([True, False])
    mock_root.hideMarker.assert_called_once_with()
    mock_root.clearMap.assert_called_once_with()


def test_status_changed_non_ready_does_not_mark_ready(widget) -> None:
    widget._is_ready = False
    widget._on_status_changed(QQuickWidget.Status.Loading)
    assert widget._is_ready is False


@pytest.mark.skipif(
    not NETWORK_AVAILABLE, reason="requires network access to tile.openstreetmap.org"
)
def test_real_qml_load_exposes_map_functions(widget) -> None:
    # QQuickWidgetはローカルQMLファイルの場合setSource()が同期的に
    # Readyへ遷移するため（QWebEngineViewのloadFinishedのような非同期
    # 待ちは不要）、fixture生成時点で既にready済みであることを確認する。
    assert widget._is_ready is True
    root = widget.rootObject()
    assert root is not None
    for name in ("loadRoute", "updateRouteRanges", "updateMarker", "hideMarker", "clearMap"):
        assert hasattr(root, name)
