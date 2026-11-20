"""Reproduce the offline clock model and synthetic SoXR measurements; no hardware."""
from pathlib import Path
import json
import math
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from host.clock import AdaptiveCapture, BufferController


def main():
    curves, cases, quality = [], [], []
    for drift in (-500, 500):
        controller = BufferController()
        level, levels = 960.0, []
        for tick in range(6000):
            t = tick * 0.1
            ppm = controller.update(level + 80 * math.sin(2.3 * t), t)
            level += 48000 * ((1 + drift * 1e-6) * (1 + ppm * 1e-6) - 1) * 0.1
            levels.append(level)
            curves.append({'source_drift_ppm': drift, 'simulation_time_s': t,
                           'buffer_frames': level, 'correction_ppm': ppm})
        cases.append({'source_drift_ppm': drift, 'duration_s': 600, 'min_buffer_ms': min(levels) / 48,
                      'max_buffer_ms': max(levels) / 48, 'final_buffer_ms': level / 48,
                      'final_correction_ppm': controller.ppm, 'model_underruns': int(min(levels) <= 0),
                      'model_overflows': int(max(levels) >= 3072)})
    for frequency in (997, 10000, 20000):
        t = np.arange(48000 * 5) / 48000
        x = (0.1 * np.sin(2 * np.pi * frequency * t)).astype(np.float32).reshape(-1, 1)
        resampler = AdaptiveCapture(1)
        start = time.perf_counter()
        chunks = [resampler.process(x[i:i + 240]) for i in range(0, len(x), 240)]
        chunks.append(resampler.finish())
        elapsed = time.perf_counter() - start
        y = np.concatenate(chunks).reshape(-1).astype(np.float64)
        n = np.arange(4800, len(y) - 4800)
        basis = np.column_stack((np.sin(2 * np.pi * frequency * n / 48000),
                                 np.cos(2 * np.pi * frequency * n / 48000), np.ones(len(n))))
        fit = np.linalg.lstsq(basis, y[n], rcond=None)[0]
        residual = y[n] - basis @ fit
        signal = np.hypot(fit[0], fit[1]) / math.sqrt(2)
        quality.append({'frequency_hz': frequency, 'ratio': 1, 'source_frames': len(x), 'output_frames': len(y),
                        'processing_wall_s_for_5s': elapsed, 'rms_fitted_tone': signal,
                        'residual_over_tone_db': 20 * math.log10(max(np.sqrt(np.mean(residual ** 2)) / signal, 1e-15)),
                        'note': 'Synthetic tone fit, float32 unity ratio; not analog ENOB, phone quality or dynamic-ratio acceptance'})
    report = {'classification': 'SIMULATION', 'hardware_access': False,
              'status': 'PASS' if all(c['model_underruns'] == c['model_overflows'] == 0 for c in cases) else 'FAIL',
              'buffer_model': 'Continuous 48k source/sink, 64ms capacity, feedback perturbation +/-80 frames; excludes OS stalls, USB FIFO and UART faults',
              'controller_cases': cases, 'resampler_quality': quality, 'physical_clock_stability': 'UNTESTED',
              'phone_acceptance': 'UNTESTED'}
    (ROOT / 'artifacts' / 'clock_simulation_curve.jsonl').write_text(
        ''.join(json.dumps(row) + '\n' for row in curves), encoding='utf-8')
    (ROOT / 'reports' / 'CLOCK_SIMULATION.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
