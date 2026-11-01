"""Validate a private QR export without retaining unrelated fields."""

import json

from .const import PRODUCT_ID
from .transport import Credentials


def parse_export(text):
    try:
        source = json.loads(text)
        devices = source["devices"] if "devices" in source else [source]
        result = {}
        for item in devices:
            if item.get("product_id", PRODUCT_ID) != PRODUCT_ID:
                continue
            data = {
                key: item[key] for key in ("device_id", "uuid", "local_key", "sec_key")
            }
            Credentials(**data)
            if data["uuid"] in result:
                raise ValueError("Duplicate device")
            result[data["uuid"]] = {
                **data,
                "name": item.get("name") or item.get("label") or "O-Air",
            }
        if not result:
            raise ValueError("No O-Air credentials")
        return result
    except (KeyError, TypeError, AttributeError, UnicodeError, ValueError):
        raise ValueError("Invalid O-Air credential export") from None
