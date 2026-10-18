"""Exercise GVariant round trips and monitor transitions with an in-memory bus."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
try:
    import mutter
    from gi.repository import GLib
except ImportError:
    mutter = None


class Bus:
    def __init__(self):
        self.serial = 10
        self.color = 0
        self.mode = '3840x2160@180.000+vrr'
        self.supported = [0, 1, 2]
        self.serial_number = 'MSI-example'
        self.active = True
        self.applies = []
        self.layout_supported = True
        self.stale_once = False

    def call_sync(self, bus, path, interface, method, args, *rest):
        if method == 'GetCurrentState':
            physical = ('DP-3', 'MSI', 'MPG321CX', self.serial_number)
            second = ('HDMI-1', 'LG', 'TV', 'LG-example')
            properties = {'color-mode': GLib.Variant('u', self.color),
                          'supported-color-modes': GLib.Variant('au', self.supported),
                          'rgb-range': GLib.Variant('u', 2),
                          'is-underscanning': GLib.Variant('b', True)}
            mode = (self.mode, 3840, 2160, 180.0, 1.25, [1.0, 1.25],
                    {'is-current': GLib.Variant('b', self.active)})
            second_mode = ('1920x1080@120.000', 1920, 1080, 120.0, 1.0, [1.0],
                           {'is-current': GLib.Variant('b', True)})
            monitors = [(physical, [mode], properties),
                        (second, [second_mode], {'color-mode': GLib.Variant('u', 2)})]
            logicals = [(0, 0, 1.25, 0, True, [physical], {})] if self.active else []
            logicals.append((3072, 0, 1.0, 0, not self.active, [second], {}))
            return GLib.Variant('(ua((ssss)a(siiddada{sv})a{sv})a(iiduba(ssss)a{sv})a{sv})',
                                (self.serial, monitors, logicals,
                                 {'layout-mode': GLib.Variant('u', 1),
                                  'supports-changing-layout-mode': GLib.Variant('b', self.layout_supported)}))
        if method == 'ApplyMonitorsConfig':
            if self.stale_once:
                self.stale_once = False
                self.serial += 1
                raise GLib.Error('The requested configuration is based on stale information')
            serial, strategy, logicals, properties = args.unpack()
            assert serial == self.serial
            assert strategy == 1
            self.applies.append(copy.deepcopy((logicals, properties)))
            self.color = logicals[0][5][0][2]['color-mode']
            self.serial += 1
            return GLib.Variant('()', ())
        raise AssertionError(method)


@unittest.skipIf(mutter is None, 'PyGObject not available; core/session tests still run')
class MutterTests(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()
        self.patch = patch.object(mutter.Gio, 'bus_get_sync', return_value=self.bus)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_round_trip_preserves_modes_layout_and_other_monitor_color(self):
        saved = mutter.snapshot()
        mutter.enable(saved)
        logicals, properties = self.bus.applies[-1]
        self.assertEqual(logicals[0][:5], (0, 0, 1.25, 0, True))
        self.assertEqual(logicals[0][5][0], ('DP-3', '3840x2160@180.000+vrr',
                                           {'color-mode': 1, 'underscanning': True, 'rgb-range': 2}))
        self.assertEqual(logicals[1][5][0][2]['color-mode'], 2)
        self.assertEqual(properties, {'layout-mode': 1})
        # Restore must use the CURRENT mode, not the pre-game mode.
        self.bus.mode = '2560x1440@165.000+vrr'
        mutter.restore(saved)
        self.assertEqual(self.bus.color, 0)
        self.assertEqual(self.bus.applies[-1][0][0][5][0][1], self.bus.mode)

    def test_unsupported_hdr_is_rejected_without_mutation(self):
        self.bus.supported = [0, 2]
        with self.assertRaisesRegex(RuntimeError, 'does not advertise'):
            mutter.snapshot('DP-3')
        self.assertEqual(self.bus.applies, [])

    def test_disconnected_or_replaced_monitor_is_not_restored(self):
        saved = mutter.snapshot()
        mutter.enable(saved)
        self.bus.active = False
        with self.assertRaisesRegex(RuntimeError, 'not active'):
            mutter.restore(saved)
        self.bus.active = True
        self.bus.serial_number = 'replacement-display'
        with self.assertRaisesRegex(RuntimeError, 'different monitor'):
            mutter.restore(saved)
        self.assertEqual(len(self.bus.applies), 1)

    def test_manual_sdr_change_and_preexisting_hdr_are_respected(self):
        saved = mutter.snapshot()
        mutter.enable(saved)
        self.bus.color = 2
        mutter.restore(saved)
        self.assertEqual(self.bus.color, 2)
        self.bus.color = 1
        saved = mutter.snapshot()
        mutter.enable(saved)
        mutter.restore(saved)
        self.assertEqual(len(self.bus.applies), 1)

    def test_stale_serial_retries_from_fresh_state(self):
        saved = mutter.snapshot()
        self.bus.stale_once = True
        mutter.enable(saved)
        self.assertEqual(self.bus.color, 1)
        self.assertEqual(len(self.bus.applies), 1)

    def test_layout_mode_not_sent_when_not_supported(self):
        self.bus.layout_supported = False
        mutter.enable(mutter.snapshot())
        self.assertEqual(self.bus.applies[-1][1], {})


if __name__ == '__main__':
    unittest.main()
