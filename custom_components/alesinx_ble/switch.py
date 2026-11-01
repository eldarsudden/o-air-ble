"""Scenario, timer, sound and TVOC display switches."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory

from .datapoints import SWITCHES
from .entity import OAirDatapointEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([OAirSwitch(entry.runtime_data, dp) for dp in SWITCHES])


class OAirSwitch(OAirDatapointEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self):
        return self.reported_value

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_write_datapoint(self.dp.id, True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_write_datapoint(self.dp.id, False)
