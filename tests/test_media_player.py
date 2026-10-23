"""Media player + launch_app/send_key against a set-up entry (app 0.29.0) and an older TV."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pipup.const import DOMAIN

NEW = {
    "app": "PiPup", "version": "0.29.0", "id": "new", "name": "New TV", "visible": False,
    "screenOn": True, "power": {"canWake": True, "canSleep": True, "sleepMethod": "device_admin"},
    "control": {"launch": True, "keys": ["play_pause", "play", "pause", "stop", "next", "previous"],
                "lastLaunched": None},
    "volume": {"level": 40, "step": 6, "max": 15, "muted": False, "fixed": False},
}
OLD = {"app": "PiPup", "version": "0.28.0", "id": "old", "name": "Old TV", "visible": False, "screenOn": True}
APPS = [
    {"package": "com.netflix.ninja", "label": "Netflix", "tv": True},
    {"package": "com.android.settings", "label": "Settings", "tv": False},
]


@pytest.fixture
async def tvs(hass: HomeAssistant):
    states = {"192.168.1.21": NEW, "192.168.1.22": OLD}
    client = {
        "launch": AsyncMock(return_value={"ok": True}),
        "key": AsyncMock(return_value={"ok": True}),
        "volume": AsyncMock(return_value={"ok": True}),
    }

    async def state(self):
        return dict(states[self.host])

    async def settings(self, **values):
        return {}

    async def apps(self):
        return list(APPS)

    def bound(name):
        async def call(self, *args, **kwargs):
            return await client[name](self.host, *args, **kwargs)
        return call

    entries = {}
    for host, tv in states.items():
        entry = MockConfigEntry(domain=DOMAIN, title=tv["name"], unique_id=tv["id"],
                                data={"host": host, "port": 7979}, options={"update_source": "off"})
        entry.add_to_hass(hass)
        entries[host] = entry
    with patch.multiple(
        "custom_components.pipup.api.PiPupClient",
        state=state, settings=settings, apps=apps,
        launch=bound("launch"), key=bound("key"), volume=bound("volume"),
    ):
        assert await hass.config_entries.async_setup(entries["192.168.1.21"].entry_id)
        await hass.async_block_till_done()
        for entry in entries.values():
            entry.runtime_data.async_refresh_soon = AsyncMock()
        yield entries, client


def _player_id(hass: HomeAssistant, unique: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("media_player", DOMAIN, f"{unique}_media_player")


async def test_player_only_on_new_app(hass: HomeAssistant, tvs) -> None:
    assert _player_id(hass, "new") is not None
    assert _player_id(hass, "old") is None


async def test_player_sources_and_actions(hass: HomeAssistant, tvs) -> None:
    _, client = tvs
    entity_id = _player_id(hass, "new")
    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["source_list"] == ["Netflix"]  # TV apps only
    assert state.attributes["volume_level"] == 0.4

    await hass.services.async_call("media_player", "select_source",
                                   {"entity_id": entity_id, "source": "Netflix"}, blocking=True)
    client["launch"].assert_awaited_with("192.168.1.21", package="com.netflix.ninja")

    await hass.services.async_call("media_player", "volume_set",
                                   {"entity_id": entity_id, "volume_level": 0.25}, blocking=True)
    client["volume"].assert_awaited_with("192.168.1.21", level=25)

    await hass.services.async_call("media_player", "media_play_pause", {"entity_id": entity_id}, blocking=True)
    client["key"].assert_awaited_with("192.168.1.21", "play_pause")


async def test_services_gate_old_app(hass: HomeAssistant, tvs) -> None:
    entries, client = tvs
    with patch(
        "custom_components.pipup.services.async_extract_config_entry_ids",
        AsyncMock(return_value=[e.entry_id for e in entries.values()]),
    ):
        with pytest.raises(HomeAssistantError, match="Old TV: TV control needs PiPup app 0.29.0"):
            await hass.services.async_call(DOMAIN, "send_key", {"key": "next"}, blocking=True)
        # the new TV still got its key
        client["key"].assert_awaited_with("192.168.1.21", "next")

        await hass.services.async_call(
            DOMAIN, "launch_app", {"uri": "https://youtu.be/x"}, blocking=False
        )
        await hass.async_block_till_done()
        client["launch"].assert_awaited_with("192.168.1.21", package=None, uri="https://youtu.be/x", wake=True)
