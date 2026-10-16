"""Capture one S11 sweep from a local S4VNA application and its 808/1 VNA.

Run from the repository root with ``python -m vna.s4vna_s11``. The S4VNA
application must be running, connected to the instrument (not in Demo Mode),
and serving SCPI on its TCP/IP Socket port. This module talks to the application,
not directly to the VNA's USB interface.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

# Reuse the transport-independent array decoder and CSV/JSON writer. The
# S4VNA acquisition commands below are separate from the older TRVNA driver.
from vna.cmt_s11 import Z0_OHM, decode_sweep, save


def capture(inst, channel: int = 1, trace: int = 1, fresh: bool = True):
    """Read complex S11 values, optionally triggering a new sweep.

    The caller owns the connection. We leave frequency, power, IF bandwidth,
    point count, calibration, and trace selection under the operator's control.
    """
    if not (1 <= channel <= 16 and 1 <= trace <= 16):
        raise ValueError("S4VNA channel and trace numbers must be 1..16")

    # Identify the application and wait for its hardware-ready state. Demo Mode
    # can also simulate an instrument, so the operator must disable it in S4VNA.
    idn = inst.query("*IDN?").strip()
    if inst.query("SYST:READ?").strip() != "1":
        raise RuntimeError("S4VNA is not ready; check USB, power, and Demo Mode")

    # The shared CSV/JSON writer converts gamma to impedance using 50 ohms.
    # Reject a different system Z0 rather than silently saving wrong impedance.
    z0 = float(inst.query("SENS:CORR:IMP?").strip())
    if not math.isfinite(z0) or not math.isclose(z0, Z0_OHM, abs_tol=1e-6):
        raise ValueError(f"S4VNA system impedance is {z0} ohm; expected {Z0_OHM:g} ohm")

    # Reading SDAT returns complex data for the chosen trace. Requiring S11
    # avoids changing the operator's trace or assuming another calibration fits.
    parameter = inst.query(f"CALC{channel}:PAR{trace}:DEF?").strip().upper()
    if parameter != "S11":
        raise ValueError(
            f"Channel {channel} trace {trace} measures {parameter!r}; set it to S11 in S4VNA"
        )
    calibration = inst.query(f"SENS{channel}:CORR:STAT?").strip()
    metadata = {
        "idn": idn,
        "fresh_sweep": fresh,
        "channel": channel,
        "trace": trace,
        "system_z0_ohm": z0,
        "calibration_enabled": calibration,
    }

    # A fresh sweep requires BUS triggering. Save both affected settings so the
    # operator gets the original trigger behavior back even if a query fails.
    prior_source = prior_continuous = None
    changed_trigger = False
    if fresh:
        prior_source = inst.query("TRIG:SOUR?").strip()
        prior_continuous = inst.query(f"INIT{channel}:CONT?").strip()
    try:
        if fresh:
            changed_trigger = True
            inst.write(f"INIT{channel}:CONT OFF")  # Hold before changing source.
            inst.write("TRIG:SOUR BUS")
            inst.write(f"INIT{channel}:CONT ON")  # Enter trigger-waiting state.
            inst.write("TRIG:SEQ:SING")
            if inst.query("*OPC?").strip() != "1":
                raise RuntimeError("S4VNA did not confirm sweep completion")

        # Frequency has N values; corrected S11 has 2N real/imaginary values.
        # The socket uses ASCII arrays, so no FORM:DATA command is sent here.
        frequencies = inst.query(f"SENS{channel}:FREQ:DATA?")
        s11 = inst.query(f"CALC{channel}:TRAC{trace}:DATA:SDAT?")
        sweep = decode_sweep(frequencies, s11)
        return sweep, metadata
    finally:
        if changed_trigger:
            # Put the channel in Hold before restoring the global source; then
            # restore its prior continuous/single state. Continue after a failed
            # restoration so every setting gets an attempt.
            for command in (
                f"INIT{channel}:CONT OFF",
                f"TRIG:SOUR {prior_source}",
                f"INIT{channel}:CONT {prior_continuous}",
            ):
                try:
                    inst.write(command)
                except Exception as exc:
                    print(f"Warning: could not restore {command}: {exc}", file=sys.stderr)


def main() -> int:
    """Parse bench settings, open the localhost socket, capture, and save."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="PC running S4VNA")
    parser.add_argument("--port", type=int, default=5025, help="S4VNA Socket Server port")
    parser.add_argument("--channel", type=int, default=1)
    parser.add_argument("--trace", type=int, default=1)
    parser.add_argument("--target-hz", type=float, default=51.705e6)
    parser.add_argument("--timeout-ms", type=int, default=100000)
    parser.add_argument("--existing", action="store_true",
                        help="Read current trace without triggering; hold it in S4VNA first")
    parser.add_argument("--output", type=Path, default=Path("s4vna_s11.csv"))
    args = parser.parse_args()
    if not (1 <= args.channel <= 16 and 1 <= args.trace <= 16):
        parser.error("S4VNA channel and trace numbers must be 1..16")
    if not (0 < args.port <= 65535 and args.timeout_ms > 0):
        parser.error("Port must be 1..65535 and timeout must be positive")
    if not (math.isfinite(args.target_hz) and args.target_hz > 0):
        parser.error("Target frequency must be a positive finite number")
    if args.output.suffix.lower() != ".csv":
        parser.error("--output must end in .csv")

    # PyVISA-py provides the socket transport; the S4VNA application handles
    # the USB hardware and SCPI commands. Newline terminates each ASCII reply.
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
            print("Warning: S4VNA reports error correction disabled", file=sys.stderr)
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
