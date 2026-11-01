"""Tuya v4 transport for O-Air, independent of Home Assistant runtime imports.

Wire format references: tuya/TuyaOpen BLE sources and ha-tuya-ble/ha_tuya_ble.
Credentials and decrypted login payloads are never logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import struct
import time
from dataclasses import dataclass, field
from typing import Callable

from bleak import BleakClient
from Crypto.Cipher import AES

WRITE_UUID = "00000001-0000-1001-8001-00805f9b07d0"
NOTIFY_UUID = "00000002-0000-1001-8001-00805f9b07d0"


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def varint(value):
    if value < 0:
        raise ValueError("Negative varint")
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def read_varint(data, position=0):
    value = 0
    for shift in range(0, 28, 7):
        if position >= len(data):
            raise ValueError("Truncated varint")
        byte = data[position]
        position += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, position
    raise ValueError("Oversized varint")


@dataclass(repr=False)
class Credentials:
    device_id: str
    uuid: str
    local_key: str = field(repr=False)
    sec_key: str = field(repr=False)

    def __post_init__(self):
        if len(self.uuid.encode("ascii")) != 16:
            raise ValueError("O-Air UUID must contain 16 ASCII bytes")
        if not 1 <= len(self.device_id.encode("ascii")) <= 22:
            raise ValueError("Invalid O-Air device ID length")
        if any(
            len(key.encode("ascii")) != 16 for key in (self.local_key, self.sec_key)
        ):
            raise ValueError("O-Air needs 16-byte localKey and secKey")

    @property
    def material(self):
        return (self.local_key + self.sec_key).encode("ascii")


@dataclass
class Frame:
    sequence: int
    response_to: int
    code: int
    payload: bytes = field(repr=False)


def encode_frame(frame, key, security_flag, protocol_version=4, packet_size=20):
    if not 20 <= packet_size <= 243:
        raise ValueError("Unsupported packet size")
    raw = (
        struct.pack(
            ">IIHH", frame.sequence, frame.response_to, frame.code, len(frame.payload)
        )
        + frame.payload
    )
    raw += struct.pack(">H", crc16(raw))
    raw += bytes(-len(raw) % 16)
    iv = secrets.token_bytes(16)
    encoded = bytes([security_flag]) + iv + AES.new(key, AES.MODE_CBC, iv).encrypt(raw)
    packets = []
    position = 0
    index = 0
    while position < len(encoded):
        header = varint(index)
        if index == 0:
            header += varint(len(encoded)) + bytes([protocol_version << 4])
        chunk = encoded[position : position + packet_size - len(header)]
        packets.append(header + chunk)
        position += len(chunk)
        index += 1
    return packets


class FrameDecoder:
    def __init__(self, key_for_flag):
        self.key_for_flag = key_for_flag
        self.reset()

    def reset(self):
        self.buffer = bytearray()
        self.expected_index = 0
        self.total = 0

    def feed(self, packet):
        try:
            index, position = read_varint(packet)
            if index == 0:
                self.reset()
                self.total, position = read_varint(packet, position)
                if position >= len(packet) or not 33 <= self.total <= 4096:
                    raise ValueError("Invalid fragment header")
                position += 1
            if not self.total or index != self.expected_index:
                raise ValueError("Out-of-order fragment")
            self.expected_index += 1
            self.buffer.extend(packet[position:])
            if len(self.buffer) > self.total:
                raise ValueError("Oversized frame")
            if len(self.buffer) < self.total:
                return None
            encoded = bytes(self.buffer)
            self.reset()
            if (len(encoded) - 17) % 16:
                raise ValueError("Invalid encrypted length")
            key = self.key_for_flag(encoded[0])
            raw = AES.new(key, AES.MODE_CBC, encoded[1:17]).decrypt(encoded[17:])
            if len(raw) < 14:
                raise ValueError("Truncated frame")
            sequence, response_to, code, length = struct.unpack(">IIHH", raw[:12])
            end = 12 + length
            if end + 2 > len(raw) or crc16(raw[:end]) != int.from_bytes(
                raw[end : end + 2], "big"
            ):
                raise ValueError("Frame length or CRC mismatch")
            return Frame(sequence, response_to, code, raw[12:end])
        except Exception:
            self.reset()
            raise


def parse_datapoints(data, length_size=2):
    result = {}
    position = 0
    while position < len(data):
        if len(data) - position < 2 + length_size:
            raise ValueError("Truncated datapoint header")
        identifier, kind = data[position : position + 2]
        length = int.from_bytes(data[position + 2 : position + 2 + length_size], "big")
        position += 2 + length_size
        if kind > 5 or position + length > len(data):
            raise ValueError("Invalid datapoint type or length")
        raw = data[position : position + length]
        position += length
        if kind == 1:
            if length != 1:
                raise ValueError("Invalid boolean datapoint")
            value = raw != b"\0"
        elif kind == 2:
            if length != 4:
                raise ValueError("Invalid integer datapoint")
            value = int.from_bytes(raw, "big", signed=True)
        elif kind == 3:
            value = raw.decode("utf-8")
        elif kind == 4:
            if length != 1:
                raise ValueError("Invalid enum datapoint")
            value = raw[0]
        else:
            value = raw.hex()
        result[identifier] = {"type": kind, "value": value}
    return result


def timestamp_end(data, position):
    if position >= len(data) or data[position] not in (0, 1):
        raise ValueError("Invalid timestamp")
    end = position + 1 + (13 if data[position] == 0 else 4)
    if end > len(data):
        raise ValueError("Truncated timestamp")
    return end


class OAirClient:
    def __init__(self, credentials, on_update: Callable | None = None):
        self.credentials = credentials
        self.on_update = on_update
        self.client = None
        self.login_key = hashlib.md5(credentials.material).digest()
        self.session_key = None
        self.protocol_version = 4
        self.wire_version = 2
        self.packet_size = 20
        self.datapoints = {}
        self.info = {}
        self.errors = []
        self.events = []
        self.phase = "idle"
        self._decoder = FrameDecoder(self._key)
        self._pending = {}
        self._sequence = 1
        self._dp_sequence = 1
        self._write_lock = asyncio.Lock()
        self._tasks = set()
        self._state_received = asyncio.Event()
        self.authorized = False

    def _key(self, flag):
        if flag == 14:
            return self.login_key
        if flag == 15 and self.session_key:
            return self.session_key
        raise ValueError("Unsupported or premature security flag")

    def _schedule(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)

        def done(completed):
            self._tasks.discard(completed)
            if not completed.cancelled() and completed.exception():
                self.errors.append(type(completed.exception()).__name__)

        task.add_done_callback(done)

    def _disconnected(self, _client):
        self.authorized = False
        for _, future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionError("BLE connection lost"))
        if self.on_update:
            self.on_update()

    def _notify(self, _characteristic, data):
        try:
            frame = self._decoder.feed(bytes(data))
            if frame is None:
                return
            self.events.append(
                {
                    "sequence": frame.sequence,
                    "response_to": frame.response_to,
                    "code": f"0x{frame.code:04x}",
                    "bytes": len(frame.payload),
                }
            )
            del self.events[:-100]
            if frame.code == 0 and frame.response_to and len(frame.payload) >= 46:
                self.protocol_version = frame.payload[2]
                self.session_key = hashlib.md5(
                    self.credentials.material + frame.payload[6:12]
                ).digest()
                self.info = {
                    "protocol_version": f"{frame.payload[2]}.{frame.payload[3]}",
                    "flags": frame.payload[4],
                    "bound": bool(frame.payload[5]),
                }
            pending = self._pending.get(frame.response_to)
            if pending and pending[0] == frame.code and not pending[1].done():
                pending[1].set_result(frame.payload)
            if frame.response_to:
                return
            payload = frame.payload
            updates = None
            ack = b""
            if frame.code in (0x8006, 0x8007):
                if len(payload) < 7 or payload[0] != 0:
                    raise ValueError("Invalid v4 datapoint report")
                position = timestamp_end(payload, 7) if frame.code == 0x8007 else 7
                updates = parse_datapoints(payload[position:], 2)
                ack = None if payload[5] & 0x80 else payload[:7] + b"\0"
            elif frame.code in (0x8001, 0x8003):
                position = timestamp_end(payload, 0) if frame.code == 0x8003 else 0
                updates = parse_datapoints(payload[position:], 1)
            elif frame.code in (0x8004, 0x8005):
                if len(payload) < 3:
                    raise ValueError("Invalid signed report")
                position = timestamp_end(payload, 3) if frame.code == 0x8005 else 3
                updates = parse_datapoints(payload[position:], 1)
                ack = payload[:3] + b"\0"
            elif frame.code == 0x8011:
                # UTC timestamp, timezone offset supplied separately.
                offset = -int(time.timezone / 36)
                ack = str(int(time.time() * 1000)).encode() + struct.pack(">h", offset)
            elif frame.code == 0x8012:
                now = time.localtime()
                offset = -int(time.timezone / 36)
                ack = struct.pack(
                    ">BBBBBBBh",
                    now.tm_year % 100,
                    now.tm_mon,
                    now.tm_mday,
                    now.tm_hour,
                    now.tm_min,
                    now.tm_sec,
                    now.tm_wday,
                    offset,
                )
            else:
                return
            if updates is not None:
                self.datapoints.update(updates)
                self._state_received.set()
                if self.on_update:
                    self.on_update()
            if ack is not None:
                self._schedule(
                    self._send(frame.code, ack, response_to=frame.sequence, wait=False)
                )
        except (ValueError, UnicodeError) as error:
            self.errors.append(str(error))

    async def _send(
        self, code, payload=b"", response_to=0, wait=True, security_flag=None
    ):
        if not self.client or not self.client.is_connected:
            raise ConnectionError("BLE connection unavailable")
        sequence = self._sequence
        self._sequence += 1
        future = asyncio.get_running_loop().create_future() if wait else None
        if future:
            self._pending[sequence] = (code, future)
        flag = security_flag if security_flag is not None else (14 if code == 0 else 15)
        key = self._key(flag)
        packets = encode_frame(
            Frame(sequence, response_to, code, payload),
            key,
            flag,
            self.wire_version,
            self.packet_size,
        )
        try:
            async with self._write_lock:
                for packet in packets:
                    await self.client.write_gatt_char(
                        WRITE_UUID, packet, response=False
                    )
                    await asyncio.sleep(0.03)
            return await asyncio.wait_for(future, 10) if future else None
        finally:
            self._pending.pop(sequence, None)
            if future and not future.done():
                future.cancel()

    async def connect(
        self, device, client_factory=BleakClient, authorize=True, connector=None
    ):
        await self.close()
        self._sequence = 1
        self._dp_sequence = 1
        self.session_key = None
        self._decoder.reset()
        self.datapoints.clear()
        self._state_received.clear()
        self.packet_size = 20
        self.phase = "connecting"
        try:
            if connector:
                self.client = await connector(device, self._disconnected)
            else:
                self.client = client_factory(
                    device, timeout=20, disconnected_callback=self._disconnected
                )
                await self.client.connect()
            self.phase = "subscribing"
            await asyncio.sleep(0.3)
            await self.client.start_notify(NOTIFY_UUID, self._notify)
            self.phase = "device_info"
            payload = await self._send(0, b"\x00\xf3")
            if (
                len(payload) < 88
                or not self.session_key
                or self.protocol_version != 4
                or not payload[5]
            ):
                raise ValueError("Unsupported O-Air device-info response")
            characteristic = self.client.services.get_characteristic(WRITE_UUID)
            self.packet_size = max(
                20, min(243, characteristic.max_write_without_response_size)
            )
            self.info["packet_size"] = self.packet_size
            if not authorize:
                self.phase = "device_info_complete"
                return
            # This Wi-Fi/BLE firmware accepts mode-15 DP commands immediately
            # after DEVICE_INFO. Legacy PAIR disconnects it. Verified on O-Air.
            self.authorized = True
            self.phase = "authorized"
        except BaseException:
            await self.close()
            raise

    async def read_state(self, report_timeout=2, identifiers=()):
        if not self.authorized:
            raise ConnectionError("O-Air session is not authorized")
        self.phase = "reading_state"
        self._state_received.clear()
        result = await self._send(3, bytes(identifiers))
        if result != b"\0":
            raise ValueError("O-Air state request rejected")
        if report_timeout:
            try:
                await asyncio.wait_for(self._state_received.wait(), report_timeout)
            except asyncio.TimeoutError:
                # O-Air acknowledges queries without necessarily reporting DPs.
                pass
        self.phase = "ready"
        return dict(self.datapoints)

    async def command(self, action):
        if action not in ("OPEN", "CLOSE", "MICRO", "VENTILATE"):
            raise ValueError("Unsupported window action")
        if not self.authorized:
            raise ConnectionError("O-Air session is not authorized")
        value = action.encode("ascii")
        prefix = struct.pack(">BI", 0, self._dp_sequence)
        self._dp_sequence += 1
        payload = prefix + bytes([101, 3]) + struct.pack(">H", len(value)) + value
        self.phase = "sending_command"
        reply = await self._send(0x27, payload)
        if len(reply) != 6 or reply[:5] != prefix or reply[5] != 0:
            raise ValueError("O-Air did not confirm the window command")
        self.phase = "ready"

    async def close(self):
        self.authorized = False
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.client:
            client, self.client = self.client, None
            if client.is_connected:
                await client.disconnect()
