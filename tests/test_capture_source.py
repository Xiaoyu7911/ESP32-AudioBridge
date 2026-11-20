import unittest
from host.audio import reject_bridge_capture


class CaptureSourceTests(unittest.TestCase):
    def test_actual_windows_interface_label_is_rejected(self):
        for name in ('麦克风 (Audio control)', 'Audio control', 'ESP Audio Bridge', 'esp audio bridge probe'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                reject_bridge_capture(name)

    def test_explicit_post_fx_bus_can_be_used(self):
        reject_bridge_capture('REAPER Post FX Bus')
        reject_bridge_capture('BlackHole 2ch')
