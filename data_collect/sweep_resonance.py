#!/usr/bin/env python3
"""

鐢ㄦ硶:
    python sweep_resonance.py                     # 1..60
    python sweep_resonance.py --points 4001       # 4001 鐐? 鏇寸粏鐨勭綉鏍?    python sweep_resonance.py --start 1 --end 5   # 鍏堣窇 5 涓?    python sweep_resonance.py --repeats 1         # 涓嶅钩鍧? 鏈€蹇?"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
import time
from datetime import datetime

try:
    import serial
except ImportError:  # pragma: no cover
    sys.exit("缂哄皯 pyserial: pip install pyserial")

from sweep_states import find_arduino, handshake, read_state_line, sleep_until
from sweep_vna_states import Scpi, capture, z_from_gamma


def noise_sigma(values: list[float]) -> float:
    """鐢ㄤ簩闃跺樊鍒嗙殑涓綅鏁颁及鍣０骞呭害. 瀵圭櫧鍣０ E|螖虏x| 鈮?1.96 蟽."""
    d2 = sorted(abs(values[i - 1] - 2.0 * values[i] + values[i + 1])
                for i in range(1, len(values) - 1))
    if not d2:
        return 0.0
    return d2[len(d2) // 2] / 1.96


def zero_crossings(freqs: list[float], x: list[float],
                   threshold: float | None = None,
                   merge_hz: float | None = None):
    """甯︽粸鍥?+ 閭昏繎鍚堝苟鐨勮繃闆舵娴?

    杩斿洖 ([(i_low, i_high, f_mid), ...], threshold).

    涓ゅ眰闂瑕佸垎寮€娌?
      1. 鍣０鎶栧姩: 闆剁偣闄勮繎 X 鍙湁 卤0.1 惟 鑰屽櫔澹版湁 0.15 惟, 涓€涓繃闆朵細琚垏鎴?         鍗佸嚑涓亣杩囬浂. 鐢ㄦ粸鍥?(鍙湁鏄庣‘瓒婅繃 +thr 鍐嶈秺杩?-thr 鎵嶇畻) 鍘嬫帀.
      2. 甯﹀唴鐪熸湁澶氫釜杩囬浂鐐? 鎴栨粸鍥炲悗浠嶆湁娈嬩綑鎶栧姩: 鍐嶇敤 merge_hz 鎶婇潬寰楀お杩?         鐨勮繃闆剁偣鍚堝苟鎴愪竴涓? 棰戠巼鍙栨暣浣撶殑涓偣.

    f_mid 浠嶆槸涓や晶棰戠巼鐨勫钩鍧囧€?鈥斺€?鎸変綘鐨勮姹備笉鍋氱簿缁嗘彃鍊?
    """
    if threshold is None:
        span = max(x) - min(x)
        threshold = max(3.0 * noise_sigma(x), 0.005 * span)
    if merge_hz is None:
        merge_hz = 0.01 * (freqs[-1] - freqs[0])

    raw = []
    side = 0
    edge = None
    for i, v in enumerate(x):
        if v > threshold:
            if side == -1 and edge is not None:
                raw.append((edge, i, 0.5 * (freqs[edge] + freqs[i])))
            side, edge = 1, i
        elif v < -threshold:
            if side == 1 and edge is not None:
                raw.append((edge, i, 0.5 * (freqs[edge] + freqs[i])))
            side, edge = -1, i

    merged: list[tuple[int, int, float]] = []
    for lo, hi, f_mid in raw:
        if merged and f_mid - merged[-1][2] <= merge_hz:
            plo, _, _ = merged[-1]
            merged[-1] = (plo, hi, 0.5 * (freqs[plo] + freqs[hi]))
        else:
            merged.append((lo, hi, f_mid))
    return merged, threshold


def main() -> int:
    ap = argparse.ArgumentParser(description="sweep 60 states, find the X=0 crossing")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5025)
    ap.add_argument("--arduino", help="Arduino serial port (auto-detect)")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=60)
    ap.add_argument("--settle", type=float, default=20.0,
                    help="seconds to wait after the relay change before sweeping")
    ap.add_argument("--start-hz", type=float, default=20000.0,
                    help="sweep start frequency (default 20 kHz)")
    ap.add_argument("--stop-hz", type=float, default=200000.0,
                    help="sweep stop frequency (default 200 kHz)")
    ap.add_argument("--keep-span", action="store_true",
                    help="use whatever span the VNA already has")
    ap.add_argument("--repeats", type=int, default=5,
                    help="sweeps per state; averaged before the crossing search")
    ap.add_argument("--points", type=int, default=None,
                    help="set the sweep point count (leave unset to keep the VNA's)")
    ap.add_argument("--timeout", type=float, default=20.0, help="SCPI reply timeout")
    ap.add_argument("--hysteresis", type=float, default=None,
                    help="override the hysteresis band in ohm (default: 3x noise, auto)")
    ap.add_argument("--merge-hz", type=float, default=None,
                    help="merge crossings closer than this (default: 1%% of the span)")
    ap.add_argument("-o", "--out", default=None, help="output CSV")
    ap.add_argument("--traces", default="auto",
                    help="per-state curves; 'auto' = <out>_traces.csv, 'none' = off")
    args = ap.parse_args()

    vna = Scpi(args.host, args.port, args.timeout)
    try:
        idn = vna.query("*IDN?")
    except OSError as exc:
        print(f"cannot reach the VNA at {args.host}:{args.port} - {exc}")
        return 1
    print(f"VNA     : {idn}")

    a_port = find_arduino(args.arduino)
    if not a_port:
        print("Arduino not found. available ports:")
        from serial.tools import list_ports
        for p in list_ports.comports():
            print(f"  {p.device:8} {p.description}")
        return 1
    print(f"Arduino : {a_port}")

    try:
        orig_start = float(vna.query("SENS1:FREQ:STAR?"))
        orig_stop = float(vna.query("SENS1:FREQ:STOP?"))
        npts = int(float(vna.query("SENS1:SWE:POIN?")))
    except (ValueError, OSError) as exc:
        print(f"cannot read the VNA sweep setup: {exc}")
        return 1

    if args.keep_span:
        f0_hz, f1_hz = orig_start, orig_stop
    else:
        vna.write(f"SENS1:FREQ:STAR {args.start_hz:.0f}")
        vna.write(f"SENS1:FREQ:STOP {args.stop_hz:.0f}")
        time.sleep(0.3)
        f0_hz = float(vna.query("SENS1:FREQ:STAR?"))
        f1_hz = float(vna.query("SENS1:FREQ:STOP?"))

    orig_points = npts
    if args.points and args.points != npts:
        vna.write(f"SENS1:SWE:POIN {args.points}")
        npts = int(float(vna.query("SENS1:SWE:POIN?")))
        if npts != args.points:
            print(f"warning: VNA clamped points {args.points} -> {npts}")

    step_hz = (f1_hz - f0_hz) / max(1, npts - 1)
    print(f"Sweep   : {f0_hz/1e3:.3f} kHz .. {f1_hz/1e3:.3f} kHz, "
          f"{npts} pts, {step_hz:.1f} Hz/step")
    if step_hz > 200:
        print(f"note: {step_hz:.0f} Hz/step is coarse for a crossing; "
              "consider --points 4001")

    out = args.out or f"resonance_{datetime.now():%Y%m%d_%H%M%S}.csv"
    traces_path = None
    if args.traces.lower() != "none":
        traces_path = (args.traces if args.traces != "auto"
                       else out[:-4] + "_traces.csv" if out.lower().endswith(".csv")
                       else out + "_traces.csv")
    print(f"Output  : {out}")
    if traces_path:
        print(f"Traces  : {traces_path}")
    print()

    ard = serial.Serial(a_port, 115200, timeout=0.2)
    if not handshake(ard):
        print("Arduino did not respond to 'status'. Is relay_sequencer.ino running?")
        return 1
    print("Arduino ready.\n")

    old_trigger = "INT"
    try:
        old_trigger = vna.query("TRIG:SOUR?").strip()
    except OSError:
        pass
    vna.write("TRIG:SOUR BUS")

    trace_fh = open(traces_path, "w", newline="", encoding="utf-8") if traces_path else None
    trace_w = None
    if trace_fh:
        trace_w = csv.writer(trace_fh)
        trace_w.writerow(["state", "frequency_hz", "s11_real", "s11_imag",
                          "x_reactance_ohm"])

    rows = []
    missing = []
    t_start = time.time()
    try:
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["state", "expected_nF", "f0_Hz", "R_ohm", "Zmag_ohm",
                        "n_crossings", "all_crossings_Hz", "f0_std_Hz",
                        "hyst_ohm", "n_sweeps", "word", "iso_time"])

            for n in range(args.start, args.end + 1):
                ard.write(f"{n}\n".encode())
                m = read_state_line(ard, n)
                if m is None:
                    print(f"state {n}: no reply, skipped")
                    continue
                t_echo = time.time()
                exp_nf, word = m.group(3), m.group(5)
                print(f"[{n:2d}] -> {exp_nf:>7} nF expected   {word}", flush=True)

                sleep_until(t_echo + args.settle)

                f = None
                acc_re = acc_im = None
                per_sweep_f0: list[float] = []

                for _ in range(args.repeats):
                    fk, rek, imk = capture(vna)
                    if f is None:
                        f = fk
                        acc_re = list(rek)
                        acc_im = list(imk)
                    else:
                        if (len(fk) != len(f) or abs(fk[0] - f[0]) > 1e-6
                                or abs(fk[-1] - f[-1]) > 1e-6):
                            raise RuntimeError("frequency axis changed between sweeps")
                        for i, v in enumerate(rek):
                            acc_re[i] += v
                        for i, v in enumerate(imk):
                            acc_im[i] += v

                    xk = [z.imag for z in z_from_gamma(rek, imk)]
                    ck, _ = zero_crossings(fk, xk, args.hysteresis, args.merge_hz)
                    if ck:
                        per_sweep_f0.append(ck[0][2])

                re_ = [v / args.repeats for v in acc_re]
                im = [v / args.repeats for v in acc_im]
                zs = z_from_gamma(re_, im)
                x = [z.imag for z in zs]

                crosses, thr_used = zero_crossings(f, x, args.hysteresis, args.merge_hz)
                std_s = (f"{statistics.pstdev(per_sweep_f0):.1f}"
                         if len(per_sweep_f0) > 1 else "")

                if crosses:
                    i, j, f0 = crosses[0]
                    r_avg = 0.5 * (zs[i].real + zs[j].real)
                    z_avg = 0.5 * (abs(zs[i]) + abs(zs[j]))
                    all_c = ";".join(f"{c[2]:.1f}" for c in crosses)
                    note = ""
                    if len(crosses) > 1:
                        note = f"   ({len(crosses)} crossings, using the first)"
                    print(f"     X=0 at {f0/1e3:9.3f} kHz   R = {r_avg:7.1f} ohm"
                          f"   |Z| = {z_avg:7.1f} ohm{note}")
                    rows.append([n, exp_nf, f"{f0:.1f}", f"{r_avg:.2f}",
                                 f"{z_avg:.2f}", len(crosses), all_c, std_s,
                                 f"{thr_used:.3f}", args.repeats, word,
                                 datetime.now().isoformat(timespec="seconds")])
                else:
                    direction = "positive" if all(v > 0 for v in x) else "negative"
                    print(f"     no X=0 in this window - X stays {direction}"
                          "   <-- resonance outside the sweep")
                    missing.append(n)
                    rows.append([n, exp_nf, "", "", "", 0, "", std_s, "",
                                 args.repeats, word,
                                 datetime.now().isoformat(timespec="seconds")])

                w.writerow(rows[-1])
                fh.flush()

                if trace_w:
                    for ff, rr, ii, zz in zip(f, re_, im, zs):
                        trace_w.writerow([n, f"{ff:.1f}", f"{rr:.6e}",
                                          f"{ii:.6e}", f"{zz.imag:.6e}"])

                done = len(rows)
                avg_s = (time.time() - t_start) / done
                left = avg_s * (args.end - args.start + 1 - done)
                print(f"     [{done} done, ~{left / 60:.1f} min left]", flush=True)

    except KeyboardInterrupt:
        print("\nstopped by Ctrl+C")
    finally:
        try:
            if npts != orig_points:
                vna.write(f"SENS1:SWE:POIN {orig_points}")
            if not args.keep_span:
                vna.write(f"SENS1:FREQ:STAR {orig_start:.0f}")
                vna.write(f"SENS1:FREQ:STOP {orig_stop:.0f}")
            vna.write(f"TRIG:SOUR {old_trigger}")
        except OSError:
            pass
        ard.write(b"0\n")
        ard.close()
        if trace_fh:
            trace_fh.close()

    dur = time.time() - t_start
    found = len(rows) - len(missing)
    print(f"\n{len(rows)} states in {dur/60:.1f} min -> {out}")
    print(f"{found} found an X=0 crossing, {len(missing)} did not.")
    if missing:
        print("no crossing: " + ", ".join(str(s) for s in missing))
        print("If most states are missing, the resonance sits outside "
              f"{f0_hz/1e3:.1f}-{f1_hz/1e3:.1f} kHz and the span needs to move.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

