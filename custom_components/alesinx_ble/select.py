"""Action used by the O-Air scenario."""

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory

from .datapoints import SCENARIO_ACTION
from .entity import OAirDatapointEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([OAirScenarioAction(entry.runtime_data)])


class OAirScenarioAction(OAirDatapointEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(SCENARIO_ACTION.options)

    def __init__(self, coordinator):
        super().__init__(coordinator, SCENARIO_ACTION)

    @property
    def current_option(self):
        return self.reported_value

    async def async_select_option(self, option):
        await self.coordinator.async_write_datapoint(self.dp.id, option)
