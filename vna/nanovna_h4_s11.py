"""Capture one complex S11 sweep from a NanoVNA-H4 USB serial shell.

Python 3.9+. Install the only external dependency with ``pip install pyserial``.
The supported NanoVNA shell command is ``scan START STOP POINTS 3``: output
mask 3 requests frequency and CH0/S11 real and imaginary values. Device
calibration is applied only when enabled on the NanoVNA.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
from typing import Protocol
from datetime import datetime, timezone
import csv


PROMPT = b"ch> "
MAX_REPLY_BYTES = 1024 * 1024

Z0_OHM = 50.0


class SerialShell(Protocol):
    def reset_input_buffer(self) -> None: ...
    def write(self, data: bytes) -> int: ...
    def flush(self) -> None: ...
    def read_until(self, expected: bytes, size: int | None = None) -> bytes: ...


def query(shell: SerialShell, command: str) -> str:
    """Send one shell command and read through the next NanoVNA prompt."""
    shell.reset_input_buffer()
    shell.write((command + "\r").encode("ascii"))
    shell.flush()
    # A prompt from USB connection setup can arrive just after the input flush.
    # Ignore that prompt; the command's reply follows the next one.
    for _ in range(3):
        reply = shell.read_until(PROMPT, size=MAX_REPLY_BYTES)
        if not reply.endswith(PROMPT):
            break
        if reply != PROMPT:
            return reply[:-len(PROMPT)].decode("ascii", errors="replace")
    raise TimeoutError(f"No complete NanoVNA reply to {command!r}; check port and timeout")


def _body_lines(reply: str, command: str) -> list[str]:
    lines = [line.strip().removeprefix("ch> ") for line in reply.splitlines()]
    return [line for line in lines if line and line != command and line != "ch>"]


def parse_scan(reply: str, command: str, expected_points: int) -> list[tuple[float, complex]]:
    """Validate ASCII `scan ... 3` output; reject partial or malformed sweeps."""
    sweep = []
    for line in _body_lines(reply, command):
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Unexpected NanoVNA scan output: {line[:120]}")
        try:
            frequency = int(parts[0])
            real, imag = float(parts[1]), float(parts[2])
        except ValueError as exc:
            raise ValueError(f"Invalid NanoVNA scan row: {line[:120]}") from exc
        if frequency <= 0 or not (math.isfinite(real) and math.isfinite(imag)):
            raise ValueError(f"Non-finite or invalid NanoVNA scan row: {line[:120]}")
        sweep.append((float(frequency), complex(real, imag)))
    if len(sweep) != expected_points:
        raise ValueError(f"NanoVNA returned {len(sweep)} points; expected {expected_points}")
    if any(right[0] <= left[0] for left, right in zip(sweep, sweep[1:])):
        raise ValueError("NanoVNA scan frequencies are not strictly increasing")
    return sweep


def capture(shell: SerialShell, start_hz: int, stop_hz: int, points: int = 101):
    """Return (sweep, metadata) from one fresh scan.

    The firmware's scan command pauses its normal display sweep afterward.
    This function does not issue `resume`, because it cannot determine whether
    the operator had already paused the device before capture.
    """
    if not (0 < start_hz < stop_hz <= 4_294_967_295):
        raise ValueError("Require 0 < start_hz < stop_hz <= 4294967295")
    if not 2 <= points <= 401:
        raise ValueError("points must be 2..401 (actual maximum depends on firmware)")

    info = _body_lines(query(shell, "info"), "info")
    if not info or info[0] == "info?":
        raise RuntimeError("NanoVNA did not recognize the info command")
    max_points_match = re.search(r"\bp:(\d+)\b", " ".join(info))
    if max_points_match and points > int(max_points_match.group(1)):
        raise ValueError(f"Firmware supports at most {max_points_match.group(1)} points")

    cal_lines = _body_lines(query(shell, "cal"), "cal")
    if any(line == "cal?" or line.startswith("usage:") for line in cal_lines):
        raise RuntimeError("NanoVNA did not recognize the cal status query")
    cal_status = " ".join(cal_lines)

    command = f"scan {start_hz} {stop_hz} {points} 3"
    sweep = parse_scan(query(shell, command), command, points)
    if sweep[0][0] < start_hz or sweep[-1][0] > stop_hz:
        raise ValueError("NanoVNA returned frequencies outside the requested range")
    metadata = {
        "idn": info[0],
        "device_info": info,
        "calibration_status": cal_status,
        "calibration_applied": "cal'ed" in cal_status.split(),
        "command": command,
        "fresh_sweep": True,
    }
    return sweep, metadata

def impedance(gamma: complex) -> complex | None:
    if abs(1 - gamma) < 1e-12:
        return None
    return Z0_OHM * (1 + gamma) / (1 - gamma)


def return_loss_db(gamma: complex) -> float | None:
    magnitude = abs(gamma)
    return -20 * math.log10(magnitude) if magnitude > 0 else None


def interpolate_at(sweep: list[tuple[float, complex]], target_hz: float) -> complex:
    if not sweep[0][0] <= target_hz <= sweep[-1][0]:
        raise ValueError(
            f"Target {target_hz:g} Hz is outside sweep "
            f"[{sweep[0][0]:g}, {sweep[-1][0]:g}] Hz"
        )
    for (f0, g0), (f1, g1) in zip(sweep, sweep[1:]):
        if f0 <= target_hz <= f1:
            fraction = (target_hz - f0) / (f1 - f0)
            return g0 + fraction * (g1 - g0)
    return sweep[-1][1]  # One-point sweeps are rejected by the VNA, but handle endpoint.

def save(sweep, metadata: dict, target_hz: float, output: Path) -> dict:
    target_gamma = interpolate_at(sweep, target_hz)
    target_z = impedance(target_gamma)
    best_frequency, best_gamma = min(sweep, key=lambda row: abs(row[1]))
    summary = {
        **metadata,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "reference_ohm": Z0_OHM,
        "points": len(sweep),
        "start_hz": sweep[0][0],
        "stop_hz": sweep[-1][0],
        "target_hz": target_hz,
        "s11_at_target_real": target_gamma.real,
        "s11_at_target_imag": target_gamma.imag,
        "return_loss_at_target_db": return_loss_db(target_gamma),
        "impedance_at_target_real_ohm": target_z.real if target_z else None,
        "impedance_at_target_imag_ohm": target_z.imag if target_z else None,
        "best_match_in_sweep_hz": best_frequency,
        "best_match_in_sweep_return_loss_db": return_loss_db(best_gamma),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["frequency_hz", "s11_real", "s11_imag", "s11_mag",
                         "return_loss_db", "impedance_real_ohm", "impedance_imag_ohm"])
        for frequency, gamma in sweep:
            z = impedance(gamma)
            writer.writerow([frequency, gamma.real, gamma.imag, abs(gamma), return_loss_db(gamma), z.real if z else "", z.imag if z else ""])
    output.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="NanoVNA USB serial port, e.g. COM4")
    parser.add_argument("--baud", type=int, default=115200,
                        help="Serial baud setting; USB CDC firmware usually ignores it")
    parser.add_argument("--start-hz", type=int, default=45_000_000)
    parser.add_argument("--stop-hz", type=int, default=60_000_000)
    parser.add_argument("--points", type=int, default=101)
    parser.add_argument("--target-hz", type=float, default=51_705_000)
    parser.add_argument("--timeout", type=float, default=60,
                        help="Seconds allowed for each shell response")
    parser.add_argument("--output", type=Path, default=Path("nanovna_h4_s11.csv"))
    args = parser.parse_args()
    if not (0 < args.start_hz < args.stop_hz <= 4_294_967_295):
        parser.error("Require 0 < --start-hz < --stop-hz <= 4294967295")
    if not 2 <= args.points <= 401:
        parser.error("--points must be 2..401; the firmware may support fewer")
    if not (math.isfinite(args.target_hz) and args.start_hz <= args.target_hz <= args.stop_hz):
        parser.error("--target-hz must be within the requested sweep")
    if not (args.baud > 0 and math.isfinite(args.timeout) and args.timeout > 0):
        parser.error("--baud and --timeout must be positive")
    if args.output.suffix.lower() != ".csv":
        parser.error("--output must end in .csv")
    try:
        import serial
    except ImportError:
        parser.exit(2, "Install the serial driver: python -m pip install pyserial\n")
    try:
        with serial.Serial(args.port, args.baud, timeout=args.timeout, write_timeout=5) as shell:
            sweep, metadata = capture(shell, args.start_hz, args.stop_hz, args.points)
        metadata["serial_port"] = args.port
        summary = save(sweep, metadata, args.target_hz, args.output)
    except Exception as exc:
        print(f"Capture failed: {exc}", file=sys.stderr)
        return 1
    print(f"Saved {summary['points']} S11 points to {args.output}")
    print(f"Target {args.target_hz / 1e6:.6f} MHz: "
          f"return loss {summary['return_loss_at_target_db']!s} dB")
    if not summary["calibration_applied"]:
        print("Warning: NanoVNA did not report applied calibration; check the cal status",
              file=sys.stderr)
    print("NanoVNA scan leaves the display sweep paused; use the device's Resume control if needed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
