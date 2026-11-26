#!/usr/bin/env python3
"""
单个状态的诊断图: 扫一次 S11, 换算成 Zin, 把 Re(Z) 和 Im(Z) 画出来.

用途: 肉眼确认
  - Re(Z) 和 Im(Z) 随频率到底长什么样
  - X 的过零点是单值还是多值
  - 零点附近的噪声是否和信号同量级 (这决定过零判据能不能用)

用法:
    python plot_state.py --state 6
    python plot_state.py --state 6 --points 4001 --repeats 3
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    import serial
except ImportError:  # pragma: no cover
    sys.exit("缺少 pyserial: pip install pyserial")

from sweep_states import find_arduino, handshake, read_state_line, sleep_until
from sweep_vna_states import Scpi, capture, z_from_gamma
from sweep_resonance import noise_sigma, zero_crossings


def main() -> int:
    ap = argparse.ArgumentParser(description="plot Re(Z) and Im(Z) for one state")
    ap.add_argument("--state", type=int, default=6)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5025)
    ap.add_argument("--arduino", default=None)
    ap.add_argument("--points", type=int, default=4001)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--settle", type=float, default=20.0,
                    help="seconds to wait after the relay change before sweeping")
    ap.add_argument("--start-hz", type=float, default=20000.0)
    ap.add_argument("--stop-hz", type=float, default=200000.0)
    ap.add_argument("--keep-span", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--csv", default="auto")
    args = ap.parse_args()

    vna = Scpi(args.host, args.port, 20.0)
    print(f"VNA     : {vna.query('*IDN?')}")

    a_port = find_arduino(args.arduino)
    if not a_port:
        print("Arduino not found.")
        return 1

    orig_start = float(vna.query("SENS1:FREQ:STAR?"))
    orig_stop = float(vna.query("SENS1:FREQ:STOP?"))
    if not args.keep_span:
        vna.write(f"SENS1:FREQ:STAR {args.start_hz:.0f}")
        vna.write(f"SENS1:FREQ:STOP {args.stop_hz:.0f}")
        time.sleep(0.3)
    f0_hz = float(vna.query("SENS1:FREQ:STAR?"))
    f1_hz = float(vna.query("SENS1:FREQ:STOP?"))
    orig_points = int(float(vna.query("SENS1:SWE:POIN?")))
    if args.points and args.points != orig_points:
        vna.write(f"SENS1:SWE:POIN {args.points}")
    npts = int(float(vna.query("SENS1:SWE:POIN?")))
    step = (f1_hz - f0_hz) / max(1, npts - 1)
    print(f"Sweep   : {f0_hz/1e3:.3f} .. {f1_hz/1e3:.3f} kHz, {npts} pts, {step:.2f} Hz/step")

    ard = serial.Serial(a_port, 115200, timeout=0.2)
    if not handshake(ard):
        print("Arduino did not answer 'status'.")
        return 1

    old_trig = "INT"
    try:
        old_trig = vna.query("TRIG:SOUR?").strip()
    except OSError:
        pass
    vna.write("TRIG:SOUR BUS")

    try:
        ard.write(f"{args.state}\n".encode())
        m = read_state_line(ard, args.state)
        if m is None:
            print(f"state {args.state}: no reply")
            return 1
        exp_nf, word = m.group(3), m.group(5)
        print(f"State   : {args.state}  expected {exp_nf} nF  word {word}")
        sleep_until(time.time() + args.settle)

        f = acc_re = acc_im = None
        for _ in range(args.repeats):
            fk, rek, imk = capture(vna)
            if f is None:
                f, acc_re, acc_im = fk, list(rek), list(imk)
            else:
                for i, v in enumerate(rek):
                    acc_re[i] += v
                for i, v in enumerate(imk):
                    acc_im[i] += v
        re_ = [v / args.repeats for v in acc_re]
        im = [v / args.repeats for v in acc_im]
    finally:
        try:
            vna.write(f"TRIG:SOUR {old_trig}")
            if npts != orig_points:
                vna.write(f"SENS1:SWE:POIN {orig_points}")
            if not args.keep_span:
                vna.write(f"SENS1:FREQ:STAR {orig_start:.0f}")
                vna.write(f"SENS1:FREQ:STOP {orig_stop:.0f}")
        except OSError:
            pass
        ard.write(b"0\n")
        ard.close()

    zs = z_from_gamma(re_, im)
    rz = [z.real for z in zs]
    xz = [z.imag for z in zs]
    fk_hz = [v / 1e3 for v in f]

    crosses, thr = zero_crossings(f, xz)
    raw = sum(1 for i in range(len(xz) - 1) if (xz[i] > 0) != (xz[i + 1] > 0))
    sigma = noise_sigma(xz)

    print(f"\nR range : {min(rz):8.2f} .. {max(rz):8.2f} ohm")
    print(f"X range : {min(xz):8.2f} .. {max(xz):8.2f} ohm")
    print(f"noise   : sigma = {sigma:.4f} ohm,  hysteresis band = +/-{thr:.4f} ohm")
    print(f"crossings: raw sign changes = {raw},  after hysteresis+merge = {len(crosses)}")
    for lo, hi, fm in crosses:
        print(f"   X=0 near {fm/1e3:9.3f} kHz   R = {0.5*(zs[lo].real+zs[hi].real):7.2f} ohm")

    out = args.out or f"state{args.state}_Z.png"
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)

    ax1.plot(fk_hz, rz, lw=1.2, color="#1f77b4")
    ax1.set_ylabel("Re(Zin)  [ohm]")
    ax1.set_title(f"State {args.state}:  expected C_eq = {exp_nf} nF,  "
                  f"{npts} points, {args.repeats} sweep(s)")
    ax1.grid(True, alpha=0.3)

    ax2.plot(fk_hz, xz, lw=1.2, color="#d62728", label="Im(Zin)")
    ax2.axhline(0, color="k", lw=0.9)
    ax2.axhspan(-thr, thr, color="grey", alpha=0.18,
                label=f"hysteresis +/-{thr:.2f} ohm")
    ax2.set_ylabel("Im(Zin)  [ohm]")
    ax2.set_xlabel("frequency  [kHz]")
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc="best", fontsize=8)

    for lo, hi, fm in crosses:
        for ax in (ax1, ax2):
            ax.axvline(fm / 1e3, color="g", ls="--", lw=1.0)
        ax2.annotate(f"{fm/1e3:.2f} kHz", xy=(fm / 1e3, 0),
                     xytext=(4, 14), textcoords="offset points",
                     fontsize=8, color="g")

    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print(f"\nSaved plot: {out}")

    csv_path = args.csv
    if csv_path and csv_path.lower() != "none":
        if csv_path == "auto":
            csv_path = out[:-4] + ".csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["frequency_hz", "s11_real", "s11_imag",
                        "z_real_ohm", "z_imag_ohm", "z_mag_ohm"])
            for ff, rr, ii, zz in zip(f, re_, im, zs):
                w.writerow([f"{ff:.1f}", f"{rr:.6e}", f"{ii:.6e}",
                            f"{zz.real:.4f}", f"{zz.imag:.4f}", f"{abs(zz):.4f}"])
        print(f"Saved data: {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
