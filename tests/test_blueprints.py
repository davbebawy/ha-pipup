"""The shipped blueprints: instantiate them in Home Assistant and check what they send."""
from datetime import timedelta
from pathlib import Path
import shutil

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

REPO = Path(__file__).parent.parent / "blueprints"


def _install(hass: HomeAssistant, kind: str, name: str) -> None:
    target = Path(hass.config.path("blueprints", kind, "ha-pipup"))
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / kind / name, target / name)


def _capture(hass: HomeAssistant) -> list[ServiceCall]:
    calls: list[ServiceCall] = []

    async def show(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("pipup", "show", show)
    return calls


async def test_info_card_script(hass: HomeAssistant) -> None:
    _install(hass, "script", "pipup_info_card.yaml")
    calls = _capture(hass)
    assert await async_setup_component(hass, "script", {"script": {"tv_card": {"use_blueprint": {
        "path": "ha-pipup/pipup_info_card.yaml",
        "input": {"tvs": ["dev1", "dev2"], "duration": 20},
    }}}})
    await hass.services.async_call(
        "script", "tv_card", {"title": "Weer", "message": "14 °C", "urgency": "info"}, blocking=True
    )
    await hass.services.async_call("script", "tv_card", {"message": "Alleen tekst", "duration": 7}, blocking=True)
    await hass.async_block_till_done()
    assert len(calls) == 2
    first, second = (
        {k: v for k, v in c.data.items() if k != "device_id"} for c in calls
    )
    assert calls[0].data["device_id"] == ["dev1", "dev2"]
    assert first == {
        "message": "14 °C", "title": "Weer", "urgency": "info", "position": "top_right",
        "duration": 20, "stack": "vertical", "show_progress": True,
    }
    assert second["duration"] == 7 and "title" not in second and "urgency" not in second
    assert "icon" not in second and "sound" not in second and "popup_id" not in second


# the 5-minute time_pattern trigger stays scheduled until teardown
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_appliance_done(hass: HomeAssistant, freezer) -> None:
    _install(hass, "automation", "pipup_appliance_done.yaml")
    calls = _capture(hass)
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"wm_running": {}}})
    hass.states.async_set("sensor.wm_power", "1", {"device_class": "power", "unit_of_measurement": "W"})
    assert await async_setup_component(hass, "automation", {"automation": {"use_blueprint": {
        "path": "ha-pipup/pipup_appliance_done.yaml",
        "input": {
            "power_sensor": "sensor.wm_power", "running_flag": "input_boolean.wm_running",
            "tvs": ["dev1"], "title": "Wasmachine", "message": "De was is klaar.",
        },
    }}})
    await hass.async_block_till_done()

    async def advance(minutes: float) -> None:
        freezer.tick(timedelta(minutes=minutes))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()

    hass.states.async_set("sensor.wm_power", "1800", {"device_class": "power"})
    await advance(3)
    assert hass.states.get("input_boolean.wm_running").state == "on"

    # a short dip between rinses is not "done"
    hass.states.async_set("sensor.wm_power", "1", {"device_class": "power"})
    await advance(2)
    hass.states.async_set("sensor.wm_power", "400", {"device_class": "power"})
    await advance(1)
    assert calls == []

    hass.states.async_set("sensor.wm_power", "1", {"device_class": "power"})
    await advance(6)
    assert hass.states.get("input_boolean.wm_running").state == "off"
    assert len(calls) == 1
    data = calls[0].data
    assert data["title"] == "Wasmachine" and data["message"] == "De was is klaar."
    assert data["popup_id"] == "appliance_wm_running" and data["duration"] == 60
    assert "icon" not in data

    # nothing more while idle
    await advance(30)
    assert len(calls) == 1


# the 5-minute time_pattern trigger stays scheduled until teardown
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_appliance_done_safety_net(hass: HomeAssistant, freezer) -> None:
    """Flag still on and power already low (the for-timer was lost): the 5-minute check finishes it."""
    _install(hass, "automation", "pipup_appliance_done.yaml")
    calls = _capture(hass)
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"wm_running": {"initial": True}}})
    hass.states.async_set("sensor.wm_power", "1", {"device_class": "power"})
    assert await async_setup_component(hass, "automation", {"automation": {"use_blueprint": {
        "path": "ha-pipup/pipup_appliance_done.yaml",
        "input": {"power_sensor": "sensor.wm_power", "running_flag": "input_boolean.wm_running", "tvs": ["dev1"]},
    }}})
    await hass.async_block_till_done()
    for _ in range(3):  # 15 minutes of 5-minute checks
        freezer.tick(timedelta(minutes=5))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
    assert len(calls) == 1
    assert hass.states.get("input_boolean.wm_running").state == "off"
