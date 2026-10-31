"""X1: the foreground app option goes to the app, a sensor follows the pushes."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.pipup.const import DOMAIN

STATE = {
    "app": "PiPup",
    "version": "0.29.2",
    "id": "dev1",
    "name": "Living Room",
    "visible": False,
    "popup": None,
    "popups": [],
    "push": {"supported": True, "webhook": True},
    "foregroundApp": {"enabled": True, "available": True, "package": "com.tcl.tv", "previous": None},
}


async def _setup(hass: HomeAssistant, state: dict, options: dict):
    await hass.config.async_update(internal_url="http://192.168.1.2:8123")
    entry = MockConfigEntry(
        domain=DOMAIN, title="TV", unique_id="dev1",
        data={"host": "192.168.1.14", "port": 7979},
        options={"update_source": "off", **options},
    )
    entry.add_to_hass(hass)
    settings = AsyncMock(return_value={})
    patcher = patch.multiple(
        "custom_components.pipup.api.PiPupClient",
        state=AsyncMock(return_value=dict(state)),
        settings=settings,
    )
    patcher.start()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, settings, patcher


async def test_foreground_sensor_and_push(hass: HomeAssistant, hass_client_no_auth) -> None:
    entry, settings, patcher = await _setup(hass, STATE, {"foreground_app": True})
    try:
        assert any(c.kwargs.get("foregroundApp") == "true" for c in settings.call_args_list)
        entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, "dev1_foreground_app")
        assert hass.states.get(entity_id).state == "com.tcl.tv"

        webhook_url = next(
            c.kwargs["webhook"] for c in settings.call_args_list if "webhook" in c.kwargs
        )
        events = async_capture_events(hass, "pipup_event")
        client = await hass_client_no_auth()
        pushed = {
            **STATE,
            "foregroundApp": {**STATE["foregroundApp"], "package": "com.netflix.ninja",
                              "previous": "com.tcl.tv"},
            "event": "foreground_app",
            "package": "com.netflix.ninja",
            "previous": "com.tcl.tv",
        }
        resp = await client.post(webhook_url.removeprefix("http://192.168.1.2:8123"), json=pushed)
        assert resp.status == 200
        await hass.async_block_till_done()
    finally:
        patcher.stop()

    state = hass.states.get(entity_id)
    assert state.state == "com.netflix.ninja"
    assert state.attributes["previous"] == "com.tcl.tv"
    assert (events[0].data["package"], events[0].data["previous"]) == ("com.netflix.ninja", "com.tcl.tv")


async def test_option_off_sends_false_and_no_sensor(hass: HomeAssistant) -> None:
    _, settings, patcher = await _setup(hass, STATE, {})
    patcher.stop()
    assert any(c.kwargs.get("foregroundApp") == "false" for c in settings.call_args_list)
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, "dev1_foreground_app") is None


async def test_older_app_gets_nothing(hass: HomeAssistant) -> None:
    old = dict(STATE)
    old.pop("foregroundApp")
    _, settings, patcher = await _setup(hass, old, {"foreground_app": True})
    patcher.stop()
    assert not any("foregroundApp" in c.kwargs for c in settings.call_args_list)
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, "dev1_foreground_app") is None
