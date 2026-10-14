"""Button style (newer apps): each part is sent only when the call sets it."""
from __future__ import annotations

from custom_components.pipup.services import build_device_payload

KEYS = ("buttonColor", "buttonFocusColor", "buttonTextColor", "buttonBorderColor", "buttonCornerRadius")


def _payload(data: dict) -> dict:
    return build_device_payload({"title": "t", **data}, {}, None)


def test_no_button_style_by_default() -> None:
    payload = _payload({})
    assert not any(key in payload for key in KEYS)


def test_button_colors_are_sent() -> None:
    payload = _payload({
        "button_color": "#40FFFFFF",
        "button_focus_color": "#66FFFFFF",
        "button_text_color": "#FFFFFF",
        "button_border_color": "#4DFFFFFF",
    })
    assert payload["buttonColor"] == "#40FFFFFF"
    assert payload["buttonFocusColor"] == "#66FFFFFF"
    assert payload["buttonTextColor"] == "#FFFFFF"
    assert payload["buttonBorderColor"] == "#4DFFFFFF"


def test_zero_corner_radius_is_sent() -> None:
    assert _payload({"button_corner_radius": 0})["buttonCornerRadius"] == 0
