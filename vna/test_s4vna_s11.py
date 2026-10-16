"""Offline checks for the S4VNA command sequence; no analyzer is required."""

import unittest

from vna.s4vna_s11 import capture


class FakeS4Vna:
    def __init__(self):
        self.values = {
            "*IDN?": "CMT,808/1,SN0001,26.2",
            "SYST:READ?": "1",
            "SENS:CORR:IMP?": "50",
            "CALC1:PAR1:DEF?": "S11",
            "SENS1:CORR:STAT?": "1",
            "TRIG:SOUR?": "INT",
            "INIT1:CONT?": "1",
            "*OPC?": "1",
            "SENS1:FREQ:DATA?": "50000000,51705000,53000000",
            "CALC1:TRAC1:DATA:SDAT?": "0.5,0.1,0.1,-0.05,0.4,0.2",
        }
        self.events = []

    def query(self, command):
        self.events.append(("query", command))
        return self.values[command]

    def write(self, command):
        self.events.append(("write", command))


class S4VnaSweepTest(unittest.TestCase):
    def test_fresh_sweep_waits_for_completion_and_restores_trigger(self):
        fake = FakeS4Vna()
        sweep, metadata = capture(fake)

        self.assertEqual(len(sweep), 3)
        self.assertEqual(sweep[1], (51705000.0, 0.1 - 0.05j))
        self.assertEqual(metadata["calibration_enabled"], "1")
        self.assertEqual(
            [command for kind, command in fake.events if kind == "write"],
            ["INIT1:CONT OFF", "TRIG:SOUR BUS", "INIT1:CONT ON",
             "TRIG:SEQ:SING", "INIT1:CONT OFF", "TRIG:SOUR INT",
             "INIT1:CONT 1"],
        )
        commands = [command for _, command in fake.events]
        self.assertLess(commands.index("*OPC?"), commands.index("SENS1:FREQ:DATA?"))
        self.assertFalse(any("FORM:DATA" in command for command in commands))

    def test_existing_read_does_not_change_trigger_settings(self):
        fake = FakeS4Vna()
        _, metadata = capture(fake, fresh=False)
        self.assertFalse(metadata["fresh_sweep"])
        self.assertFalse(any(kind == "write" for kind, _ in fake.events))
        self.assertNotIn(("query", "*OPC?"), fake.events)

    def test_rejects_non_s11_trace_before_triggering(self):
        fake = FakeS4Vna()
        fake.values["CALC1:PAR1:DEF?"] = "S21"
        with self.assertRaisesRegex(ValueError, "set it to S11"):
            capture(fake)
        self.assertFalse(any(kind == "write" for kind, _ in fake.events))

    def test_bad_data_still_restores_trigger(self):
        fake = FakeS4Vna()
        fake.values["CALC1:TRAC1:DATA:SDAT?"] = "0.1,0.2"
        with self.assertRaisesRegex(ValueError, "expected 6"):
            capture(fake)
        self.assertEqual(fake.events[-3:], [
            ("write", "INIT1:CONT OFF"),
            ("write", "TRIG:SOUR INT"),
            ("write", "INIT1:CONT 1"),
        ])

    def test_rejects_not_ready_and_non_50_ohm_state(self):
        fake = FakeS4Vna()
        fake.values["SYST:READ?"] = "0"
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            capture(fake)
        self.assertFalse(any(kind == "write" for kind, _ in fake.events))

        fake = FakeS4Vna()
        fake.values["SENS:CORR:IMP?"] = "75"
        with self.assertRaisesRegex(ValueError, "expected 50"):
            capture(fake)
        self.assertFalse(any(kind == "write" for kind, _ in fake.events))


if __name__ == "__main__":
    unittest.main()
