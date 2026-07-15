import datetime

import gpxpy.gpx

from app.map_matching_dialog import MapMatchingDialog
from app.map_matching_worker import MapMatchingWorker

UTC = datetime.timezone.utc


def _points() -> list[gpxpy.gpx.GPXTrackPoint]:
    t0 = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)
    return [
        gpxpy.gpx.GPXTrackPoint(
            latitude=35.0,
            longitude=135.0 + i * 0.01,  # ジグザグ要素を入れて間引かれ過ぎないようにする
            elevation=10.0 + i,
            time=t0 + datetime.timedelta(seconds=i),
        )
        for i in range(3)
    ]


def _fake_match_chunk(chunk):
    return {
        "matched_points": [
            {"lat": lat + 0.001, "lon": lon, "type": "matched"} for lat, lon in chunk
        ]
    }


def test_worker_emits_finished_matching_with_result(qtbot):
    worker = MapMatchingWorker(_points(), match_chunk_impl=_fake_match_chunk)
    with qtbot.waitSignal(worker.finished_matching, timeout=5000) as blocker:
        worker.start()
    worker.wait()

    result = blocker.args[0]
    assert result.status == "完了"
    assert len(result.points) >= 2
    assert result.points[0].time == _points()[0].time


def test_worker_request_cancel_before_start_results_in_cancelled(qtbot):
    worker = MapMatchingWorker(_points(), match_chunk_impl=_fake_match_chunk)
    worker.request_cancel()
    with qtbot.waitSignal(worker.finished_matching, timeout=5000) as blocker:
        worker.start()
    worker.wait()

    result = blocker.args[0]
    assert result.status == "キャンセル"


def test_dialog_cancel_button_calls_worker_request_cancel(qtbot):
    worker = MapMatchingWorker(_points(), match_chunk_impl=_fake_match_chunk)
    # ダイアログのconnect()がボタンクリックに束縛するのはコンストラクタ実行時点の
    # request_cancelなので、差し替えはMapMatchingDialog生成前に行う必要がある
    calls = []
    worker.request_cancel = lambda: calls.append("cancel")

    dialog = MapMatchingDialog(worker)
    qtbot.addWidget(dialog)

    dialog.cancel_button.click()

    assert calls == ["cancel"]


def test_dialog_closes_automatically_when_worker_finishes(qtbot):
    worker = MapMatchingWorker(_points(), match_chunk_impl=_fake_match_chunk)
    dialog = MapMatchingDialog(worker)
    qtbot.addWidget(dialog)

    with qtbot.waitSignal(dialog.finished, timeout=5000):
        worker.start()
    worker.wait()
