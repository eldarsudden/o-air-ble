"""Last acknowledged command, separate from measured window position."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory

from .entity import OAirEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([OAirCommandSensor(entry.runtime_data)])


class OAirCommandSensor(OAirEntity, SensorEntity):
    _attr_translation_key = "last_command"
    _attr_icon = "mdi:gesture-tap-button"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "last_command")

    @property
    def native_value(self):
        return self.coordinator.last_command
