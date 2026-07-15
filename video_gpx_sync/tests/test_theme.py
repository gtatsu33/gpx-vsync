import os

from app.theme import CHECKMARK_ICON_PATH, DARK, LIGHT, build_stylesheet


def test_checkmark_icon_file_exists() -> None:
    assert os.path.isfile(CHECKMARK_ICON_PATH)


def test_build_stylesheet_references_checkmark_icon_for_checked_checkbox() -> None:
    css = build_stylesheet(LIGHT)
    assert f"image: url({CHECKMARK_ICON_PATH})" in css


def test_build_stylesheet_includes_palette_tokens() -> None:
    for palette in (LIGHT, DARK):
        css = build_stylesheet(palette)
        assert palette.accent in css
        assert palette.warn in css
        assert palette.error in css
