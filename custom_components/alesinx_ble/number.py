"""Numeric O-Air settings, including the maximum opening limit."""

import math

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .datapoints import NUMBERS
from .entity import OAirDatapointEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([OAirNumber(entry.runtime_data, dp) for dp in NUMBERS])


class OAirNumber(OAirDatapointEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, dp):
        super().__init__(coordinator, dp)
        self._attr_native_min_value = dp.minimum
        self._attr_native_max_value = dp.maximum
        self._attr_native_unit_of_measurement = dp.unit
        self._attr_device_class = dp.device_class
        if dp.id == 129:
            self._attr_icon = "mdi:angle-acute"

    @property
    def native_value(self):
        return self.reported_value

    async def async_set_native_value(self, value):
        if isinstance(value, bool) or not math.isfinite(value) or int(value) != value:
            raise HomeAssistantError("O-Air requires a whole-number setting value")
        await self.coordinator.async_write_datapoint(self.dp.id, int(value))
