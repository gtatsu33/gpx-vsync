import json
import socket

import pytest

from app.map_widget import MapWidget


def _network_available() -> bool:
    try:
        socket.create_connection(("unpkg.com", 443), timeout=3).close()
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
    calls = []
    monkeypatch.setattr(
        widget.page(), "runJavaScript", lambda script, *a, **k: calls.append(script)
    )

    widget.update_marker(35.0, 135.0)

    assert calls == []
    assert widget._pending_calls == ["updateMarker(35.0, 135.0);"]


def test_pending_calls_flush_on_ready(widget, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        widget.page(), "runJavaScript", lambda script, *a, **k: calls.append(script)
    )

    widget.update_marker(35.0, 135.0)
    widget.hide_marker()
    widget._on_load_finished(True)

    assert calls == ["updateMarker(35.0, 135.0);", "hideMarker();"]
    assert widget._pending_calls == []


def test_calls_run_immediately_when_ready(widget, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        widget.page(), "runJavaScript", lambda script, *a, **k: calls.append(script)
    )
    widget._is_ready = True

    widget.load_gpx_route([(35.0, 135.0), (35.001, 135.001)])
    widget.update_route_ranges([True, False])
    widget.hide_marker()
    widget.clear()

    expected_latlngs = json.dumps([[35.0, 135.0], [35.001, 135.001]])
    assert calls[0] == f"loadRoute({expected_latlngs});"
    assert calls[1] == "updateRouteRanges([true, false]);"
    assert calls[2] == "hideMarker();"
    assert calls[3] == "clearMap();"


def test_load_finished_false_does_not_mark_ready(widget) -> None:
    widget._on_load_finished(False)
    assert widget._is_ready is False


@pytest.mark.skipif(
    not NETWORK_AVAILABLE, reason="requires network access to unpkg.com CDN"
)
def test_real_page_load_and_leaflet_available(widget, qtbot) -> None:
    with qtbot.waitSignal(widget.map_ready, timeout=15000):
        pass

    result: dict = {}

    def callback(value):
        result["leaflet_loaded"] = value

    widget.page().runJavaScript(
        "typeof L !== 'undefined' && typeof map !== 'undefined'", callback
    )
    qtbot.waitUntil(lambda: "leaflet_loaded" in result, timeout=5000)
    assert result["leaflet_loaded"] is True
