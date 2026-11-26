#!/usr/bin/env python3
"""
批量画多个状态的 Re(Zin) / Im(Zin), 每个状态一张图 + 一张总览.

用法:
    python plot_states.py --start 1 --end 20
    python plot_states.py --start 1 --end 20 --points 4001 --outdir figures/state_plots

输出:
    <outdir>/state_01.png ...     每个状态一张 (Re 在上, Im 在下, 所有候选过零点都标出来)
    <outdir>/overview_im.png      所有状态的 Im(Z) 总览, 方便一眼看出谁乱
    <outdir>/summary.csv          每个状态的极值、过零点数量、候选频率
"""

from __future__ import annotations

import argparse
import csv
import os
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
    ap = argparse.ArgumentParser(description="plot Re/Im Zin for a range of states")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=20)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5025)
    ap.add_argument("--arduino", default=None)
    ap.add_argument("--points", type=int, default=4001)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--settle", type=float, default=20.0,
                    help="seconds to wait after the relay change before sweeping")
    ap.add_argument("--start-hz", type=float, default=20000.0,
                    help="sweep start frequency (default 20 kHz)")
    ap.add_argument("--stop-hz", type=float, default=200000.0,
                    help="sweep stop frequency (default 200 kHz)")
    ap.add_argument("--keep-span", action="store_true",
                    help="use whatever span the VNA already has")
    ap.add_argument("--outdir", default="figures/state_plots")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    vna = Scpi(args.host, args.port, 20.0)
    print(f"VNA     : {vna.query('*IDN?')}")

    a_port = find_arduino(args.arduino)
    if not a_port:
        print("Arduino not found.")
        return 1
    print(f"Arduino : {a_port}")

    orig_start = float(vna.query("SENS1:FREQ:STAR?"))
    orig_stop = float(vna.query("SENS1:FREQ:STOP?"))
    if not args.keep_span:
        vna.write(f"SENS1:FREQ:STAR {args.start_hz:.0f}")
        vna.write(f"SENS1:FREQ:STOP {args.stop_hz:.0f}")
        time.sleep(0.3)

    f_lo = float(vna.query("SENS1:FREQ:STAR?"))
    f_hi = float(vna.query("SENS1:FREQ:STOP?"))
    orig_points = int(float(vna.query("SENS1:SWE:POIN?")))
    if args.points and args.points != orig_points:
        vna.write(f"SENS1:SWE:POIN {args.points}")
    npts = int(float(vna.query("SENS1:SWE:POIN?")))
    step = (f_hi - f_lo) / max(1, npts - 1)
    print(f"Sweep   : {f_lo/1e3:.3f} .. {f_hi/1e3:.3f} kHz, {npts} pts, {step:.2f} Hz/step")
    print(f"Output  : {args.outdir}/\n")

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

    summary = []
    overview = []
    t_start = time.time()

    try:
        for n in range(args.start, args.end + 1):
            ard.write(f"{n}\n".encode())
            m = read_state_line(ard, n)
            if m is None:
                print(f"state {n}: no reply, skipped")
                continue
            exp_nf, word = m.group(3), m.group(5)
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

            zs = z_from_gamma(re_, im)
            rz = [z.real for z in zs]
            xz = [z.imag for z in zs]
            fk_khz = [v / 1e3 for v in f]

            crosses, thr = zero_crossings(f, xz)
            sigma = noise_sigma(xz)
            i_rmax = max(range(len(rz)), key=lambda k: rz[k])

            # ---- 单状态图: 上 Re, 下 Im, 所有候选过零点都画出来 ----
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True)
            ax1.plot(fk_khz, rz, lw=0.9, color="#1f77b4")
            ax1.axvline(fk_khz[i_rmax], color="#1f77b4", ls=":", lw=1.1)
            ax1.plot([fk_khz[i_rmax]], [rz[i_rmax]], "o", ms=4, color="#1f77b4")
            ax1.annotate(f"Re max {rz[i_rmax]:.1f} @ {fk_khz[i_rmax]:.2f} kHz",
                         xy=(fk_khz[i_rmax], rz[i_rmax]), xytext=(6, -14),
                         textcoords="offset points", fontsize=8, color="#1f77b4")
            ax1.set_ylabel("Re(Zin)  [ohm]")
            ax1.grid(True, alpha=0.3)

            ax2.plot(fk_khz, xz, lw=0.9, color="#d62728")
            ax2.axhline(0, color="k", lw=0.8)
            ax2.axhspan(-thr, thr, color="grey", alpha=0.15)
            for lo, hi, fm in crosses:
                ax2.axvline(fm / 1e3, color="g", ls="--", lw=0.7, alpha=0.75)
            ax2.set_ylabel("Im(Zin)  [ohm]")
            ax2.set_xlabel("frequency  [kHz]")
            ax2.grid(True, alpha=0.3)

            fig.suptitle(f"State {n}  -  expected {exp_nf} nF  -  "
                         f"{len(crosses)} candidate X=0  -  noise sigma {sigma:.2f} ohm",
                         fontsize=11)
            fig.tight_layout()
            path = os.path.join(args.outdir, f"state_{n:02d}.png")
            fig.savefig(path, dpi=130)
            plt.close(fig)

            clist = ";".join(f"{c[2]:.1f}" for c in crosses)
            summary.append([n, exp_nf, word, f"{min(rz):.2f}", f"{max(rz):.2f}",
                            f"{fk_khz[i_rmax]:.3f}", len(crosses), clist,
                            f"{sigma:.4f}"])
            overview.append((n, fk_khz, xz, crosses, thr))

            print(f"[{n:2d}] {exp_nf:>7} nF   Re {min(rz):6.1f}..{max(rz):6.1f}"
                  f"   Re_max @ {fk_khz[i_rmax]:6.2f} kHz   "
                  f"X=0 candidates: {len(crosses)}", flush=True)

            done = n - args.start + 1
            left = (time.time() - t_start) / done * (args.end - n)
            print(f"     [{done} done, ~{left/60:.1f} min left]", flush=True)

    except KeyboardInterrupt:
        print("\nstopped by Ctrl+C")
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

    with open(os.path.join(args.outdir, "summary.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["state", "expected_nF", "word", "Re_min_ohm", "Re_max_ohm",
                    "f_at_Re_max_kHz", "n_X0_candidates", "X0_candidates_Hz",
                    "noise_sigma_ohm"])
        w.writerows(summary)

    # ---- 总览: 所有状态的 Im(Z) ----
    if overview:
        cols = 4
        rows = (len(overview) + cols - 1) // cols
        fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 2.4 * rows),
                                 sharex=True)
        axes = axes.ravel()
        for ax, (n, fk, xz, crosses, thr) in zip(axes, overview):
            ax.plot(fk, xz, lw=0.7, color="#d62728")
            ax.axhline(0, color="k", lw=0.7)
            ax.axhspan(-thr, thr, color="grey", alpha=0.18)
            for lo, hi, fm in crosses:
                ax.axvline(fm / 1e3, color="g", ls="--", lw=0.5, alpha=0.7)
            ax.set_title(f"state {n}  ({len(crosses)} X=0)", fontsize=9)
            ax.tick_params(labelsize=7)
            ax.grid(True, alpha=0.25)
        for ax in axes[len(overview):]:
            ax.axis("off")
        for ax in axes[(rows - 1) * cols:]:
            ax.set_xlabel("kHz", fontsize=8)
        fig.suptitle("Im(Zin) for every state - green dashes are X=0 candidates",
                     fontsize=12)
        fig.tight_layout()
        fig.savefig(os.path.join(args.outdir, "overview_im.png"), dpi=120)
        plt.close(fig)

    print(f"\nSaved {len(summary)} figures + overview_im.png + summary.csv "
          f"to {args.outdir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
