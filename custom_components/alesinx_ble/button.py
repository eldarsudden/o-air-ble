"""Additional opening modes."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import OAirEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            OAirButton(entry.runtime_data, action)
            for action in ("MICRO", "VENTILATE", "CALIBRATE")
        ]
    )


class OAirButton(OAirEntity, ButtonEntity):
    def __init__(self, coordinator, action):
        super().__init__(coordinator, action.lower())
        self.action = action
        self._attr_translation_key = action.lower()
        self._attr_icon = "mdi:window-open-variant"
        if action == "CALIBRATE":
            self._attr_entity_registry_enabled_default = False
            self._attr_entity_category = EntityCategory.CONFIG
            self._attr_icon = "mdi:tune"

    async def async_press(self):
        if self.action == "CALIBRATE":
            await self.coordinator.async_write_datapoint(101, self.action)
        else:
            await self.coordinator.async_command(self.action)
