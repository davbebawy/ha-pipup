"""Video media height (newer apps): sent only when the call sets media_height."""
from __future__ import annotations

from custom_components.pipup.services import build_device_payload

STREAM = "http://ha/api/hls/x/master_playlist.m3u8"


def _video(data: dict, opts: dict | None = None, stream: str | None = STREAM) -> dict:
    payload = build_device_payload({"title": "t", **data}, opts or {}, stream)
    return payload["media"]["video"]


def test_camera_popup_without_height_sends_none() -> None:
    assert "height" not in _video({})


def test_camera_popup_sends_explicit_height() -> None:
    assert _video({"media_height": 480})["height"] == 480


def test_device_default_height_is_not_sent_for_video() -> None:
    assert "height" not in _video({}, {"default_media_height": 360})


def test_video_url_sends_explicit_height() -> None:
    assert _video({"video_url": "rtsp://cam/1", "media_height": 480}, stream=None)["height"] == 480
