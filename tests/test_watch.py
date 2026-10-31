"""TV state push: the watch list goes to the app, one sensor per key, pushes update it."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.pipup.config_flow import parse_watch
from custom_components.pipup.const import DOMAIN

WATCH = "prop:sys.tcl.inputid,system:recent_play_channel_id"
STATE = {
    "app": "PiPup",
    "version": "0.29.2",
    "id": "dev1",
    "name": "Living Room",
    "visible": False,
    "popup": None,
    "popups": [],
    "push": {"supported": True, "webhook": True},
    "watch": {
        "keys": WATCH.split(","),
        "values": {"prop:sys.tcl.inputid": "HDMI1", "system:recent_play_channel_id": None},
        "errors": {"system:recent_play_channel_id": "SecurityException: not readable"},
    },
}


def test_parse_watch() -> None:
    """Same syntax as the app; kinds lowercased, duplicates and blanks dropped."""
    assert parse_watch(" PROP:a.b , system:c,,prop:a.b") == ["prop:a.b", "system:c"]
    assert parse_watch("") == [] and parse_watch(None) == []
    for bad in ("a.b", "vendor:x", "prop:", "prop:a b", "secure:a;b"):
        with pytest.raises(ValueError):
            parse_watch(bad)
    with pytest.raises(ValueError):
        parse_watch(",".join(f"prop:p{i}" for i in range(33)))


async def test_watch_sensors_and_push(hass: HomeAssistant, hass_client_no_auth) -> None:
    await hass.config.async_update(internal_url="http://192.168.1.2:8123")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="TV",
        unique_id="dev1",
        data={"host": "192.168.1.14", "port": 7979},
        options={"update_source": "off", "watch": WATCH},
    )
    entry.add_to_hass(hass)
    settings = AsyncMock(return_value={})
    with patch.multiple(
        "custom_components.pipup.api.PiPupClient",
        state=AsyncMock(return_value=dict(STATE)),
        settings=settings,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert any(c.kwargs.get("watch") == WATCH for c in settings.call_args_list)
        registry = er.async_get(hass)
        input_id = registry.async_get_entity_id("sensor", DOMAIN, "dev1_watch_prop:sys.tcl.inputid")
        channel = registry.async_get_entity_id(
            "sensor", DOMAIN, "dev1_watch_system:recent_play_channel_id"
        )
        assert hass.states.get(input_id).state == "HDMI1"
        assert hass.states.get(channel).attributes["error"].startswith("SecurityException")

        webhook_url = next(
            c.kwargs["webhook"] for c in settings.call_args_list if "webhook" in c.kwargs
        )
        events = async_capture_events(hass, "pipup_event")
        client = await hass_client_no_auth()
        pushed = {
            **STATE,
            "watch": {**STATE["watch"], "values": {**STATE["watch"]["values"], "prop:sys.tcl.inputid": "TV"}},
            "event": "watch",
            "key": "prop:sys.tcl.inputid",
            "old": "HDMI1",
            "new": "TV",
        }
        resp = await client.post(webhook_url.removeprefix("http://192.168.1.2:8123"), json=pushed)
        assert resp.status == 200
        await hass.async_block_till_done()

    assert hass.states.get(input_id).state == "TV"
    assert len(events) == 1
    data = events[0].data
    assert (data["event"], data["key"], data["old"], data["new"]) == (
        "watch", "prop:sys.tcl.inputid", "HDMI1", "TV"
    )
    assert "kind" in data and data["kind"] is None


async def test_no_watch_in_app_no_sensors(hass: HomeAssistant) -> None:
    """An app without watch gets no watch setting and no sensors."""
    await hass.config.async_update(internal_url="http://192.168.1.2:8123")
    entry = MockConfigEntry(
        domain=DOMAIN, title="TV", unique_id="dev1",
        data={"host": "192.168.1.14", "port": 7979},
        options={"update_source": "off", "watch": WATCH},
    )
    entry.add_to_hass(hass)
    old = dict(STATE)
    old.pop("watch")
    settings = AsyncMock(return_value={})
    with patch.multiple(
        "custom_components.pipup.api.PiPupClient",
        state=AsyncMock(return_value=old),
        settings=settings,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert not any("watch" in c.kwargs for c in settings.call_args_list)
    assert er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, "dev1_watch_prop:sys.tcl.inputid"
    ) is None


async def test_popup_event_has_no_watch_fields(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Other events keep their old shape."""
    await hass.config.async_update(internal_url="http://192.168.1.2:8123")
    entry = MockConfigEntry(
        domain=DOMAIN, title="TV", unique_id="dev1",
        data={"host": "192.168.1.14", "port": 7979}, options={"update_source": "off"},
    )
    entry.add_to_hass(hass)
    settings = AsyncMock(return_value={})
    with patch.multiple(
        "custom_components.pipup.api.PiPupClient",
        state=AsyncMock(return_value=dict(STATE)),
        settings=settings,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        webhook_url = next(
            c.kwargs["webhook"] for c in settings.call_args_list if "webhook" in c.kwargs
        )
        events = async_capture_events(hass, "pipup_event")
        client = await hass_client_no_auth()
        await client.post(
            webhook_url.removeprefix("http://192.168.1.2:8123"),
            json={**STATE, "event": "job", "kind": "screencap", "run": "r1", "result": "ok"},
        )
        await client.post(
            webhook_url.removeprefix("http://192.168.1.2:8123"),
            json={**STATE, "event": "screen_off"},
        )
        await hass.async_block_till_done()
    assert events[0].data["kind"] == "screencap" and events[0].data["result"] == "ok"
    assert "key" not in events[1].data and "kind" not in events[1].data
