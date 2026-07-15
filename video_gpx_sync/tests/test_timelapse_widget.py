import pytest

from app.timelapse_widget import DEFAULT_INTERVAL_SEC, TimelapseWidget


@pytest.fixture
def widget(qtbot) -> TimelapseWidget:
    w = TimelapseWidget()
    qtbot.addWidget(w)
    return w


def test_initial_state_disabled(widget: TimelapseWidget) -> None:
    assert widget.timelapse_enabled() is False
    assert widget.interval_spinbox.isEnabled() is False
    assert widget.interval_seconds() == pytest.approx(DEFAULT_INTERVAL_SEC)


def test_checking_enables_interval_and_emits(widget: TimelapseWidget, qtbot) -> None:
    with qtbot.waitSignal(widget.timelapse_changed, timeout=1000) as blocker:
        widget.checkbox.setChecked(True)

    assert blocker.args == [True, DEFAULT_INTERVAL_SEC]
    assert widget.interval_spinbox.isEnabled() is True
    assert widget.timelapse_enabled() is True


def test_unchecking_disables_and_emits_false(widget: TimelapseWidget, qtbot) -> None:
    widget.checkbox.setChecked(True)

    with qtbot.waitSignal(widget.timelapse_changed, timeout=1000) as blocker:
        widget.checkbox.setChecked(False)

    assert blocker.args == [False, DEFAULT_INTERVAL_SEC]
    assert widget.interval_spinbox.isEnabled() is False


def test_changing_interval_while_enabled_emits(widget: TimelapseWidget, qtbot) -> None:
    widget.checkbox.setChecked(True)

    with qtbot.waitSignal(widget.timelapse_changed, timeout=1000) as blocker:
        widget.interval_spinbox.setValue(2.0)

    assert blocker.args == [True, 2.0]


def test_changing_interval_while_disabled_does_not_emit(
    widget: TimelapseWidget, qtbot
) -> None:
    received = []
    widget.timelapse_changed.connect(lambda enabled, interval: received.append(enabled))
    widget.interval_spinbox.setValue(3.0)
    qtbot.wait(50)
    assert received == []


def test_reset_returns_to_initial_state(widget: TimelapseWidget, qtbot) -> None:
    widget.checkbox.setChecked(True)
    widget.interval_spinbox.setValue(5.0)

    with qtbot.waitSignal(widget.timelapse_changed, timeout=1000) as blocker:
        widget.reset()

    assert blocker.args == [False, DEFAULT_INTERVAL_SEC]
    assert widget.timelapse_enabled() is False
    assert widget.interval_seconds() == pytest.approx(DEFAULT_INTERVAL_SEC)
