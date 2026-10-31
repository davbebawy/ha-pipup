"""Y10: grants a reinstall reset are set back over ADB when the option is on."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pipup.adb import PiPupAdb
from custom_components.pipup.const import DOMAIN
from custom_components.pipup.coordinator import missing_grants

ACCESS = "nl.rogro82.pipup/nl.rogro82.pipup.PiPupAccessibilityService"
OK = {"overlay": True, "installPackages": True, "autoStart": True, "accessibility": True}
STATE = {
    "app": "PiPup",
    "version": "0.29.2",
    "id": "dev1",
    "name": "Living Room",
    "visible": False,
    "popup": None,
    "permissions": dict(OK),
    "update": {"installing": False, "phase": None},
}


def test_missing_grants() -> None:
    """Only grants ADB can set; None = the device has none; accessibility only if it was on."""
    assert missing_grants(OK, True) == []
    lost = {"overlay": False, "installPackages": False, "autoStart": None, "accessibility": False}
    assert missing_grants(lost, False) == ["overlay", "installPackages"]
    assert missing_grants(lost, True) == ["overlay", "installPackages", "accessibility"]
    assert missing_grants(None, True) == []


def _fake_adb() -> MagicMock:
    adb = MagicMock()
    adb.__aenter__ = AsyncMock(return_value=adb)
    adb.__aexit__ = AsyncMock(return_value=None)
    adb.connect = AsyncMock()
    adb.regrant = AsyncMock()
    return adb


async def _setup(hass: HomeAssistant, tv: dict, options: dict):
    entry = MockConfigEntry(
        domain=DOMAIN, title="TV", unique_id="dev1",
        data={"host": "192.168.1.14", "port": 7979},
        options={"update_source": "off", **options},
    )
    entry.add_to_hass(hass)
    patcher = patch.multiple(
        "custom_components.pipup.api.PiPupClient",
        state=AsyncMock(side_effect=lambda *_: dict(tv)),
        settings=AsyncMock(return_value={}),
    )
    patcher.start()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, patcher


async def test_lost_grants_set_back_once(hass: HomeAssistant) -> None:
    """After a reinstall: one ADB heal (with accessibility, it was on), then quiet."""
    tv = dict(STATE)
    entry, patcher = await _setup(hass, tv, {"adb_regrant": True})
    adb = _fake_adb()
    try:
        coordinator = entry.runtime_data
        with (
            patch("custom_components.pipup.coordinator.PiPupAdb", return_value=adb),
            patch("custom_components.pipup.coordinator.POST_CALL_SETTLE_SECONDS", 0),
        ):
            tv["permissions"] = {**OK, "overlay": False, "accessibility": False}
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            adb.connect.assert_awaited_once()
            adb.regrant.assert_awaited_once_with(accessibility=True)
            assert coordinator.last_regrant == {
                "missing": ["overlay", "accessibility"], "result": "ok"
            }
            # still missing (the TV refused): never the same round again, also later
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            coordinator._regrant_at -= 3600
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            assert adb.regrant.await_count == 1
            # all back, then lost again (the next reinstall): a new round
            tv["permissions"] = dict(OK)
            await coordinator.async_refresh()
            tv["permissions"] = {**OK, "overlay": False}
            coordinator._regrant_at -= 3600
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            assert adb.regrant.await_count == 2
    finally:
        patcher.stop()


async def test_option_off_or_update_running_no_adb(hass: HomeAssistant) -> None:
    """Off by default; and never during an app update (it sets the grants itself)."""
    tv = {**STATE, "permissions": {**OK, "overlay": False}}
    entry, patcher = await _setup(hass, tv, {})
    adb = _fake_adb()
    try:
        with patch("custom_components.pipup.coordinator.PiPupAdb", return_value=adb):
            await entry.runtime_data.async_refresh()
            await hass.async_block_till_done()
            adb.connect.assert_not_awaited()
    finally:
        patcher.stop()

    tv2 = {**STATE, "permissions": {**OK, "overlay": False},
           "update": {"installing": True, "phase": "installing"}}
    hass2_entry = MockConfigEntry(
        domain=DOMAIN, title="TV2", unique_id="dev2",
        data={"host": "192.168.1.15", "port": 7979},
        options={"update_source": "off", "adb_regrant": True},
    )
    hass2_entry.add_to_hass(hass)
    with (
        patch.multiple(
            "custom_components.pipup.api.PiPupClient",
            state=AsyncMock(side_effect=lambda *_: {**tv2, "id": "dev2"}),
            settings=AsyncMock(return_value={}),
        ),
        patch("custom_components.pipup.coordinator.PiPupAdb", return_value=adb),
    ):
        assert await hass.config_entries.async_setup(hass2_entry.entry_id)
        await hass.async_block_till_done()
        adb.connect.assert_not_awaited()


async def test_adb_failure_is_recorded(hass: HomeAssistant) -> None:
    """A TV that does not trust HA: logged and kept for diagnostics, no refresh loop."""
    from custom_components.pipup.adb import AdbError

    tv = {**STATE, "permissions": {**OK, "installPackages": False}}
    adb = _fake_adb()
    adb.connect.side_effect = AdbError("not_authorized")
    with patch("custom_components.pipup.coordinator.PiPupAdb", return_value=adb):
        entry, patcher = await _setup(hass, tv, {"adb_regrant": True})
        patcher.stop()
    assert entry.runtime_data.last_regrant == {"missing": ["installPackages"], "result": "not_authorized"}


async def test_regrant_writes_accessibility_twice_when_it_does_not_stick(hass: HomeAssistant) -> None:
    """The first settings put after an install may not stick: read back, write again."""
    calls: list[str] = []
    reads = iter(["null", "null", ACCESS])

    async def shell(command, **_):
        calls.append(command)
        return next(reads) if command.startswith("settings get") else ""

    device = MagicMock()
    device.connect = AsyncMock()
    device.close = AsyncMock()
    device.shell = AsyncMock(side_effect=shell)
    with (
        patch("custom_components.pipup.adb.AdbDeviceAsync", return_value=device),
        patch("custom_components.pipup.adb.async_get_signer", AsyncMock(return_value=object())),
    ):
        adb = PiPupAdb(hass, "192.168.1.14", {})
        await adb.connect(1)
    await adb.regrant(accessibility=True)
    puts = [c for c in calls if c.startswith("settings put secure enabled_accessibility_services")]
    assert puts == [f"settings put secure enabled_accessibility_services {ACCESS}"] * 2
    assert "appops set nl.rogro82.pipup SYSTEM_ALERT_WINDOW allow" in calls

    calls.clear()
    await adb.regrant(accessibility=False)
    assert not any(c.startswith("settings") for c in calls)


async def test_turning_regrant_on_tests_adb(hass: HomeAssistant) -> None:
    """Saving the option on tests the ADB connection, also with the app's own update."""
    entry, patcher = await _setup(hass, dict(STATE), {})
    test = AsyncMock(return_value="adb_cannot_connect")
    try:
        with patch("custom_components.pipup.config_flow.PiPupOptionsFlow._test_adb", test):
            result = await hass.config_entries.options.async_init(entry.entry_id)
            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                {"advanced_install": {"install_method": "app", "adb_port": 5555,
                                      "adb_key": "own", "adb_regrant": True}},
            )
        assert result["errors"] == {"base": "adb_cannot_connect"}
        test.assert_awaited_once()
        assert not entry.options.get("adb_regrant")
    finally:
        patcher.stop()
