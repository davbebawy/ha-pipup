"""grid: tile schema, payload shape, full screen defaults and the app-version gate."""
import pytest
import voluptuous as vol

from custom_components.pipup.services import SHOW_SCHEMA, build_device_payload, unsupported_media

URL = "http://g:1984/api/webrtc?src="


def test_tiles_accept_urls_and_mappings() -> None:
    data = SHOW_SCHEMA({"grid": [URL + "a", {"whep_url": URL + "b", "label": "Tuin", "poster_url": "http://f/b.jpg"}]})
    assert data["grid"] == [
        {"uri": URL + "a"},
        {"uri": URL + "b", "label": "Tuin", "poster": "http://f/b.jpg"},
    ]


def test_tiles_are_capped_and_need_a_url() -> None:
    with pytest.raises(vol.Invalid):
        SHOW_SCHEMA({"grid": [URL + str(i) for i in range(10)]})
    with pytest.raises(vol.Invalid):
        SHOW_SCHEMA({"grid": [{"label": "zonder url"}]})


def test_grid_payload() -> None:
    data = SHOW_SCHEMA({"grid": [URL + "a", URL + "b"], "grid_columns": 2, "grid_labels": False})
    payload = build_device_payload(data, {}, None)
    grid = payload["media"]["grid"]
    assert grid == {
        "items": [{"uri": URL + "a"}, {"uri": URL + "b"}],
        "width": 1280, "height": 720, "muted": True, "columns": 2, "labels": False,
    }
    assert "padding" not in payload


def test_fullscreen_centres_without_padding_unless_given() -> None:
    payload = build_device_payload(SHOW_SCHEMA({"grid": [URL + "a"], "grid_fullscreen": True}), {}, None)
    assert payload["media"]["grid"]["fullscreen"] is True
    assert payload["position"] == 4  # center
    assert payload["padding"] == 0

    payload = build_device_payload(
        SHOW_SCHEMA({"grid": [URL + "a"], "grid_fullscreen": True, "position": "top_left", "padding": 10}),
        {}, None,
    )
    assert payload["position"] == 1
    assert payload["padding"] == 10


def test_grid_needs_app_0_29() -> None:
    payload = {"media": {"grid": {"items": []}}}
    assert unsupported_media(payload, "0.28.0") == ("grid", "0.29.0")
    assert unsupported_media(payload, "0.29.0") is None
