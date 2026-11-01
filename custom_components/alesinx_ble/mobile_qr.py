"""Ephemeral Smart Life mobile QR authorization for local BLE credentials.

Uses the same mobile API exchange already verified by the standalone tool.
The caller owns the shared aiohttp session. No tokens or exports are written.
"""

import asyncio
import secrets
import time

from aiohttp import ClientError
from tuya_mobile import TuyaMobileApp, TuyaMobileSession, TuyaPasswordClient
from tuya_mobile.errors import TuyaMobileError

from .const import PRODUCT_ID
from .transport import Credentials

ENDPOINTS = {
    "eu": "https://a1.tuyaeu.com/api.json",
    "us": "https://a1.tuyaus.com/api.json",
    "sg": "https://a1-sg.iotbing.com/api.json",
    "cn": "https://a1.tuyacn.com/api.json",
    "in": "https://a1.tuyain.com/api.json",
}
API_ERRORS = (TuyaMobileError, ClientError, TimeoutError, ValueError, RuntimeError)


class MobileQRLoginError(Exception):
    """A safe translation key, never a server response containing secrets."""

    def __init__(self, code="qr_failed"):
        self.code = code
        super().__init__(code)


def walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def api_result(response):
    if not isinstance(response, dict) or response.get("success") is not True:
        raise MobileQRLoginError()
    return response.get("result")


def account_result(response):
    if isinstance(response, dict):
        if response.get("success") is False or response.get("errorCode"):
            raise MobileQRLoginError()
    if not isinstance(response, (dict, list)):
        raise MobileQRLoginError()
    return response


class MobileQRLogin:
    def __init__(self, session):
        self._session = session
        self._client = None
        self._token = None
        self._expires = 0
        self._authenticated = False
        self._candidates = {}
        self._tasks = set()

    async def _request(self, awaitable):
        task = asyncio.create_task(awaitable)
        self._tasks.add(task)
        try:
            return await task
        finally:
            self._tasks.discard(task)

    @property
    def qr_data(self):
        return f"tuyaSmart--qrLogin?token={self._token}" if self._token else None

    async def start(self, country, region):
        self.clear()
        if (
            not isinstance(country, str)
            or not country.isascii()
            or not country.isdigit()
            or not 1 <= len(country) <= 4
        ):
            raise MobileQRLoginError("invalid_country")
        if region not in ENDPOINTS:
            raise MobileQRLoginError("invalid_region")
        self._client = TuyaPasswordClient.for_application(
            TuyaMobileApp.SMART_LIFE,
            self._session,
            username="alesinx-ble-qr-" + secrets.token_hex(16),
            endpoint=ENDPOINTS[region],
            max_login_attempts=1,
        )
        try:
            response = await self._request(
                self._client._mobile_call(
                    "tuya.m.user.qr.token.create", "1.0", {"countryCode": country}
                )
            )
            token = api_result(response)
            if not isinstance(token, str) or not token:
                raise MobileQRLoginError()
            self._token = token
            self._expires = time.monotonic() + 180
        except (MobileQRLoginError, *API_ERRORS):
            self.clear()
            raise MobileQRLoginError() from None

    async def approved(self):
        if self._authenticated:
            return True
        if not self._client or time.monotonic() >= self._expires:
            raise MobileQRLoginError("qr_expired")
        try:
            response = await self._request(
                self._client._mobile_call(
                    "tuya.m.user.qr.token.user.get", "1.0", {"token": self._token}
                )
            )
            result = api_result(response)
            login = next(
                (
                    item
                    for item in walk_dicts(result)
                    if all(
                        isinstance(item.get(key), str) and item[key]
                        for key in ("sid", "ecode", "uid")
                    )
                ),
                None,
            )
            if login is None:
                if any("sid" in item for item in walk_dicts(result)):
                    raise MobileQRLoginError()
                return False
            self._client.sid = login["sid"]
            self._client.ecode = login["ecode"]
            self._client.uid = login["uid"]
            if endpoint := self._client._endpoint_from_login(login):
                self._client.mobile_url = endpoint
            self._client.mobile_session = TuyaMobileSession(
                sid=login["sid"],
                ecode=login["ecode"],
                uid=login["uid"],
                endpoint=self._client.mobile_url,
            )
            self._authenticated = True
            self._token = None
            return True
        except API_ERRORS:
            raise MobileQRLoginError() from None

    async def discover(self):
        if not self._authenticated:
            raise MobileQRLoginError()
        try:
            async with asyncio.timeout(45):
                homes = account_result(
                    await self._request(
                        self._client._mobile_call("m.life.home.space.list", "1.0", {})
                    )
                )
                groups = {
                    str(item.get("gid") or item.get("groupId") or item.get("homeId"))
                    for item in walk_dicts(homes)
                    if item.get("gid") or item.get("groupId") or item.get("homeId")
                }
                found = {}
                for group in sorted(groups):
                    devices = account_result(
                        await self._request(
                            self._client._mobile_call(
                                "m.life.my.group.device.list", "2.2", {"gid": group}
                            )
                        )
                    )
                    for item in walk_dicts(devices):
                        identifier = (
                            item.get("devId") or item.get("deviceId") or item.get("id")
                        )
                        product = (
                            item.get("productId")
                            or item.get("product_id")
                            or item.get("pid")
                        )
                        if not identifier or product != PRODUCT_ID:
                            continue
                        data = {
                            "device_id": str(identifier),
                            "product_id": product,
                            "name": str(item.get("name") or "O-Air"),
                            "uuid": item.get("uuid"),
                        }
                        previous = found.get(data["device_id"])
                        if (
                            previous
                            and previous.get("uuid")
                            and data.get("uuid")
                            and previous["uuid"] != data["uuid"]
                        ):
                            raise MobileQRLoginError("identity_mismatch")
                        found[data["device_id"]] = data
                if not found:
                    raise MobileQRLoginError("no_devices")
                self._candidates = found
                return {key: dict(data) for key, data in found.items()}
        except API_ERRORS:
            raise MobileQRLoginError() from None

    async def credentials(self, identifier):
        if not self._authenticated or identifier not in self._candidates:
            raise MobileQRLoginError("identity_mismatch")
        previous = self._candidates[identifier]
        try:
            credential = await self._request(
                self._client.get_device_credentials(identifier)
            )
            if (
                credential.device_id != identifier
                or (credential.product_id and credential.product_id != PRODUCT_ID)
                or (
                    previous.get("uuid")
                    and credential.uuid
                    and previous["uuid"] != credential.uuid
                )
            ):
                raise MobileQRLoginError("identity_mismatch")
            result = {
                "device_id": identifier,
                "uuid": credential.uuid or previous.get("uuid"),
                "name": previous["name"],
                "local_key": credential.local_key,
                "sec_key": credential.sec_key,
            }
            Credentials(
                **{
                    key: result[key]
                    for key in ("device_id", "uuid", "local_key", "sec_key")
                }
            )
            return result
        except (AttributeError, TypeError, UnicodeError, *API_ERRORS):
            raise MobileQRLoginError("missing_keys") from None

    def clear(self):
        for task in self._tasks:
            task.cancel()
        if self._client:
            self._client.sid = self._client.ecode = self._client.uid = None
            self._client.mobile_session = None
        self._client = None
        self._token = None
        self._expires = 0
        self._authenticated = False
        self._candidates = {}
