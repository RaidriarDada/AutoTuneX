import tempfile
import unittest
from pathlib import Path

from vna.cmt_s11 import capture, decode_sweep, impedance, interpolate_at, save


class FakeCmtVna:
    def __init__(self):
        self.values = {
            "*IDN?": "Copper Mountain,TR1300/1,SN0001,1.0",
            "FORM:DATA?": "REAL",
            "CALC1:PAR1:DEF?": "S21",
            "TRIG:SOUR?": "INT",
            "INIT1:CONT?": "0",
            "SENS1:CORR:STAT?": "1",
            "SENS1:CORR:IMP?": "50",
            "*OPC?": "1",
            "SENS1:FREQ:DATA?": "50000000,51705000,53000000",
            "CALC1:TRAC1:DATA:SDAT?": "0.5,0.1,0.1,-0.05,0.4,0.2",
        }
        self.writes = []
        self.queries = []

    def query(self, command):
        self.queries.append(command)
        return self.values[command]

    def write(self, command):
        self.writes.append(command)


class SweepTest(unittest.TestCase):
    def test_capture_sends_documented_commands_and_restores_state(self):
        fake = FakeCmtVna()
        sweep, metadata = capture(fake)
        self.assertEqual(len(sweep), 3)
        self.assertEqual(metadata["calibration_enabled"], "1")
        self.assertIn("TRIG:SEQ:SING", fake.writes)
        self.assertLess(fake.queries.index("*OPC?"),
                        fake.queries.index("CALC1:TRAC1:DATA:SDAT?"))
        self.assertEqual(fake.writes[-4:], ["CALC1:PAR1:DEF S21", "FORM:DATA REAL",
                                           "INIT1:CONT 0", "TRIG:SOUR INT"])

    def test_rejects_wrong_array_length(self):
        with self.assertRaisesRegex(ValueError, "expected 4"):
            decode_sweep("1,2", "0.1,0.2")

    def test_existing_requires_s11_trace(self):
        fake = FakeCmtVna()
        with self.assertRaisesRegex(ValueError, "already measure S11"):
            capture(fake, fresh=False)
        self.assertNotIn("TRIG:SEQ:SING", fake.writes)

    def test_interpolation_impedance_and_file_output(self):
        sweep = [(50e6, 0.2 + 0.2j), (52e6, 0j)]
        self.assertAlmostEqual(interpolate_at(sweep, 51e6).real, 0.1)
        self.assertAlmostEqual(impedance(0j).real, 50)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "capture.csv"
            summary = save(sweep, {"idn": "fake"}, 51e6, out)
            self.assertTrue(out.exists())
            self.assertTrue(out.with_suffix(".json").exists())
            self.assertAlmostEqual(summary["s11_at_target_real"], 0.1)


if __name__ == "__main__":
    unittest.main()
