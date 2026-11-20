"""File/realtime PCM sender. Run with: python -m host.sender --help."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import random
import math
import sys
import time
import zlib
from .protocol import Frame, Kind, encode
from .session import Session

ROOT = Path(__file__).resolve().parents[1]


def inventory(audio: bool = False):
    if not audio:
        from serial.tools import list_ports
        return [dict(port=p.device, description=p.description, vid=p.vid, pid=p.pid,
                     serial_number=p.serial_number, location=p.location) for p in list_ports.comports()]
    import sounddevice as sd
    apis = sd.query_hostapis()
    return [dict(index=i, name=d['name'], api=apis[d['hostapi']]['name'],
                 inputs=d['max_input_channels'], outputs=d['max_output_channels'],
                 default_sample_rate=d['default_samplerate']) for i, d in enumerate(sd.query_devices())]


def write_json(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, default=ROOT / 'configs' / 'hardware.local.json')
    p.add_argument('--baud', type=int, choices=[2000000, 3000000], default=3000000)
    p.add_argument('--wait-for-usb', type=float, default=0,
                   help='bounded0..120s wait for the actual USB recorder after opening UART; no audio sent while waiting')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('ports', help='enumerate only; never opens ports')
    sub.add_parser('devices', help='enumerate audio endpoints without recording')
    sub.add_parser('hello', help='query the one identity-bound board')
    w = sub.add_parser('wav', help='48000 Hz PCM WAV; Ctrl+C sends STOP')
    w.add_argument('path', type=Path)
    w.add_argument('--bits', type=int, choices=[16, 24], help='explicit conversion if different from WAV')
    w.add_argument('--channels', type=int, choices=[1, 2], default=1)
    w.add_argument('--mix', choices=['average', 'left', 'right'])
    w.add_argument('--dry-run', type=Path, help='write protocol frames to a local file, no serial/USB access')
    c = sub.add_parser('capture', help='capture an explicitly selected post-FX input')
    selection = c.add_mutually_exclusive_group(required=True)
    selection.add_argument('--source', type=int)
    selection.add_argument('--source-name', help='exact stable input name; requires --source-api')
    c.add_argument('--source-api', help='exact PortAudio API, e.g. Core Audio; no automatic fallback')
    c.add_argument('--post-fx-confirmed', action='store_true', required=True)
    c.add_argument('--input-channels', type=int, choices=[1, 2], default=2)
    c.add_argument('--channels', type=int, choices=[1, 2], default=1)
    c.add_argument('--bits', type=int, choices=[16, 24], default=16)
    c.add_argument('--mix', choices=['average', 'left', 'right'])
    c.add_argument('--seconds', type=float, default=60)
    c.add_argument('--asrc', action='store_true', help='explicit experimental soxr clock adaptation; changes samples')
    c.add_argument('--capture-block-frames', type=int, choices=[240, 480], default=240,
                   help='CoreAudio callback frames; queue stays bounded at80ms, UART packets remain240frames')
    c.add_argument('--capture-latency', choices=['low', 'high'], default='low',
                   help='Explicit PortAudio latency request; report actual backend latency, keep the80ms application queue')
    c.add_argument('--diagnose-timing', action='store_true', help='bounded consumer-stage timing; never logs from the callback')
    s = sub.add_parser('stress', help='UART integrity only; not an audio or phone acceptance')
    s.add_argument('--bits', type=int, choices=[16, 24], default=16)
    s.add_argument('--channels', type=int, choices=[1, 2], default=1)
    s.add_argument('--seconds', type=float, default=600)
    s.add_argument('--seed', type=int, default=12345)
    for command in (w, c, s):
        command.add_argument('--stats-log', type=Path)
    return p


def send_pcm_chunks(session, data: bytes, channels: int, bits: int, block_frames: int = 240) -> int:
    frame_bytes = channels * (bits // 8)
    if len(data) % frame_bytes:
        raise ValueError('Partial PCM frame from source/resampler')
    for offset in range(0, len(data), block_frames * frame_bytes):
        part = data[offset:offset + block_frames * frame_bytes]
        session.send(Kind.AUDIO, part, len(part) // frame_bytes, channels, bits)
    return len(data) // frame_bytes


def poll_stream(session, started_at: float, command: str, adaptive=None, log=None):
    """Process telemetry even while the input callback has no block ready."""
    stats = None
    for frame, value in session.poll():
        if frame.kind == Kind.ERROR:
            raise RuntimeError(f'Bridge error: {value}')
        if frame.kind != Kind.STATS:
            continue
        stats = value
        if adaptive and value.get('running'):
            adaptive.observe(value, time.monotonic())
        if log:
            log.write(json.dumps({'host_elapsed_s': time.monotonic() - started_at, **value,
                                  'host_decoder': session.decoder_diagnostics(),
                                  'host_asrc': adaptive.describe() if adaptive else None}) + '\n')
            log.flush()
        if any(value.get(key, 0) for key in ('crc_errors', 'malformed_frames', 'sequence_gaps', 'index_gaps',
                                            'audio_rejected', 'uart_errors', 'overflows', 'watchdog_stops')):
            raise RuntimeError(f'Transport discontinuity: {value}')
        if value.get('running') is False:
            raise RuntimeError(f'Bridge stopped during input: {value}')
        if command != 'stress' and value.get('underruns', 0):
            raise RuntimeError(f'Audio underrun: {value}')
    return stats


def run(args) -> int:
    if args.command in ('ports', 'devices'):
        write_json(inventory(args.command == 'devices'))
        return 0
    if (ROOT / 'STOP_REQUESTED').exists():
        raise ValueError('STOP_REQUESTED exists')
    if args.command == 'hello':
        session = Session.serial(args.config, args.baud)
        try:
            write_json(session.hello())
        finally:
            session.close()
        return 0
    from .audio import WavSource, PCMConverter, CallbackQueue, reject_bridge_capture
    import numpy as np
    source = capture = session = log = adaptive = None
    block = 240  # 5 ms at 48k; UART scheduling is not treated as the sink clock.
    sent = wire_bytes = crc = 0
    requested_frames = math.ceil(args.seconds * 48000) if args.command == 'stress' else None
    stats = {}
    from .diagnostics import TimingProbe
    probe = TimingProbe() if getattr(args, 'diagnose_timing', False) else None

    def timed(stage, function, *values, **options):
        return probe.call(stage, function, *values, **options) if probe else function(*values, **options)

    started_at = time.monotonic()
    try:
        if args.command == 'wav':
            source = WavSource(args.path, args.bits, args.channels, args.mix)
            args.bits = source.bits
            if args.dry_run:
                args.dry_run.parent.mkdir(parents=True, exist_ok=True)
                with args.dry_run.open('wb') as output:
                    sequence = index = 0
                    while data := source.read(block):
                        frames = len(data) // (args.channels * args.bits // 8)
                        wire = encode(Frame(Kind.AUDIO, 1, sequence, data, index, frames, args.channels, args.bits))
                        output.write(wire)
                        wire_bytes += len(wire)
                        sequence += 1
                        index += frames
                write_json({'classification': 'SIMULATION', 'hardware_access': False,
                            'frames': index, 'wire_bytes': wire_bytes, 'path': str(args.dry_run),
                            'pcm_direct': source.direct, 'conversion': asdict(source.converter.stats)})
                return 0
        else:
            if not 0 < args.seconds <= 3600:
                raise ValueError('Duration must be >0 and <=3600 seconds per run')
        if args.stats_log:
            args.stats_log.parent.mkdir(parents=True, exist_ok=True)
            log = args.stats_log.open('w', encoding='utf-8')
        if args.command == 'capture':
            import sounddevice as sd
            source_index = args.source
            if args.source_name:
                if not args.source_api:
                    raise ValueError('A named post-FX input requires explicit --source-api')
                from .source import choose_named_input
                source_index = choose_named_input(sd.query_devices(), sd.query_hostapis(), args.source_name,
                                                  args.source_api, args.input_channels)
            device = dict(sd.query_devices(source_index, 'input'))
            if args.source_api and sd.query_hostapis()[device['hostapi']]['name'].casefold() != args.source_api.casefold():
                raise ValueError('Selected input API differs from --source-api; no fallback')
            reject_bridge_capture(device['name'])
            converter = PCMConverter(args.input_channels, args.channels, args.bits, args.mix)
            capture_block = args.capture_block_frames
            queue = CallbackQueue(capture_block, args.input_channels,
                                  slots=3840 // capture_block, armed=False)
            if args.asrc:
                from .clock import AdaptiveCapture
                adaptive = AdaptiveCapture(args.input_channels)
            sd.check_input_settings(device=source_index, channels=args.input_channels, dtype='float32', samplerate=48000)
            capture = sd.RawInputStream(device=source_index, channels=args.input_channels, dtype='float32',
                                        samplerate=48000, blocksize=capture_block, latency=args.capture_latency,
                                        callback=queue.callback)
            write_json({'source': device, 'post_fx_confirmed_by_operator': True,
                        'source_index': source_index, 'explicit_source_api': args.source_api,
                        'mix': args.mix, 'bits': args.bits, 'dither': converter.dither,
                        'clock_adaptation': adaptive.describe() if adaptive else 'NONE',
                        'capture_block_frames': capture_block, 'queue_capacity_frames': 3840,
                        'requested_capture_latency': args.capture_latency,
                        'reported_backend_input_latency_seconds': capture.latency,
                        'startup_policy': 'Start CoreAudio before opening UART; explicitly discard/count pre-stream callbacks'})
            # Permission dialogs and AUHAL startup can block for a long time.
            # They must complete before the board starts its audio watchdog.
            timed('backend_start', capture.start)
            write_json({'status': 'AUDIO_CAPTURE_READY_PRE_STREAM',
                        'startup_discarded_frames': queue.startup_discarded_frames,
                        'serial_opened': False})
        rng = random.Random(getattr(args, 'seed', 12345))
        session = timed('serial_open', Session.serial, args.config, args.baud)
        if args.wait_for_usb and args.command != 'stress':
            write_json({'status': 'WAITING_FOR_USB_RECORDER', 'maximum_seconds': args.wait_for_usb,
                        'audio_sent': False, 'serial_port_already_open': True})
        timed('handshake', session.start, args.bits, args.channels, 'integrity' if args.command == 'stress' else 'audio',
              usb_wait_seconds=args.wait_for_usb)
        if capture:
            queue.arm()
        started_at = time.monotonic()
        next_print = started_at
        while True:
            if (ROOT / 'STOP_REQUESTED').exists():
                raise InterruptedError('STOP_REQUESTED')
            if adaptive:
                adaptive.check_timeout(time.monotonic(), started_at)
            if args.command == 'stress' and sent >= requested_frames:
                break
            if args.command == 'capture' and time.monotonic() - started_at >= args.seconds:
                break
            if args.command == 'wav':
                data = source.read(block)
                if not data:
                    break
            elif args.command == 'stress':
                data = rng.randbytes(min(block, requested_frames - sent) * args.channels * (args.bits // 8))
            else:
                if queue.dropped_blocks or queue.callback_error or queue.status_events:
                    raise RuntimeError(f'Capture discontinuity: drops={queue.dropped_blocks}, status={queue.status_events}')
                data = queue.pop()
                if data is None:
                    stats = timed('telemetry', poll_stream, session, started_at, args.command, adaptive, log) or stats
                    time.sleep(0.001)  # wait for callback, not an audio clock
                    continue
                floats = np.frombuffer(data, dtype=np.float32).reshape(-1, args.input_channels)
                if adaptive:
                    floats = timed('asrc', adaptive.process, floats)
                    if not len(floats):
                        continue
                data = timed('conversion', converter.convert, floats)
            sent += timed('uart_send', send_pcm_chunks, session, data, args.channels, args.bits, block)
            crc = zlib.crc32(data, crc) & 0xffffffff
            # File/integrity paths use absolute pacing; drift is measured, no hidden
            # sample drops, resampling or claim of long-term clock adaptation.
            if args.command != 'capture':
                wait = started_at + sent / 48000 - time.monotonic()
                if wait > 0:
                    time.sleep(min(wait, 0.02))
            stats = timed('telemetry', poll_stream, session, started_at, args.command, adaptive, log) or stats
            if time.monotonic() >= next_print:
                write_json({'classification': 'BENCH_MEASUREMENT', 'sent_frames': sent,
                            'wire_bytes': session.wire_bytes, 'device': stats,
                            'clock_adaptation': adaptive.describe() if adaptive else 'NONE; long-run quality/stability unverified'})
                next_print = time.monotonic() + 1
        if adaptive:
            tail = converter.convert(adaptive.finish())
            sent += send_pcm_chunks(session, tail, args.channels, args.bits, block)
            crc = zlib.crc32(tail, crc) & 0xffffffff
        stats = session.stop(drain=args.command != 'stress')
        required = {'audio_frames': sent, 'audio_crc32': crc, 'crc_errors': 0,
                        'sequence_gaps': 0, 'index_gaps': 0, 'uart_errors': 0, 'audio_rejected': 0,
                        'malformed_frames': 0, 'watchdog_stops': 0, 'overflows': 0, 'underruns': 0}
        if args.command != 'stress':
            required['consumed_frames'] = sent
        if any(stats.get(key) != value for key, value in required.items()) or any(session.decoder_diagnostics().values()):
            raise RuntimeError(f'Final transfer counters FAIL: expected={required}, received={stats}')
        if log:
            log.write(json.dumps({'host_phase': 'final', 'host_elapsed_s': time.monotonic() - started_at,
                                  **stats, 'host_decoder': session.decoder_diagnostics(),
                                  'host_asrc': adaptive.describe() if adaptive else None}) + '\n')
            log.flush()
        write_json({'classification': 'BENCH_MEASUREMENT', 'status': 'INTEGRITY_PASS' if args.command == 'stress' else 'TRANSFER_FINISHED',
                    'phone_acceptance': 'UNTESTED', 'sent_frames': sent,
                    'requested_audio_frames': requested_frames, 'host_audio_crc32': crc,
                    'wire_bytes': session.wire_bytes,
                    'elapsed_s': time.monotonic() - started_at, 'device': stats,
                    'host_decoder': session.decoder_diagnostics(),
                    'clock_adaptation': adaptive.describe() if adaptive else 'NONE',
                    'conversion': asdict(source.converter.stats if source else converter.stats) if args.command != 'stress' else None})
        return 0
    finally:
        if capture:
            capture.close()
            write_json({'status': 'CAPTURE_DIAGNOSTICS',
                        'capture_block_frames': capture_block, 'queue_capacity_frames': 3840,
                        'requested_capture_latency': args.capture_latency,
                        'reported_backend_input_latency_seconds': capture.latency,
                        'startup_discarded_frames': queue.startup_discarded_frames,
                        'dropped_blocks': queue.dropped_blocks, 'status_events': queue.status_events,
                        'callback_error': queue.callback_error,
                        'sent_frames': sent, 'wire_bytes': session.wire_bytes if session else 0,
                        'clock_adaptation': adaptive.describe() if adaptive else None,
                        'consumer_timing': probe.describe() if probe else None})
        try:
            if session:
                session.close()
        finally:
            if source:
                source.close()
            if log:
                log.close()


def main():
    try:
        return run(parser().parse_args())
    except KeyboardInterrupt:
        print('Stopped by operator; STOP/close attempted.', file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, TimeoutError, InterruptedError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
