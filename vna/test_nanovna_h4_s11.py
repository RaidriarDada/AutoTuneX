import tempfile
import unittest
from pathlib import Path

from vna.cmt_s11 import save
from vna.nanovna_h4_s11 import capture, parse_scan, query


class FakeSerial:
    def __init__(self, replies):
        self.replies = replies
        self.commands = []

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.commands.append(data.decode("ascii").strip())
        return len(data)

    def flush(self):
        pass

    def read_until(self, expected, size=None):
        reply = self.replies[self.commands[-1]]
        return reply.pop(0) if isinstance(reply, list) else reply


class NanoVnaH4Test(unittest.TestCase):
    def test_capture_one_scan_and_save(self):
        command = "scan 50000000 52000000 3 3"
        fake = FakeSerial({
            "info": b"info\r\nBoard: NanoVNA-H4\r\nVersion: 1.2 [p:401]\r\nch> ",
            "cal": b"cal\r\nload open short Es Er cal'ed\r\nch> ",
            command: ("ch> " + command + "\r\n50000000 0.2 0.1\r\n"
                      "51000000 0.1 -0.1\r\n52000000 0.3 0.2\r\nch> ").encode(),
        })
        sweep, metadata = capture(fake, 50_000_000, 52_000_000, 3)
        self.assertEqual(fake.commands, ["info", "cal", command])
        self.assertEqual(sweep[1], (51_000_000, 0.1 - 0.1j))
        self.assertTrue(metadata["calibration_applied"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one_sweep.csv"
            summary = save(sweep, metadata, 51_000_000, path)
            self.assertEqual(summary["points"], 3)
            self.assertEqual(len(path.read_text().splitlines()), 4)

    def test_rejects_partial_and_bad_scan_data(self):
        command = "scan 1 3 3 3"
        with self.assertRaisesRegex(ValueError, "expected 3"):
            parse_scan("1 0.1 0.2\n2 0.2 0.3\n", command, 3)
        with self.assertRaisesRegex(ValueError, "Unexpected NanoVNA"):
            parse_scan("scan?\n", command, 3)
        with self.assertRaisesRegex(ValueError, "not strictly increasing"):
            parse_scan("1 0 0\n2 0 0\n2 0 0\n", command, 3)

    def test_rejects_points_above_firmware_maximum(self):
        fake = FakeSerial({
            "info": b"Board: NanoVNA-H4\r\nVersion: 1.2 [p:101]\r\nch> ",
        })
        with self.assertRaisesRegex(ValueError, "at most 101"):
            capture(fake, 50_000_000, 52_000_000, 201)
        self.assertEqual(fake.commands, ["info"])

    def test_reports_timeout_without_complete_prompt(self):
        fake = FakeSerial({"info": b"Board: NanoVNA-H4\r\n"})
        with self.assertRaises(TimeoutError):
            query(fake, "info")

    def test_ignores_connection_prompt_before_reply(self):
        fake = FakeSerial({"info": [b"ch> ", b"Board: NanoVNA-H4\r\nch> "]})
        self.assertEqual(query(fake, "info"), "Board: NanoVNA-H4\r\n")


if __name__ == "__main__":
    unittest.main()
