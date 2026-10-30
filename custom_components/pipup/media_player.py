"""Media player: launch apps, media keys and volume on the TV (app >= 0.29.0).

PiPup cannot see what is playing or which app is in front (that needs usage access, a
grant a TV has no screen for), so this entity is a remote control, not a now-playing
card: state is the screen (on/off), volume is the TV's media volume, the source list is
the installed apps, and the transport buttons send media keys to whatever app holds the
media session.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import PiPupError, PiPupUnsupportedError
from .const import POWER_STATE_OFF, POWER_STATE_ON
from .coordinator import PiPupCoordinator
from .entity import PiPupEntity

_LOGGER = logging.getLogger(__name__)

# The installed apps rarely change; re-read them at most this often (and on demand
# when a source is not found).
APPS_REFRESH_INTERVAL = timedelta(hours=6)

KEY_FOR_FEATURE = {
    "play": MediaPlayerEntityFeature.PLAY,
    "pause": MediaPlayerEntityFeature.PAUSE,
    "stop": MediaPlayerEntityFeature.STOP,
    "next": MediaPlayerEntityFeature.NEXT_TRACK,
    "previous": MediaPlayerEntityFeature.PREVIOUS_TRACK,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the media player when the app has TV control (0.29.0)."""
    coordinator: PiPupCoordinator = entry.runtime_data
    if isinstance(coordinator.data.get("control"), dict):
        async_add_entities([PiPupMediaPlayer(coordinator, entry)])


def source_apps(apps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The apps worth listing as sources.

    A TV lists its TV apps (LEANBACK_LAUNCHER); phone-launcher entries are mostly
    system tools there. A device without any TV app (a plain-Android projector) lists
    everything. Duplicate labels keep the first, so a source name stays unambiguous.
    """
    tv = [a for a in apps if a.get("tv")]
    chosen = tv or apps
    seen: set[str] = set()
    result = []
    for app in chosen:
        label = str(app.get("label") or app.get("package"))
        if label in seen:
            continue
        seen.add(label)
        result.append({**app, "label": label})
    return result


class PiPupMediaPlayer(PiPupEntity, MediaPlayerEntity):
    """Remote control for the TV: apps, media keys, volume, screen."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.TV

    def __init__(self, coordinator: PiPupCoordinator, entry) -> None:
        """Initialize the media player."""
        super().__init__(coordinator, entry, "media_player")
        self._apps: list[dict[str, Any]] = []
        self._apps_read_at = None

    async def async_added_to_hass(self) -> None:
        """Read the app list once the entity is in place."""
        await super().async_added_to_hass()
        await self._async_refresh_apps()

    async def _async_refresh_apps(self, force: bool = False) -> None:
        now = dt_util.utcnow()
        if (
            not force
            and self._apps_read_at is not None
            and now - self._apps_read_at < APPS_REFRESH_INTERVAL
        ):
            return
        try:
            self._apps = source_apps(await self.coordinator.client.apps())
            self._apps_read_at = now
        except PiPupError as err:
            # a TV in standby (Fire TV sticks drop off the network): keep the old list
            _LOGGER.debug("%s: app list not read: %s", self.entity_id, err)

    def _handle_coordinator_update(self) -> None:
        """Re-read the app list now and then, piggybacking on state updates."""
        if self.coordinator.online and (
            self._apps_read_at is None
            or dt_util.utcnow() - self._apps_read_at >= APPS_REFRESH_INTERVAL
        ):
            self.hass.async_create_task(self._async_refresh_apps())
        super()._handle_coordinator_update()

    # ------------------------------------------------------------ state

    @property
    def _control(self) -> dict[str, Any]:
        value = self.coordinator.data.get("control")
        return value if isinstance(value, dict) else {}

    @property
    def _volume(self) -> dict[str, Any]:
        value = self.coordinator.data.get("volume")
        return value if isinstance(value, dict) else {}

    @property
    def _power(self) -> dict[str, Any]:
        value = self.coordinator.data.get("power")
        return value if isinstance(value, dict) else {}

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """What this TV can do; volume set only where the volume is not fixed."""
        features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.SELECT_SOURCE
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_MUTE
        )
        if self._power.get("canSleep"):
            features |= MediaPlayerEntityFeature.TURN_OFF
        if self._volume and not self._volume.get("fixed"):
            features |= MediaPlayerEntityFeature.VOLUME_SET
        keys = self._control.get("keys") or []
        for key, feature in KEY_FOR_FEATURE.items():
            if key in keys:
                features |= feature
        return features

    @property
    def state(self) -> MediaPlayerState | None:
        """On while the screen is on; off in standby (also when unreachable).

        Fire TV sticks drop off the network in standby, so unreachable reads as off.
        """
        if not self.coordinator.online:
            return MediaPlayerState.OFF
        screen = self.coordinator.data.get("screenOn")
        if screen is None:
            return None
        return MediaPlayerState.ON if screen else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        """Media volume 0..1."""
        level = self._volume.get("level")
        return level / 100 if isinstance(level, (int, float)) else None

    @property
    def is_volume_muted(self) -> bool | None:
        """Whether the media stream is muted."""
        muted = self._volume.get("muted")
        return bool(muted) if muted is not None else None

    @property
    def source_list(self) -> list[str]:
        """Installed apps, by label."""
        return [a["label"] for a in self._apps]

    @property
    def source(self) -> str | None:
        """The app PiPup itself launched last - not necessarily what is on screen."""
        pkg = self._control.get("lastLaunched")
        return next((a["label"] for a in self._apps if a.get("package") == pkg), None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """What the TV reports about its controls."""
        return {
            "keys": self._control.get("keys"),
            "last_launched": self._control.get("lastLaunched"),
            "volume_fixed": self._volume.get("fixed"),
            "volume_steps": self._volume.get("max"),
        }

    # ------------------------------------------------------------ actions

    async def _call(self, coro) -> dict[str, Any]:
        try:
            result = await coro
        except PiPupUnsupportedError as err:
            raise HomeAssistantError(f"{self.entity_id}: this TV cannot do that: {err}") from err
        except PiPupError as err:
            raise HomeAssistantError(f"{self.entity_id}: {err}") from err
        await self.coordinator.async_refresh_soon()
        return result

    async def async_turn_on(self) -> None:
        """Wake the TV."""
        await self._call(self.coordinator.client.power(POWER_STATE_ON))

    async def async_turn_off(self) -> None:
        """Put the TV in standby."""
        await self._call(self.coordinator.client.power(POWER_STATE_OFF))

    async def async_select_source(self, source: str) -> None:
        """Start the app with this label (or package name)."""
        app = self._find_app(source)
        if app is None:
            await self._async_refresh_apps(force=True)
            app = self._find_app(source)
        package = app["package"] if app else source if "." in source else None
        if package is None:
            raise HomeAssistantError(f"{self.entity_id}: no app called '{source}'")
        await self._call(self.coordinator.client.launch(package=package))

    def _find_app(self, source: str) -> dict[str, Any] | None:
        return next(
            (a for a in self._apps if source in (a.get("label"), a.get("package"))), None
        )

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the media volume (not on a fixed-volume box)."""
        await self._call(self.coordinator.client.volume(level=round(volume * 100)))

    async def async_volume_up(self) -> None:
        """One volume step up."""
        await self._call(self.coordinator.client.volume(step="up"))

    async def async_volume_down(self) -> None:
        """One volume step down."""
        await self._call(self.coordinator.client.volume(step="down"))

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the media stream."""
        await self._call(self.coordinator.client.volume(mute="on" if mute else "off"))

    async def async_media_play(self) -> None:
        """Send play."""
        await self._call(self.coordinator.client.key("play"))

    async def async_media_pause(self) -> None:
        """Send pause."""
        await self._call(self.coordinator.client.key("pause"))

    async def async_media_play_pause(self) -> None:
        """Send play/pause: PiPup does not know which of the two applies."""
        await self._call(self.coordinator.client.key("play_pause"))

    async def async_media_stop(self) -> None:
        """Send stop."""
        await self._call(self.coordinator.client.key("stop"))

    async def async_media_next_track(self) -> None:
        """Send next."""
        await self._call(self.coordinator.client.key("next"))

    async def async_media_previous_track(self) -> None:
        """Send previous."""
        await self._call(self.coordinator.client.key("previous"))
