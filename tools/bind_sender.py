"""Plan/save one sender's exact USB-UART binding without opening any serial port."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def binding(port: str, expected_serial: str, ports: list) -> dict:
    matches = [p for p in ports if p.device == port]
    if len(matches) != 1:
        raise ValueError('Selected port is missing or ambiguous; enumerate again')
    p = matches[0]
    if (p.vid, p.pid) != (0x1a86, 0x55d3):
        raise ValueError('Selected port is not the reviewed CH343 USB-UART; Bluetooth is not a target')
    if not expected_serial or p.serial_number != expected_serial:
        raise ValueError('USB serial does not match the known board; do not guess if the Mac driver omits identity')
    return dict(serial_port=port, serial_target_confirmed=True,
                serial_identity=dict(vid=p.vid, pid=p.pid, serial_number=p.serial_number, location=p.location),
                connection_mode='computer_com_only', power_review=dict(status='UNVERIFIED'),
                baud_candidates=[2000000, 3000000],
                confirmation='Operator selected the known board by port and exact USB serial',
                created_utc=datetime.now(timezone.utc).isoformat(),
                scope='Sender binding only; no chip probe, firmware flash, audio capture or Mac acceptance performed')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--expected-serial', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'configs' / 'hardware.mac.local.json')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-known-board', action='store_true')
    args = parser.parse_args()
    from serial.tools import list_ports
    result = binding(args.port, args.expected_serial, list(list_ports.comports()))
    print(json.dumps({'planned_config': str(args.output), 'hardware_opened': False, **result}, ensure_ascii=False, indent=2))
    if args.execute:
        if not args.confirm_known_board:
            raise ValueError('Saving a confirmed binding requires --confirm-known-board')
        destination = args.output.resolve()
        if not destination.is_relative_to(ROOT / 'configs') or not destination.name.endswith('.local.json'):
            raise ValueError('Save only a *.local.json file inside this project configs directory')
        # Never overwrite a Windows binding or an earlier Mac confirmation.
        with destination.open('x', encoding='utf-8') as output:
            output.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(2)
