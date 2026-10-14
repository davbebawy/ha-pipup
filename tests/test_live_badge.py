"""LIVE badge (newer apps): sent only when the call turns it on."""
from __future__ import annotations

from custom_components.pipup.services import build_device_payload


def _payload(data: dict) -> dict:
    return build_device_payload({"title": "t", **data}, {}, None)


def test_no_live_badge_by_default() -> None:
    payload = _payload({})
    assert "liveBadge" not in payload
    assert "liveBadgeColor" not in payload


def test_live_badge_is_sent() -> None:
    assert _payload({"live_badge": True})["liveBadge"] is True


def test_live_badge_color_needs_the_badge() -> None:
    assert "liveBadgeColor" not in _payload({"live_badge_color": "#FF3B30"})
    assert _payload({"live_badge": True, "live_badge_color": "#FF3B30"})["liveBadgeColor"] == "#FF3B30"


def test_live_badge_position_is_sent_with_the_badge() -> None:
    assert _payload({"live_badge": True, "live_badge_position": "top_left"})["liveBadgePosition"] == "top_left"
    assert "liveBadgePosition" not in _payload({"live_badge_position": "top_left"})
