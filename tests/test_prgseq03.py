"""Exercise the real sequence/controller with simulated GPIO and a virtual clock."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.pins = {}
        self.now_ms = 0
        self.stop_at_ms = None
        self.sensor_level = lambda now: 0
        self.fail_pwm = lambda duty: False
        self.fail_relay = False
        owner = self

        class Pin:
            IN = 0
            OUT = 1

            def __init__(self, number, mode=None, value=None):
                self.number = number
                self.mode = mode
                self.level = 0
                owner.pins[number] = self
                if value is not None:
                    self.value(value)

            def value(self, value=None):
                if value is None:
                    if self.number == 0:
                        return owner.sensor_level(owner.now_ms)
                    return self.level
                if owner.fail_relay and self.number == 17:
                    raise OSError("relay unavailable")
                self.level = value
                owner.events.append(("relay", value, owner.now_ms))

        class PWM:
            def __init__(self, pin):
                self.pin = pin
                self.duty = None
                self.released = False

            def freq(self, frequency):
                self.frequency = frequency

            def duty_u16(self, duty):
                if owner.fail_pwm(duty):
                    raise OSError("PWM unavailable")
                self.duty = duty
                owner.events.append(
                    ("pwm", duty, owner.now_ms, owner.pins[17].level)
                )

            def deinit(self):
                self.released = True
                owner.events.append(("deinit", owner.now_ms))

        def sleep(seconds):
            self.now_ms += round(seconds * 1000)
            if self.stop_at_ms is not None and self.now_ms >= self.stop_at_ms:
                raise KeyboardInterrupt()

        machine = types.ModuleType("machine")
        machine.Pin = Pin
        machine.PWM = PWM
        clock = types.ModuleType("time")
        clock.sleep = sleep
        clock.ticks_ms = lambda: self.now_ms
        clock.ticks_diff = lambda now, start: now - start

        with patch.dict(sys.modules, {"machine": machine, "time": clock}):
            controller = load_module(
                "_roomlight_controller_test", ROOT / "lib/BlackLight/BlackLightControl.py"
            )
            with patch.dict(sys.modules, {"lib.BlackLight.BlackLightControl": controller}):
                self.sequence = load_module(
                    "_roomlight_sequence_test", ROOT / "prgSeq01/prgSeq03.py"
                )
        self.pwm = self.sequence.BlackLight._pwm

    def events_named(self, name):
        return [event for event in self.events if event[0] == name]

    def run_quietly(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.sequence.run()

    def assert_outputs_off(self):
        self.assertEqual(self.pins[17].level, 0)
        self.assertEqual(self.pwm.duty, 0)
        self.assertTrue(self.pwm.released)

    def test_pins_and_initial_outputs(self):
        self.assertEqual(set(self.pins), {0, 16, 17})
        self.assertEqual(self.pins[0].mode, self.pins[0].IN)
        self.assertEqual(self.pins[17].mode, self.pins[17].OUT)
        self.assertIs(self.sequence.bRelay, self.pins[17])
        self.assertEqual(self.pwm.pin.number, 16)
        self.assertEqual(self.pwm.frequency, 1000)
        self.assertEqual(self.pins[17].level, 0)
        self.assertEqual(self.pwm.duty, 0)
        self.assertFalse(self.pwm.released)

    def test_controller_pwm_is_not_inverted(self):
        self.events.clear()
        for percent in (0, 50, 100):
            self.sequence.BlackLight.set_percent(percent)
        self.assertEqual(
            [event[1] for event in self.events_named("pwm")], [0, 32767, 65535]
        )

    def test_wake_activates_relay_only_after_final_pwm(self):
        self.events.clear()
        self.sequence.fbiWakeUp()
        self.assertEqual(self.events[-2][:2], ("pwm", 65535))
        self.assertEqual(self.events[-1], ("relay", 1, 1000))
        self.assertEqual(self.events_named("relay"), [("relay", 1, 1000)])
        self.assertTrue(all(event[3] == 0 for event in self.events_named("pwm")))

    def test_sleep_keeps_relay_active_until_final_pwm(self):
        self.sequence.fbiWakeUp()
        self.events.clear()
        self.sequence.fbiSleep()
        self.assertEqual(self.events[-2][:2], ("pwm", 0))
        self.assertEqual(self.events[-1], ("relay", 0, 2000))
        self.assertEqual(self.events_named("relay"), [("relay", 0, 2000)])
        self.assertTrue(all(event[3] == 1 for event in self.events_named("pwm")))

    def test_high_hold_restarts_after_short_pulse(self):
        self.sensor_level = lambda now: int(now < 100 or now >= 200)
        self.sequence.wait_for_high_hold(0.2)
        self.assertEqual(self.now_ms, 400)

    def test_held_sensor_does_not_toggle_repeatedly(self):
        self.sensor_level = lambda now: 1
        self.stop_at_ms = 2500
        with self.assertRaises(KeyboardInterrupt):
            self.run_quietly()
        self.assertEqual(
            [event for event in self.events_named("relay") if event[1] == 1],
            [("relay", 1, 1200)],
        )
        self.assert_outputs_off()

    def test_sensor_cycle_turns_on_then_off_and_cleans_up(self):
        self.sensor_level = lambda now: int(now < 1400 or 1500 <= now < 2800)
        self.stop_at_ms = 3000
        with self.assertRaises(KeyboardInterrupt):
            self.run_quietly()
        self.assertIn(("relay", 1, 1200), self.events)
        self.assertIn(("relay", 0, 2700), self.events)
        self.assertEqual(
            len([event for event in self.events_named("relay") if event[1] == 1]), 1
        )
        self.assert_outputs_off()

    def test_wake_failure_does_not_activate_relay(self):
        self.sensor_level = lambda now: 1
        self.fail_pwm = lambda duty: duty == 32767
        with self.assertRaisesRegex(OSError, "PWM unavailable"):
            self.run_quietly()
        self.assertFalse(any(event[1] == 1 for event in self.events_named("relay")))
        self.assert_outputs_off()

    def test_sleep_failure_also_turns_outputs_off(self):
        self.sensor_level = lambda now: int(now < 1400 or 1500 <= now < 2800)
        self.fail_pwm = lambda duty: duty == 32767 and self.pins[17].level == 1
        with self.assertRaisesRegex(OSError, "PWM unavailable"):
            self.run_quietly()
        self.assertIn(("relay", 1, 1200), self.events)
        self.assert_outputs_off()

    def test_shutdown_attempts_pwm_cleanup_even_if_relay_write_fails(self):
        self.sequence.fbiWakeUp()
        self.fail_relay = True
        with self.assertRaisesRegex(OSError, "relay unavailable"):
            self.sequence.shutdown()
        self.assertEqual(self.pwm.duty, 0)
        self.assertTrue(self.pwm.released)


if __name__ == "__main__":
    unittest.main()
