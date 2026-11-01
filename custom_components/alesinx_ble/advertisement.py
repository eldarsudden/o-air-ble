"""Decode TuyaOS v4 advertisement metadata without device credentials.

Reference: tuya/TuyaOpen, src/tuya_cloud_service/ble/ble_mgr.c (ble_adv_set)
and ble_cryption.c (tuya_ble_rsp_id_encrypt). UUID recovery uses public
advertisement bytes; it neither authenticates a device nor reveals its keys.
"""

from __future__ import annotations

import hashlib
import re


def decode_v4(service_data: bytes, manufacturer_data: bytes):
    if len(service_data) < 4 or service_data[0] >> 4 != 4:
        return None
    id_length = service_data[3]
    if id_length != 16 or len(service_data) != 4 + id_length:
        return None
    if len(manufacturer_data) != 20:
        return None
    control = int.from_bytes(service_data[:2], "big")
    result = {
        "protocol_version": 4,
        "frame_control": f"0x{control:04x}",
        "bound": bool(control & (1 << 11)),
        "requests_connection": bool(control & (1 << 9)),
        "security_v2_supported": bool(control & (1 << 2)),
        "security_v2_confirmed": bool(control & (1 << 3)),
        "id_type": service_data[2],
        "encryption_mode": manufacturer_data[0],
        "communication_capabilities": f"0x{int.from_bytes(manufacturer_data[1:3], 'big'):04x}",
        "response_flags": f"0x{manufacturer_data[3]:02x}",
    }
    try:
        from Crypto.Cipher import AES
    except ImportError:
        result["uuid_decode_error"] = "Install pycryptodome to recover the public UUID"
        return result
    public_key = hashlib.md5(service_data).digest()
    uuid = AES.new(public_key, AES.MODE_CBC, public_key).decrypt(manufacturer_data[4:])
    if re.fullmatch(rb"[a-zA-Z0-9]{16}", uuid):
        result["device_uuid"] = uuid.decode("ascii")
    else:
        result["uuid_decode_error"] = (
            "Payload did not decode to a 16-character alphanumeric UUID"
        )
    return result
