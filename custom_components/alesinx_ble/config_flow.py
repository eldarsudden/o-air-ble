"""Configure O-Air using Smart Life QR login or an existing credential export."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .coordinator import (
    TRANSPORT_ERRORS,
    connect_ble,
    discovery_error,
    find_device,
    wait_for_device,
)
from .credentials import parse_export
from .mobile_qr import ENDPOINTS, MobileQRLogin, MobileQRLoginError
from .transport import Credentials, OAirClient


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._devices = {}
        self._mobile = None
        self._country = "7"
        self._region = "eu"

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id="user", menu_options=["qr_login", "manual"])

    async def async_step_qr_login(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._country = user_input["country"].strip().lstrip("+")
            self._region = user_input["region"]
            self._clear_login()
            self._mobile = MobileQRLogin(async_get_clientsession(self.hass))
            try:
                await self._mobile.start(self._country, self._region)
            except MobileQRLoginError as error:
                errors["base"] = error.code
            else:
                return await self.async_step_scan()
        return self._show_login(errors)

    def _show_login(self, errors):
        return self.async_show_form(
            step_id="qr_login",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("country", default=self._country): str,
                    vol.Required("region", default=self._region): vol.In(
                        list(ENDPOINTS)
                    ),
                }
            ),
        )

    async def async_step_scan(self, user_input=None):
        if self._mobile is None:
            return await self.async_step_qr_login()
        errors = {}
        if user_input is not None:
            try:
                if user_input.get("refresh_qr"):
                    await self._mobile.start(self._country, self._region)
                elif not await self._mobile.approved():
                    errors["base"] = "qr_pending"
                else:
                    self._devices = await self._mobile.discover()
                    return await self.async_step_device()
            except MobileQRLoginError as error:
                errors["base"] = error.code
        if not self._mobile.qr_data:
            self._clear_login()
            return self._show_login(errors)
        return self.async_show_form(
            step_id="scan",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Optional("qr"): selector.QrCodeSelector(
                        selector.QrCodeSelectorConfig(
                            data=self._mobile.qr_data,
                            scale=5,
                            error_correction_level=selector.QrErrorCorrectionLevel.QUARTILE,
                        )
                    ),
                    vol.Optional("refresh_qr", default=False): bool,
                }
            ),
        )

    async def async_step_manual(self, user_input=None):
        errors = {}
        self._clear_login()
        if user_input is not None:
            try:
                self._devices = parse_export(user_input["credentials"])
            except ValueError:
                errors["base"] = "invalid_credentials"
            else:
                return await self.async_step_device()
        return self.async_show_form(
            step_id="manual",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("credentials"): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True)
                    )
                }
            ),
        )

    async def async_step_device(self, user_input=None):
        errors = {}
        if user_input is not None:
            selected = user_input["device"]
            data = self._devices[selected]
            if self._mobile and "sec_key" not in data:
                try:
                    data = await self._mobile.credentials(data["device_id"])
                except MobileQRLoginError as error:
                    return self._show_devices({"base": error.code})
                self._devices[selected] = data
            uuid = data["uuid"]
            await self.async_set_unique_id(uuid)
            self._abort_if_unique_id_configured()
            device = find_device(self.hass, uuid)
            if device is None:
                try:
                    device = await wait_for_device(self.hass, uuid)
                except TRANSPORT_ERRORS:
                    return self._show_devices({"base": "bluetooth_scan_failed"})
            if device is None:
                errors["base"] = discovery_error(self.hass, uuid)
            else:
                client = OAirClient(
                    Credentials(
                        **{
                            k: data[k]
                            for k in ("device_id", "uuid", "local_key", "sec_key")
                        }
                    )
                )
                try:
                    await client.connect(device, connector=connect_ble)
                    await client.read_state(report_timeout=0)
                except TRANSPORT_ERRORS:
                    errors["base"] = "cannot_connect"
                finally:
                    await client.close()
                if not errors:
                    self._devices = {}
                    self._clear_login()
                    return self.async_create_entry(title=data["name"], data=data)
        return self._show_devices(errors)

    def _show_devices(self, errors):
        choices = {
            uuid: data["name"] + " (" + uuid[-4:] + ")"
            for uuid, data in self._devices.items()
        }
        return self.async_show_form(
            step_id="device",
            errors=errors,
            data_schema=vol.Schema({vol.Required("device"): vol.In(choices)}),
        )

    def _clear_login(self):
        if self._mobile:
            self._mobile.clear()
        self._mobile = None

    def async_remove(self):
        self._clear_login()
        self._devices = {}
        super().async_remove()
