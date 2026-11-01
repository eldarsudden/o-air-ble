"""Additional opening modes."""

from homeassistant.components.button import ButtonEntity

from .entity import OAirEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [OAirButton(entry.runtime_data, action) for action in ("MICRO", "VENTILATE")]
    )


class OAirButton(OAirEntity, ButtonEntity):
    def __init__(self, coordinator, action):
        super().__init__(coordinator, action.lower())
        self.action = action
        self._attr_translation_key = action.lower()
        self._attr_icon = "mdi:window-open-variant"

    async def async_press(self):
        await self.coordinator.async_command(self.action)
