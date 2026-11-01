"""Last acknowledged command, separate from measured window position."""

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory

from .datapoints import READINGS
from .entity import OAirDatapointEntity, OAirEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [OAirCommandSensor(entry.runtime_data)]
        + [OAirSensor(entry.runtime_data, dp) for dp in READINGS]
    )


class OAirSensor(OAirDatapointEntity, SensorEntity):
    def __init__(self, coordinator, dp):
        super().__init__(coordinator, dp)
        self._attr_native_unit_of_measurement = dp.unit
        if dp.options:
            self._attr_device_class = "enum"
            self._attr_options = list(dp.options)
        else:
            self._attr_device_class = dp.device_class
            self._attr_state_class = SensorStateClass.MEASUREMENT
        if dp.id in (101, 123, 128, 131):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return self.reported_value


class OAirCommandSensor(OAirEntity, SensorEntity):
    _attr_translation_key = "last_command"
    _attr_icon = "mdi:gesture-tap-button"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "last_command")

    @property
    def native_value(self):
        return self.coordinator.last_command
