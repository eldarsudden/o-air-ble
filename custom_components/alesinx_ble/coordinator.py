"""Serialized BLE transactions through Home Assistant's adapters."""

import asyncio
import logging
from datetime import timedelta

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .advertisement import decode_v4
from .const import DOMAIN, SERVICE_UUID
from .datapoints import WRITABLE, reported_value, validate_value
from .transport import Credentials, OAirClient

_LOGGER = logging.getLogger(__name__)
TRANSPORT_ERRORS = (BleakError, ConnectionError, OSError, TimeoutError, ValueError)


async def connect_ble(device, disconnected_callback):
    """Retry connection establishment only, before sending a window command."""
    return await establish_connection(
        BleakClientWithServiceCache,
        device,
        "O-Air",
        disconnected_callback=disconnected_callback,
        max_attempts=3,
    )


def find_device(hass, uuid):
    """Resolve the factory UUID on this host, including Bluetooth proxies."""
    for info in bluetooth.async_discovered_service_info(hass, connectable=True):
        decoded = decode_v4(
            info.service_data.get(SERVICE_UUID, b""),
            info.manufacturer_data.get(0x07D0, b""),
        )
        if decoded and decoded.get("device_uuid") == uuid:
            device = bluetooth.async_ble_device_from_address(
                hass, info.address, connectable=True
            )
            if device is not None:
                return device
        # A stronger source can have an incomplete scan response. Check the
        # merged advertisement from every connectable source for this address.
        for source in bluetooth.async_scanner_devices_by_address(
            hass, info.address, connectable=True
        ):
            advertisement = source.advertisement
            decoded = decode_v4(
                advertisement.service_data.get(SERVICE_UUID, b""),
                advertisement.manufacturer_data.get(0x07D0, b""),
            )
            if decoded and decoded.get("device_uuid") == uuid:
                device = bluetooth.async_ble_device_from_address(
                    hass, info.address, connectable=True
                )
                if device is not None:
                    return device
    return None


async def wait_for_device(hass, uuid, duration=10):
    """Observe UUID matches throughout the active scan, including replay."""
    if not bluetooth.async_scanner_count(hass, connectable=True):
        return None
    found = asyncio.get_running_loop().create_future()

    def discovered(info, change):
        if found.done():
            return
        decoded = decode_v4(
            info.service_data.get(SERVICE_UUID, b""),
            info.manufacturer_data.get(0x07D0, b""),
        )
        if decoded and decoded.get("device_uuid") == uuid:
            device = bluetooth.async_ble_device_from_address(
                hass, info.address, connectable=True
            )
            if device is not None:
                found.set_result(device)

    unsubscribe = bluetooth.async_register_callback(
        hass,
        discovered,
        {"service_uuid": SERVICE_UUID, "connectable": True},
        bluetooth.BluetoothScanningMode.ACTIVE,
    )
    try:
        await bluetooth.async_request_active_scan(hass, duration=duration)
        return found.result() if found.done() else find_device(hass, uuid)
    finally:
        unsubscribe()
        if not found.done():
            found.cancel()


def discovery_error(hass):
    """Explain an unreachable opener without logging credentials or UUIDs."""
    scanners = bluetooth.async_scanner_count(hass, connectable=False)
    connectable = bluetooth.async_scanner_count(hass, connectable=True)
    infos = bluetooth.async_discovered_service_info(hass, connectable=False)
    tuya = [
        info
        for info in infos
        if SERVICE_UUID in info.service_data or SERVICE_UUID in info.service_uuids
    ]
    complete = sum(
        bool(
            (
                decode_v4(
                    info.service_data.get(SERVICE_UUID, b""),
                    info.manufacturer_data.get(0x07D0, b""),
                )
                or {}
            ).get("device_uuid")
        )
        for info in tuya
    )
    _LOGGER.warning(
        "O-Air discovery: scanners=%s, connectable=%s, Tuya FD50 devices=%s, decoded UUIDs=%s",
        scanners,
        connectable,
        len(tuya),
        complete,
    )
    if not scanners:
        return "no_bluetooth_source"
    if not connectable:
        return "no_connectable_source"
    if tuya and not complete:
        return "incomplete_bluetooth_data"
    return "not_found"


class OAirCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=60),
        )
        self.entry = entry
        self.uuid = entry.data["uuid"]
        self._credentials = Credentials(
            **{k: entry.data[k] for k in ("device_id", "uuid", "local_key", "sec_key")}
        )
        self._lock = asyncio.Lock()
        self._stopping = False
        self.last_command = None
        self.datapoints = {}
        self.write_receipts = {}
        self.write_verification = {}

    async def _transaction(self, action=None, setting=None):
        async with self._lock:
            if self._stopping:
                raise ConnectionError("O-Air is unloading")
            device = find_device(self.hass, self.uuid)
            if device is None:
                device = await wait_for_device(self.hass, self.uuid, duration=5)
            if device is None:
                discovery_error(self.hass)
                raise ConnectionError(
                    "O-Air is not reachable by a connectable Bluetooth adapter"
                )
            client = OAirClient(self._credentials)
            try:
                await client.connect(device, connector=connect_ble)
                if action or setting is not None:
                    identifier, value = (101, action) if action else setting
                    targets = (132, 119) if identifier == 101 else (identifier,)
                    for target in targets:
                        self.datapoints.pop(target, None)
                    if action:
                        await client.command(action)
                    else:
                        await client.write_datapoint(identifier, value)
                    self.write_receipts[identifier] = value
                    self.write_verification[identifier] = None
                    if identifier == 101:
                        self.last_command = value
                    try:
                        await asyncio.sleep(0.3)
                        self.datapoints.update(
                            await client.read_state(identifiers=targets)
                        )
                        if identifier != 101:
                            observed = reported_value(
                                self.datapoints, WRITABLE[identifier]
                            )
                            if observed is not None and observed != value:
                                await asyncio.sleep(0.5)
                                self.datapoints.update(
                                    await client.read_state(identifiers=targets)
                                )
                                observed = reported_value(
                                    self.datapoints, WRITABLE[identifier]
                                )
                            if observed is not None:
                                self.write_verification[identifier] = observed == value
                    except TRANSPORT_ERRORS:
                        # A failed status read must not turn a confirmed move
                        # into a failed command that the caller might repeat.
                        _LOGGER.debug(
                            "O-Air acknowledged the write; value feedback is unavailable"
                        )
                else:
                    self.datapoints = await client.read_all()
                return dict(self.datapoints)
            finally:
                try:
                    await client.close()
                except TRANSPORT_ERRORS:
                    _LOGGER.debug("O-Air connection already closed")

    async def _async_update_data(self):
        try:
            return await self._transaction()
        except TRANSPORT_ERRORS as error:
            raise UpdateFailed(
                "O-Air Bluetooth query failed; close Smart Life and check range"
            ) from error

    async def async_command(self, action):
        try:
            data = await self._transaction(action)
        except TRANSPORT_ERRORS as error:
            self.async_set_update_error(UpdateFailed("O-Air Bluetooth command failed"))
            raise HomeAssistantError(
                "O-Air did not confirm the command; check the window before retrying"
            ) from error
        self.async_set_updated_data(data)

    async def async_write_datapoint(self, identifier, value):
        dp = WRITABLE.get(identifier)
        if dp is None:
            raise HomeAssistantError("O-Air datapoint is read-only or unsupported")
        try:
            validate_value(dp, value)
        except ValueError as error:
            raise HomeAssistantError("Invalid O-Air setting value") from error
        observed = self.datapoints.get(identifier)
        if observed and observed.get("type") != dp.kind:
            raise HomeAssistantError(
                "O-Air reported an unexpected datatype for this setting"
            )
        try:
            data = await self._transaction(setting=(identifier, value))
        except TRANSPORT_ERRORS as error:
            self.async_set_update_error(
                UpdateFailed("O-Air Bluetooth setting write failed")
            )
            raise HomeAssistantError(
                "O-Air did not acknowledge the setting write"
            ) from error
        self.async_set_updated_data(data)
        if self.write_verification.get(identifier) is False:
            raise HomeAssistantError(
                "O-Air acknowledged the setting but returned a different value when read back"
            )

    async def async_shutdown_connection(self):
        self._stopping = True
        async with self._lock:
            pass
