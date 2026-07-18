from app.mapillary_upload_dialog import MapillaryUploadDialog
from app.mapillary_upload_worker import MapillaryUploadWorker
from app.mapillary_validator import UploadResult


def _fake_upload_export_success(video_path, video_start_time, user_name=None, should_cancel=None):
    return UploadResult(ok=True, errors=[], warnings=[])


def _fake_upload_export_cancel(video_path, video_start_time, user_name=None, should_cancel=None):
    return None


def test_worker_emits_finished_upload_with_result(qtbot):
    worker = MapillaryUploadWorker(
        "video.mp4", "2026_07_12_01_00_00_000",
        upload_export_impl=_fake_upload_export_success,
    )
    with qtbot.waitSignal(worker.finished_upload, timeout=5000) as blocker:
        worker.start()
    worker.wait()

    result = blocker.args[0]
    assert result.ok is True


def test_worker_passes_user_name_through(qtbot):
    received = {}

    def fake_upload(video_path, video_start_time, user_name=None, should_cancel=None):
        received["user_name"] = user_name
        return UploadResult(ok=True, errors=[], warnings=[])

    worker = MapillaryUploadWorker(
        "video.mp4", "2026_07_12_01_00_00_000",
        user_name="alice",
        upload_export_impl=fake_upload,
    )
    with qtbot.waitSignal(worker.finished_upload, timeout=5000):
        worker.start()
    worker.wait()

    assert received["user_name"] == "alice"


def test_worker_emits_none_when_cancelled(qtbot):
    worker = MapillaryUploadWorker(
        "video.mp4", "2026_07_12_01_00_00_000",
        upload_export_impl=_fake_upload_export_cancel,
    )
    with qtbot.waitSignal(worker.finished_upload, timeout=5000) as blocker:
        worker.start()
    worker.wait()

    assert blocker.args[0] is None


def test_dialog_cancel_button_calls_worker_request_cancel(qtbot):
    worker = MapillaryUploadWorker(
        "video.mp4", "2026_07_12_01_00_00_000",
        upload_export_impl=_fake_upload_export_success,
    )
    calls = []
    worker.request_cancel = lambda: calls.append("cancel")

    dialog = MapillaryUploadDialog(worker)
    qtbot.addWidget(dialog)

    dialog.cancel_button.click()

    assert calls == ["cancel"]


def test_dialog_closes_automatically_when_worker_finishes(qtbot):
    worker = MapillaryUploadWorker(
        "video.mp4", "2026_07_12_01_00_00_000",
        upload_export_impl=_fake_upload_export_success,
    )
    dialog = MapillaryUploadDialog(worker)
    qtbot.addWidget(dialog)

    with qtbot.waitSignal(dialog.finished, timeout=5000):
        worker.start()
    worker.wait()
