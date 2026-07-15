import pytest

from app.offset_widget import OffsetWidget, format_offset


def test_format_offset_positive() -> None:
    assert format_offset(12) == "+00:12"


def test_format_offset_negative() -> None:
    assert format_offset(-90) == "-01:30"


def test_format_offset_zero() -> None:
    assert format_offset(0) == "+00:00"


@pytest.fixture
def widget(qtbot) -> OffsetWidget:
    w = OffsetWidget()
    qtbot.addWidget(w)
    return w


@pytest.mark.parametrize(
    "step_seconds", [-600.0, -60.0, -10.0, -1.0, 1.0, 10.0, 60.0, 600.0]
)
def test_each_button_emits_correct_delta(
    widget: OffsetWidget, qtbot, step_seconds: float
) -> None:
    with qtbot.waitSignal(widget.offset_changed, timeout=1000) as blocker:
        widget.step_buttons[step_seconds].click()
    assert blocker.args[0] == step_seconds
    assert widget.offset_seconds() == step_seconds


def test_offset_accumulates_across_clicks(widget: OffsetWidget) -> None:
    widget.step_buttons[10.0].click()
    widget.step_buttons[10.0].click()
    widget.step_buttons[-1.0].click()
    assert widget.offset_seconds() == 19.0
    assert widget.offset_label.text() == "+00:19"


def test_reset_returns_to_zero_and_emits(widget: OffsetWidget, qtbot) -> None:
    widget.step_buttons[60.0].click()
    widget.step_buttons[600.0].click()
    assert widget.offset_seconds() == 660.0

    with qtbot.waitSignal(widget.offset_changed, timeout=1000) as blocker:
        widget.reset_button.click()

    assert blocker.args[0] == 0.0
    assert widget.offset_seconds() == 0.0
    assert widget.offset_label.text() == "+00:00"


def test_negative_offset_label_format(widget: OffsetWidget) -> None:
    widget.step_buttons[-60.0].click()
    widget.step_buttons[-10.0].click()
    assert widget.offset_seconds() == -70.0
    assert widget.offset_label.text() == "-01:10"


def test_set_offset_overwrites_regardless_of_current_value(
    widget: OffsetWidget, qtbot
) -> None:
    widget.step_buttons[600.0].click()
    widget.step_buttons[600.0].click()
    assert widget.offset_seconds() == 1200.0

    with qtbot.waitSignal(widget.offset_changed, timeout=1000) as blocker:
        widget.set_offset(-345.0)

    assert blocker.args[0] == -345.0
    assert widget.offset_seconds() == -345.0
    assert widget.offset_label.text() == "-05:45"


def test_force_sync_button_exists_next_to_reset(widget: OffsetWidget) -> None:
    assert widget.force_sync_button.text() == "強制同期"
