"""Original UART frame reference. MIT. No hardware access.

Wire format: COBS(header + payload + crc32_le) + NUL.
This is a protocol layer, not an audio sender or a clock-recovery implementation.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
import struct
import zlib

MAGIC = b"EAB1"
VERSION = 1
HEADER = struct.Struct("<4sBBHIIQHBBI")
CRC = struct.Struct("<I")
MAX_PAYLOAD = 4096
MAX_RAW = HEADER.size + MAX_PAYLOAD + CRC.size
MAX_ENCODED = MAX_RAW + MAX_RAW // 254 + 2

class Kind(IntEnum):
    HELLO = 1
    CONFIG = 2
    START = 3
    AUDIO = 4
    STOP = 5
    STATS = 6
    ACK = 7
    ERROR = 8
    HEARTBEAT = 9

class ProtocolError(ValueError):
    pass

@dataclass(frozen=True)
class Frame:
    kind: Kind
    stream_id: int
    sequence: int
    payload: bytes = b""
    sample_index: int = 0
    frames: int = 0
    channels: int = 0
    bits: int = 0
    flags: int = 0


def cobs_encode(data: bytes) -> bytes:
    output = bytearray(b"\x00")
    code_index = 0
    code = 1
    for value in data:
        if value == 0:
            output[code_index] = code
            code_index = len(output)
            output.append(0)
            code = 1
        else:
            output.append(value)
            code += 1
            if code == 0xFF:
                output[code_index] = code
                code_index = len(output)
                output.append(0)
                code = 1
    output[code_index] = code
    return bytes(output)


def cobs_decode(data: bytes) -> bytes:
    if not data or 0 in data:
        raise ProtocolError("invalid COBS data")
    result = bytearray()
    index = 0
    while index < len(data):
        code = data[index]
        index += 1
        end = index + code - 1
        if end > len(data):
            raise ProtocolError("truncated COBS block")
        result.extend(data[index:end])
        index = end
        if code != 0xFF and index < len(data):
            result.append(0)
    return bytes(result)


def _validate(frame: Frame) -> None:
    try:
        kind = Kind(frame.kind)
    except (ValueError, TypeError) as exc:
        raise ProtocolError("unknown kind") from exc
    limits = ((frame.stream_id, 32), (frame.sequence, 32),
              (frame.sample_index, 64), (frame.frames, 16))
    if any(not isinstance(value, int) or not 0 <= value < 2**width
           for value, width in limits):
        raise ProtocolError("out-of-range header integer")
    if frame.flags != 0:
        raise ProtocolError("unsupported flags")
    if not isinstance(frame.payload, bytes) or len(frame.payload) > MAX_PAYLOAD:
        raise ProtocolError("payload must be bounded bytes")
    if kind == Kind.AUDIO:
        if frame.channels not in (1, 2) or frame.bits not in (16, 24) or frame.frames <= 0:
            raise ProtocolError("invalid PCM format")
        if len(frame.payload) != frame.frames * frame.channels * (frame.bits // 8):
            raise ProtocolError("PCM payload length mismatch")
    elif frame.frames or frame.channels or frame.bits or frame.sample_index:
        raise ProtocolError("control frame has audio metadata")


def encode(frame: Frame) -> bytes:
    _validate(frame)
    raw = HEADER.pack(MAGIC, VERSION, int(frame.kind), frame.flags,
                      frame.stream_id, frame.sequence, frame.sample_index,
                      frame.frames, frame.channels, frame.bits, len(frame.payload))
    raw += frame.payload
    raw += CRC.pack(zlib.crc32(raw) & 0xFFFFFFFF)
    return cobs_encode(raw) + b"\x00"


def decode(encoded_without_delimiter: bytes) -> Frame:
    if len(encoded_without_delimiter) > MAX_ENCODED:
        raise ProtocolError("oversize encoded frame")
    raw = cobs_decode(encoded_without_delimiter)
    if not HEADER.size + CRC.size <= len(raw) <= MAX_RAW:
        raise ProtocolError("invalid frame size")
    if (zlib.crc32(raw[:-4]) & 0xFFFFFFFF) != CRC.unpack(raw[-4:])[0]:
        raise ProtocolError("CRC mismatch")
    magic, version, kind, flags, sid, seq, index, count, channels, bits, size = HEADER.unpack(raw[:HEADER.size])
    if magic != MAGIC or version != VERSION:
        raise ProtocolError("unsupported magic/version")
    payload = raw[HEADER.size:-4]
    if size != len(payload):
        raise ProtocolError("declared length mismatch")
    try:
        parsed_kind = Kind(kind)
    except ValueError as exc:
        raise ProtocolError("unknown message kind") from exc
    frame = Frame(parsed_kind, sid, seq, payload, index, count, channels, bits, flags)
    _validate(frame)
    return frame


class StreamDecoder:
    """Bounded decoder tolerating partial reads, corrupt frames and boot noise."""
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._discarding = False
        self.bad_frames = 0
        self.oversize_frames = 0

    def feed(self, data: bytes) -> list[Frame]:
        result: list[Frame] = []
        for value in data:
            if value == 0:
                if self._discarding:
                    self._discarding = False
                elif self._buffer:
                    try:
                        result.append(decode(bytes(self._buffer)))
                    except ProtocolError:
                        self.bad_frames += 1
                self._buffer.clear()
            elif not self._discarding:
                if len(self._buffer) >= MAX_ENCODED:
                    self.oversize_frames += 1
                    self._buffer.clear()
                    self._discarding = True
                else:
                    self._buffer.append(value)
        return result


def pack_pcm24(samples: list[int]) -> bytes:
    data = bytearray()
    for sample in samples:
        if not isinstance(sample, int) or not -(2**23) <= sample < 2**23:
            raise ProtocolError("24-bit sample out of range")
        data.extend(sample.to_bytes(3, "little", signed=True))
    return bytes(data)


def unpack_pcm24(data: bytes) -> list[int]:
    if len(data) % 3:
        raise ProtocolError("unaligned 24-bit payload")
    return [int.from_bytes(data[i:i+3], "little", signed=True)
            for i in range(0, len(data), 3)]
