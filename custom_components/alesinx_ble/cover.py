"""Window controls; report position only when supplied by the device."""

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)

from .entity import OAirEntity


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
        dp = self.coordinator.datapoints.get(132, {})
        value = dp.get("value")
        return (
            value
            if dp.get("type") == 2 and isinstance(value, int) and 0 <= value <= 100
            else None
        )

    @property
    def _action(self):
        dp = self.coordinator.datapoints.get(119, {})
        value = dp.get("value")
        return (
            value
            if dp.get("type") == 3
            and value
            in (
                "OPEN",
                "CLOSE",
                "MICRO",
                "VENTILATE",
                "EXT_OPEN",
                "OPENING",
                "VENT_OPENING",
                "MICRO_OPENING",
                "CLOSING",
            )
            else None
        )

    @property
    def assumed_state(self):
        return self.current_cover_position is None and self._action is None

    @property
    def is_closed(self):
        if self.current_cover_position is not None:
            return self.current_cover_position == 0
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
            "position_feedback": not self.assumed_state,
        }

    async def async_open_cover(self, **kwargs):
        await self.coordinator.async_command("OPEN")

    async def async_close_cover(self, **kwargs):
        await self.coordinator.async_command("CLOSE")
