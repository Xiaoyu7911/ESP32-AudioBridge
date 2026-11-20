"""Versioned protocol session. Serial is opened only after exact identity checks."""
from __future__ import annotations
import json
import math
from pathlib import Path
import secrets
import time
from .identity import load_confirmed
from .protocol import Frame, Kind, StreamDecoder, encode


class Session:
    def __init__(self, transport, stream_id: int | None = None):
        self.transport = transport
        self.stream_id = stream_id if stream_id is not None else secrets.randbits(32)
        self.sequence = self.sample_index = 0
        self.decoder = StreamDecoder()
        self.last_stats: dict = {}
        self.wire_bytes = 0
        self.started = False
        self.decoder_baseline = (0, 0)

    def decoder_diagnostics(self) -> dict:
        return {'bad_frames_during_stream': self.decoder.bad_frames - self.decoder_baseline[0],
                'oversize_frames_during_stream': self.decoder.oversize_frames - self.decoder_baseline[1]}

    @classmethod
    def serial(cls, config: Path, baud: int):
        import serial
        _, port = load_confirmed(config)
        if baud not in (2000000, 3000000):
            raise ValueError('Bring-up is restricted to 2M/3M; no silent baud fallback')
        uart = serial.Serial(port=None, baudrate=baud, timeout=0.02, write_timeout=0.25,
                             rtscts=False, dsrdtr=False, xonxoff=False)
        # Set desired states before open. Some OS/drivers can still glitch them;
        # the HELLO retry handles a possible reset; no toggling during streaming.
        uart.dtr = uart.rts = False
        uart.port = port
        try:
            uart.open()
        except BaseException:
            uart.close()
            raise
        return cls(uart)

    def send(self, kind: Kind, payload: bytes = b'', frames: int = 0, channels: int = 0, bits: int = 0) -> int:
        seq = self.sequence
        wire = encode(Frame(kind, self.stream_id, seq, payload,
                            self.sample_index if kind == Kind.AUDIO else 0, frames, channels, bits))
        written = self.transport.write(wire)
        if written != len(wire):
            raise RuntimeError('Short UART write; abort stream rather than silently dropping bytes')
        self.sequence = (seq + 1) & 0xffffffff
        self.wire_bytes += written
        if kind == Kind.AUDIO:
            self.sample_index += frames
        return seq

    def poll(self, wait: bool = False) -> list[tuple[Frame, dict]]:
        result = []
        waiting = getattr(self.transport, 'in_waiting', 0)
        if not waiting and not wait:
            return result
        data = self.transport.read(max(1, min(waiting, 8192)))
        frames = self.decoder.feed(data)
        if self.started and any(self.decoder_diagnostics().values()):
            raise RuntimeError(f'Corrupt bridge telemetry: {self.decoder_diagnostics()}')
        for frame in frames:
            if frame.stream_id != self.stream_id or frame.kind == Kind.AUDIO:
                continue
            try:
                payload = json.loads(frame.payload.decode('utf-8'))
            except (ValueError, UnicodeError):
                raise RuntimeError('Invalid control JSON from bridge')
            if not isinstance(payload, dict):
                raise RuntimeError('Bridge control message must be an object')
            if frame.kind == Kind.STATS:
                self.last_stats = payload
            result.append((frame, payload))
        return result

    def request(self, kind: Kind, values: dict | None = None, timeout: float = 2.0) -> dict:
        seq = self.send(kind, json.dumps(values or {}, separators=(',', ':'), allow_nan=False).encode())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for frame, payload in self.poll(wait=True):
                if payload.get('reply_to') != seq:
                    continue
                if frame.kind == Kind.ERROR or payload.get('ok') is False:
                    raise RuntimeError(f'Bridge rejected {kind.name}: {payload}')
                if frame.kind in (Kind.ACK, Kind.HELLO, Kind.STATS):
                    return payload
        raise TimeoutError(f'No bridge response to {kind.name}; confirm firmware, baud and port, do not scan other ports')

    def hello(self) -> dict:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                result = self.request(Kind.HELLO, {'protocol': 1}, timeout=0.6)
                if result.get('protocol') != 1:
                    raise RuntimeError('Firmware protocol version mismatch')
                return result
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise

    def start(self, bits: int, channels: int, mode: str = 'audio', usb_wait_seconds: float = 0) -> dict:
        if not math.isfinite(usb_wait_seconds) or not 0 <= usb_wait_seconds <= 120:
            raise ValueError('USB readiness wait must be finite and within0..120seconds')
        hello = self.hello()
        if hello.get('bits') != bits or hello.get('channels') != channels or hello.get('sample_rate') != 48000:
            raise ValueError(f'WAV/source format does not match USB firmware profile: {hello}')
        self.request(Kind.CONFIG, {'sample_rate': 48000, 'bits': bits, 'channels': channels, 'mode': mode})
        if mode == 'audio' and usb_wait_seconds:
            deadline = time.monotonic() + usb_wait_seconds
            while True:
                if (Path(__file__).resolve().parents[1] / 'STOP_REQUESTED').exists():
                    raise InterruptedError('STOP_REQUESTED while waiting for USB recorder; no audio sent')
                status = self.request(Kind.STATS)
                if status.get('usb_stream_active') is True:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('USB recorder did not become active within the requested wait; no audio sent')
                time.sleep(min(.1, max(0, deadline - time.monotonic())))
        result = self.request(Kind.START)
        self.sample_index = 0
        self.decoder_baseline = (self.decoder.bad_frames, self.decoder.oversize_frames)
        self.started = True
        return result

    def stop(self, drain: bool = False) -> dict:
        if not self.started:
            return {}
        self.request(Kind.STOP, {'drain': drain}, timeout=3.0)
        self.started = False
        return self.request(Kind.STATS)

    def close(self):
        try:
            if self.started:
                self.stop()
        finally:
            self.transport.close()
