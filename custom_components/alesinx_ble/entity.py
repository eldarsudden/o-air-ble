"""Shared device identity."""

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .datapoints import reported_value


class OAirEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.uuid}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.uuid)},
            name=coordinator.entry.title,
            manufacturer="Alesinx",
            model="O-Air",
        )


class OAirDatapointEntity(OAirEntity):
    def __init__(self, coordinator, dp):
        super().__init__(coordinator, dp.key)
        self.dp = dp
        self._attr_translation_key = dp.key
        self._attr_entity_registry_enabled_default = dp.enabled

    @property
    def reported_value(self):
        return reported_value(self.coordinator.datapoints, self.dp)

    @property
    def extra_state_attributes(self):
        attributes = {"value_reported": self.reported_value is not None}
        if self.dp.id in self.coordinator.write_receipts:
            attributes["last_acknowledged_value"] = self.coordinator.write_receipts[
                self.dp.id
            ]
            attributes["last_write_verified"] = self.coordinator.write_verification.get(
                self.dp.id
            )
        return attributes
