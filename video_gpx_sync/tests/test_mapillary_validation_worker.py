from app.mapillary_validation_dialog import MapillaryValidationDialog
from app.mapillary_validation_worker import MapillaryValidationWorker
from app.mapillary_validator import ValidationResult


def _fake_validate_export_success(video_path, video_start_time, should_cancel=None):
    return ValidationResult(ok=True, n_images=4, errors=[], warnings=[])


def _fake_validate_export_cancel(video_path, video_start_time, should_cancel=None):
    return None


def test_worker_emits_finished_validation_with_result(qtbot):
    worker = MapillaryValidationWorker(
        "video.mp4", "2026_07_12_01_00_00_000",
        validate_export_impl=_fake_validate_export_success,
    )
    with qtbot.waitSignal(worker.finished_validation, timeout=5000) as blocker:
        worker.start()
    worker.wait()

    result = blocker.args[0]
    assert result.ok is True
    assert result.n_images == 4


def test_worker_emits_none_when_cancelled(qtbot):
    worker = MapillaryValidationWorker(
        "video.mp4", "2026_07_12_01_00_00_000",
        validate_export_impl=_fake_validate_export_cancel,
    )
    with qtbot.waitSignal(worker.finished_validation, timeout=5000) as blocker:
        worker.start()
    worker.wait()

    assert blocker.args[0] is None


def test_dialog_cancel_button_calls_worker_request_cancel(qtbot):
    worker = MapillaryValidationWorker(
        "video.mp4", "2026_07_12_01_00_00_000",
        validate_export_impl=_fake_validate_export_success,
    )
    calls = []
    worker.request_cancel = lambda: calls.append("cancel")

    dialog = MapillaryValidationDialog(worker)
    qtbot.addWidget(dialog)

    dialog.cancel_button.click()

    assert calls == ["cancel"]


def test_dialog_closes_automatically_when_worker_finishes(qtbot):
    worker = MapillaryValidationWorker(
        "video.mp4", "2026_07_12_01_00_00_000",
        validate_export_impl=_fake_validate_export_success,
    )
    dialog = MapillaryValidationDialog(worker)
    qtbot.addWidget(dialog)

    with qtbot.waitSignal(dialog.finished, timeout=5000):
        worker.start()
    worker.wait()
