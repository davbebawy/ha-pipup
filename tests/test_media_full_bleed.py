"""Full-bleed media (newer apps): sent only when the call turns it on."""
from __future__ import annotations

from custom_components.pipup.services import build_device_payload


def _payload(data: dict) -> dict:
    return build_device_payload({"title": "t", **data}, {}, None)


def test_no_full_bleed_by_default() -> None:
    assert "mediaFullBleed" not in _payload({})


def test_full_bleed_is_sent() -> None:
    assert _payload({"media_full_bleed": True})["mediaFullBleed"] is True


def test_inline_buttons_are_sent_only_when_on() -> None:
    assert "buttonsInline" not in _payload({})
    assert _payload({"buttons_inline": True})["buttonsInline"] is True
