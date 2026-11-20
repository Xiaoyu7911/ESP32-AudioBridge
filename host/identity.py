"""Validate one previously confirmed USB-UART device before opening it."""
from __future__ import annotations
import json
from pathlib import Path


def confirmed_port(config: dict, ports: list) -> str:
    device = config.get('serial_port')
    identity = config.get('serial_identity') or {}
    if not device or not config.get('serial_target_confirmed'):
        raise ValueError('No confirmed USB-UART target. Enumerate first; do not select a Bluetooth COM port.')
    if not isinstance(identity.get('vid'), int) or not isinstance(identity.get('pid'), int):
        raise ValueError('Confirmed target must have an exact USB VID/PID')
    matching = [p for p in ports if p.device == device]
    if len(matching) != 1:
        raise ValueError(f'Confirmed port {device} is absent or ambiguous; re-enumerate, do not guess')
    port = matching[0]
    if (port.vid, port.pid) != (identity['vid'], identity['pid']):
        raise ValueError('USB identity changed on the configured port; refuse access')
    serial = identity.get('serial_number')
    location = identity.get('location')
    if serial:
        if port.serial_number != serial:
            raise ValueError('USB serial number differs from the confirmed board')
    elif location:
        if port.location != location:
            raise ValueError('USB location differs; re-confirm the board before access')
    else:
        raise ValueError('Target lacks serial/location binding; explicitly resolve hardware identity first')
    return device


def load_confirmed(path: Path) -> tuple[dict, str]:
    from serial.tools import list_ports
    config = json.loads(path.read_text(encoding='utf-8'))
    return config, confirmed_port(config, list(list_ports.comports()))
