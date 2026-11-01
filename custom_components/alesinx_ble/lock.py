"""O-Air child lock."""

from homeassistant.components.lock import LockEntity
from homeassistant.const import EntityCategory

from .datapoints import CHILD_LOCK
from .entity import OAirDatapointEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([OAirChildLock(entry.runtime_data)])


class OAirChildLock(OAirDatapointEntity, LockEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator):
        super().__init__(coordinator, CHILD_LOCK)

    @property
    def is_locked(self):
        return self.reported_value

    async def async_lock(self, **kwargs):
        await self.coordinator.async_write_datapoint(self.dp.id, True)

    async def async_unlock(self, **kwargs):
        await self.coordinator.async_write_datapoint(self.dp.id, False)
