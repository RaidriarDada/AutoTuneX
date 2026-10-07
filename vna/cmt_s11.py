"""Capture a fresh complex S11 sweep from CMT VNA software over SCPI/TCP.

Python 3.9+. Install: python -m pip install pyvisa pyvisa-py
The CMT VNA application must be running with its Socket Server enabled.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys


Z0_OHM = 50.0


def parse_numbers(reply: str) -> list[float]:
    values = [float(item.strip()) for item in reply.strip().split(",") if item.strip()]
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("VNA returned an empty or non-finite ASCII numeric array")
    return values


def decode_sweep(frequency_reply: str, s11_reply: str) -> list[tuple[float, complex]]:
    frequencies = parse_numbers(frequency_reply)
    ri = parse_numbers(s11_reply)
    if len(frequencies) < 2:
        raise ValueError("At least two frequency points are required")
    if len(ri) != 2 * len(frequencies):
        raise ValueError(
            f"S11 has {len(ri)} numbers; expected {2 * len(frequencies)} "
            "(real, imaginary pairs)"
        )
    if any(b <= a for a, b in zip(frequencies, frequencies[1:])):
        raise ValueError("Frequency points are not strictly increasing; use a frequency sweep")
    return [(frequency, complex(ri[2 * i], ri[2 * i + 1]))
            for i, frequency in enumerate(frequencies)]


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


def capture(inst, channel: int = 1, trace: int = 1, fresh: bool = True):
    """Return (sweep, metadata). Restores temporary VNA display/trigger settings."""
    parameter = f"CALC{channel}:PAR{trace}:DEF"
    continuous = f"INIT{channel}:CONT"
    prior: dict[str, str | None] = {}
    metadata = {"idn": inst.query("*IDN?").strip(), "fresh_sweep": fresh}
    prior["format"] = inst.query("FORM:DATA?").strip()
    prior["parameter"] = inst.query(f"{parameter}?").strip()
    if fresh:
        prior["source"] = inst.query("TRIG:SOUR?").strip()
        prior["continuous"] = inst.query(f"{continuous}?").strip()
    try:
        inst.write("FORM:DATA ASC")
        system_z0 = float(inst.query(f"SENS{channel}:CORR:IMP?").strip())
        if not math.isclose(system_z0, Z0_OHM, rel_tol=0, abs_tol=1e-6):
            raise ValueError(f"VNA system impedance is {system_z0} ohm, expected 50 ohm")
        metadata["system_z0_ohm"] = system_z0
        if not fresh and prior["parameter"].upper() != "S11":
            raise ValueError("--existing requires the selected trace to already measure S11")
        if prior["parameter"].upper() != "S11":
            inst.write(f"{parameter} S11")
        metadata["calibration_enabled"] = inst.query(f"SENS{channel}:CORR:STAT?").strip()
        if fresh:
            inst.write(f"{continuous} ON")
            inst.write("TRIG:SOUR BUS")
            inst.write("TRIG:SEQ:SING")
            if inst.query("*OPC?").strip() != "1":
                raise RuntimeError("VNA did not report sweep completion (*OPC? != 1)")
        frequency_reply = inst.query(f"SENS{channel}:FREQ:DATA?")
        s11_reply = inst.query(f"CALC{channel}:TRAC{trace}:DATA:SDAT?")
        sweep = decode_sweep(frequency_reply, s11_reply)
    finally:
        # Restore the operator's state even when parsing or acquisition fails.
        restoration = []
        if prior.get("parameter", "").upper() != "S11":
            restoration.append(f"{parameter} {prior['parameter']}")
        if prior.get("format"):
            restoration.append(f"FORM:DATA {prior['format']}")
        if fresh:
            if prior.get("continuous"):
                restoration.append(f"{continuous} {prior['continuous']}")
            if prior.get("source"):
                restoration.append(f"TRIG:SOUR {prior['source']}")
        for command in restoration:
            try:
                inst.write(command)
            except Exception as exc:
                print(f"Warning: could not restore {command}: {exc}", file=sys.stderr)
    return sweep, metadata


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
            writer.writerow([frequency, gamma.real, gamma.imag, abs(gamma),
                             return_loss_db(gamma), z.real if z else "", z.imag if z else ""])
    output.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Computer running CMT VNA software")
    parser.add_argument("--port", type=int, default=5025, help="CMT Socket Server port")
    parser.add_argument("--channel", type=int, default=1)
    parser.add_argument("--trace", type=int, default=1)
    parser.add_argument("--target-hz", type=float, default=51.705e6)
    parser.add_argument("--timeout-ms", type=int, default=100000)
    parser.add_argument("--existing", action="store_true", help="Read displayed data without a new sweep")
    parser.add_argument("--output", type=Path, default=Path("s11_capture.csv"))
    args = parser.parse_args()
    if not (1 <= args.channel <= 9 and 1 <= args.trace <= 8):
        parser.error("For TRVNA, channel must be 1..9 and trace 1..8")
    if not (0 < args.port <= 65535 and args.timeout_ms > 0 and math.isfinite(args.target_hz)
            and args.target_hz > 0):
        parser.error("Invalid port, timeout, or target frequency")
    if args.output.suffix.lower() != ".csv":
        parser.error("--output must end in .csv")
    try:
        import pyvisa
    except ImportError:
        parser.exit(2, "Install dependencies: python -m pip install pyvisa pyvisa-py\n")
    manager = pyvisa.ResourceManager("@py")
    inst = None
    try:
        inst = manager.open_resource(f"TCPIP0::{args.host}::{args.port}::SOCKET")
        inst.read_termination = "\n"
        inst.write_termination = "\n"
        inst.timeout = args.timeout_ms
        sweep, metadata = capture(inst, args.channel, args.trace, not args.existing)
        summary = save(sweep, metadata, args.target_hz, args.output)
        print(f"VNA: {summary['idn']}")
        print(f"Saved {summary['points']} points to {args.output} and {args.output.with_suffix('.json')}")
        print(f"At {summary['target_hz']/1e6:.6f} MHz: "
              f"RL={summary['return_loss_at_target_db']!s} dB, "
              f"Z={summary['impedance_at_target_real_ohm']!s} "
              f"+ j{summary['impedance_at_target_imag_ohm']!s} ohm")
        if summary["calibration_enabled"] in ("0", "OFF"):
            print("Warning: VNA reports correction/calibration disabled", file=sys.stderr)
        return 0
    except Exception as exc:
        print(f"Capture failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if inst is not None:
            inst.close()
        manager.close()


if __name__ == "__main__":
    raise SystemExit(main())
