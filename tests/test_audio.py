import tempfile
from pathlib import Path
import unittest
import wave
try:
    import numpy as np
    from host.audio import PCMConverter, CallbackQueue, WavSource, unpack_pcm
except ImportError:
    np = None
from host.protocol import pack_pcm24, unpack_pcm24


@unittest.skipIf(np is None, 'Install host/requirements.lock.txt in project venv')
class AudioTests(unittest.TestCase):
    def test_24bit_boundaries_and_nonzero_low_bits(self):
        values = [-8388608, -65537, -1, 0, 1, 65537, 8388607]
        raw = pack_pcm24(values)
        decoded = unpack_pcm(raw, 24, 1)
        converter = PCMConverter(1, 1, 24)
        self.assertEqual(unpack_pcm24(converter.convert(decoded)), values)

    def test_stereo_downmix_is_explicit_and_equal_weight(self):
        with self.assertRaises(ValueError):
            PCMConverter(2, 1, 16)
        converter = PCMConverter(2, 1, 16, 'average', dither=False)
        result = converter.convert(np.array([[0.5, -0.5], [0.5, 0.5]]))
        self.assertEqual(np.frombuffer(result, '<i2').tolist(), [0, 16384])

    def test_bad_floats_and_clipping_never_wrap(self):
        converter = PCMConverter(1, 1, 16, dither=False)
        result = converter.convert(np.array([[np.nan], [np.inf], [-np.inf], [2.0], [-2.0]]))
        self.assertEqual(np.frombuffer(result, '<i2').tolist(), [0, 0, 0, 32767, -32768])
        self.assertEqual(converter.stats.invalid_samples, 3)
        self.assertEqual(converter.stats.clipped_samples, 2)

    def test_dither_is_bounded_and_does_not_create_dc(self):
        converter = PCMConverter(1, 1, 16, seed=42)
        result = np.frombuffer(converter.convert(np.zeros((100000, 1))), '<i2')
        self.assertLessEqual(int(np.abs(result).max()), 1)
        self.assertLess(abs(float(result.mean())), 0.01)
        self.assertGreater(int(np.count_nonzero(result)), 10000)

    def test_callback_queue_bounds_and_recovers_without_overwrite(self):
        queue = CallbackQueue(2, 1, slots=2)
        a, b, c = b'aaaaaaaa', b'bbbbbbbb', b'cccccccc'
        for value in (a, b, c):
            queue.callback(value, 2, None, False)
        self.assertEqual(queue.dropped_blocks, 1)
        self.assertEqual(queue.pop(), a)
        self.assertEqual(queue.pop(), b)
        self.assertIsNone(queue.pop())
        queue.callback(c, 2, None, False)
        self.assertEqual(queue.pop(), c)

    def test_backend_startup_callbacks_are_counted_before_measured_stream(self):
        queue = CallbackQueue(2, 1, slots=2, armed=False)
        for _ in range(100):
            queue.callback(b'aaaaaaaa', 2, None, False)
        self.assertEqual(queue.startup_discarded_frames, 200)
        self.assertEqual(queue.dropped_blocks, 0)
        self.assertIsNone(queue.pop())
        queue.arm()
        queue.callback(b'bbbbbbbb', 2, None, False)
        self.assertEqual(queue.pop(), b'bbbbbbbb')
        with self.assertRaises(RuntimeError):
            queue.arm()

    def test_startup_gate_does_not_hide_backend_errors(self):
        queue = CallbackQueue(2, 1, armed=False)
        queue.callback(b'aaaaaaaa', 2, None, True)
        queue.callback(b'bad', 2, None, False)
        self.assertEqual(queue.status_events, 1)
        self.assertTrue(queue.callback_error)

    def test_wav_exact_24bit_passthrough_and_rate_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.wav'
            raw = pack_pcm24([-8388608, -1, 1, 8388607])
            with wave.open(str(path), 'wb') as out:
                out.setparams((1, 3, 48000, 0, 'NONE', 'not compressed'))
                out.writeframes(raw)
            source = WavSource(path)
            self.assertTrue(source.direct)
            self.assertEqual(source.read(100), raw)
            source.close()
            with wave.open(str(path), 'wb') as out:
                out.setparams((1, 3, 44100, 0, 'NONE', 'not compressed'))
                out.writeframes(raw)
            with self.assertRaises(ValueError):
                WavSource(path)
