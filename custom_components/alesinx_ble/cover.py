"""Window controls; report position only when supplied by the device."""

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)

from .datapoints import READINGS, reported_value
from .entity import OAirEntity

ACTION_DP = next(dp for dp in READINGS if dp.id == 119)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([OAirCover(entry.runtime_data)])


class OAirCover(OAirEntity, CoverEntity):
    _attr_name = None
    _attr_device_class = CoverDeviceClass.WINDOW
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(self, coordinator):
        super().__init__(coordinator, "window")

    @property
    def current_cover_position(self):
        # DP 132 returned zero on an actually open window. Its relationship
        # to HA's normalized position scale has not been established.
        # Expose it through its own sensor instead of inverting/guessing it.
        return None

    @property
    def _action(self):
        value = reported_value(self.coordinator.datapoints, ACTION_DP)
        command = self.coordinator.last_command
        if command == "CLOSE" and value in ("OPEN", "VENTILATE", "MICRO", "EXT_OPEN"):
            return None
        if command in ("OPEN", "VENTILATE", "MICRO") and value == "CLOSE":
            return None
        return value

    @property
    def assumed_state(self):
        return self.current_cover_position is None and self._action is None

    @property
    def is_closed(self):
        if self._action == "CLOSE":
            return True
        if self._action in (
            "OPEN",
            "MICRO",
            "VENTILATE",
            "EXT_OPEN",
            "OPENING",
            "VENT_OPENING",
            "MICRO_OPENING",
        ):
            return False
        return None

    @property
    def is_opening(self):
        return self._action in ("OPENING", "VENT_OPENING", "MICRO_OPENING")

    @property
    def is_closing(self):
        return self._action == "CLOSING"

    @property
    def extra_state_attributes(self):
        return {
            "last_command": self.coordinator.last_command,
            "state_feedback": self._action is not None,
            "position_feedback": False,
        }

    async def async_open_cover(self, **kwargs):
        await self.coordinator.async_command("OPEN")

    async def async_close_cover(self, **kwargs):
        await self.coordinator.async_command("CLOSE")
