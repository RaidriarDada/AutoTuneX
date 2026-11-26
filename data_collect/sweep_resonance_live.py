#!/usr/bin/env python3
"""
演示版: 扫 60 个状态的同时实时画图.

和 sweep_resonance.py 的测量逻辑、CSV 格式完全一致, 只是多了两个窗口:
  上面: f0 随状态号变化 (边跑边长出来), 灰线是固件给的期望电容
  下面: 当前状态的 Im(Z) 曲线, 绿色虚线是判定出的过零点

参数默认值就是演示用的那组:
    --start 1 --end 60 --points 2001 --repeats 2 --settle 10

用法:
    python sweep_resonance_live.py
    python sweep_resonance_live.py --no-live        # 无窗口, 每个状态存一张 PNG
    python sweep_resonance_live.py --start 1 --end 10
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from datetime import datetime

import matplotlib

# 找一个能开窗口的后端; 找不到就退回 Agg (存 PNG)
_backend = None
for _cand in ("TkAgg", "QtAgg", "Qt5Agg"):
    try:
        matplotlib.use(_cand)
        _backend = _cand
        break
    except Exception:
        continue
if _backend is None:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    import serial
except ImportError:  # pragma: no cover
    sys.exit("缺少 pyserial: pip install pyserial")

from sweep_states import find_arduino, handshake, read_state_line, sleep_until
from sweep_vna_states import Scpi, capture, z_from_gamma
from sweep_resonance import zero_crossings


class LivePlot:
    """边测边画的图. 无交互后端时退化成每状态存一张 PNG."""

    def __init__(self, total: int, enabled: bool, frames_dir: str | None = None):
        self.total = total
        _be = matplotlib.get_backend().lower()
        # TkAgg/QtAgg 里也含 'agg' 子串, 只能按前缀认
        self.interactive = enabled and _be.startswith(
            ("tk", "qt", "wx", "gtk", "macosx"))
        self.build = self.interactive or frames_dir is not None
        self.frames_dir = frames_dir
        self.states: list[int] = []
        self.f0s: list[float] = []
        self.rs: list[float] = []
        self.caps: list[float] = []
        self.fig = None
        self.ax1 = None
        self.ax2 = None
        self.ax1b = None
        if self.frames_dir:
            os.makedirs(self.frames_dir, exist_ok=True)
        if self.interactive:
            plt.ion()
        if self.build:
            self.fig = plt.figure(figsize=(12, 7.5))
            gs = self.fig.add_gridspec(2, 1, height_ratios=[1.15, 1.0])
            self.ax1 = self.fig.add_subplot(gs[0])
            self.ax2 = self.fig.add_subplot(gs[1])
            # twinx 只能建一次 —— 放进 update() 会每次叠一层刻度
            self.ax1b = self.ax1.twinx()
            if self.interactive:
                self.fig.show()

    def update(self, state: int, expected_nf: float, f_khz, xz, crosses, thr,
               f0_hz, r_ohm, elapsed: float, eta_min: float) -> None:
        self.states.append(state)
        self.caps.append(float(expected_nf))
        self.f0s.append(f0_hz / 1e3 if f0_hz else float("nan"))
        self.rs.append(r_ohm if r_ohm else float("nan"))

        if not self.build:
            return

        ax1, ax2, ax1b = self.ax1, self.ax2, self.ax1b
        ax1.clear()
        ax1b.clear()
        ax2.clear()
        ax1.plot(self.states, self.f0s, "o-", ms=4, lw=1.2, color="#1f77b4",
                 label="f0 (X=0)  [kHz]")
        ax1.set_xlabel("state")
        ax1.set_ylabel("f0  [kHz]", color="#1f77b4")
        ax1.tick_params(axis="y", labelcolor="#1f77b4")
        ax1.grid(True, alpha=0.3)
        ax1.set_xlim(0, self.total + 1)

        ax1b.plot(self.states, self.caps, "--", lw=1.0, color="#999999",
                  label="expected C_eq  [nF]")
        ax1b.yaxis.tick_right()                 # clear() 会把 twin 轴推回左边
        ax1b.yaxis.set_label_position("right")
        ax1b.set_ylabel("expected C_eq  [nF]", color="#777777")
        ax1b.tick_params(axis="y", labelcolor="#777777")

        last = len(self.states) - 1
        ax1.set_title(f"state {state}/{self.total}   |   f0 = "
                      f"{self.f0s[last]:.3f} kHz   R = {self.rs[last]:.1f} ohm"
                      f"   |   elapsed {elapsed/60:.1f} min,  ~{eta_min:.1f} min left",
                      fontsize=11)

        ax2.clear()
        ax2.plot(f_khz, xz, lw=0.9, color="#d62728")
        ax2.axhline(0, color="k", lw=0.8)
        ax2.axhspan(-thr, thr, color="grey", alpha=0.15)
        for lo, hi, fm in crosses:
            ax2.axvline(fm / 1e3, color="g", ls="--", lw=1.0)
            ax2.annotate(f"{fm/1e3:.2f} kHz", xy=(fm / 1e3, 0),
                         xytext=(4, 12), textcoords="offset points",
                         fontsize=8, color="g")
        ax2.set_xlabel("frequency  [kHz]")
        ax2.set_ylabel("Im(Zin)  [ohm]")
        ax2.grid(True, alpha=0.3)

        self.fig.tight_layout()
        if self.interactive:
            plt.pause(0.02)

        if self.frames_dir:
            self.fig.savefig(os.path.join(self.frames_dir,
                                          f"frame_{state:02d}.png"), dpi=100)

    def finish(self, path: str | None) -> None:
        if not self.interactive or self.fig is None:
            return
        plt.ioff()
        if path:
            self.fig.savefig(path, dpi=130)
            print(f"Saved live plot: {path}")
        plt.show(block=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="live demo: sweep and plot f0")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5025)
    ap.add_argument("--arduino", default=None)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=60)
    ap.add_argument("--settle", type=float, default=10.0)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--points", type=int, default=2001)
    ap.add_argument("--start-hz", type=float, default=20000.0)
    ap.add_argument("--stop-hz", type=float, default=200000.0)
    ap.add_argument("--keep-span", action="store_true")
    ap.add_argument("--hysteresis", type=float, default=None)
    ap.add_argument("--merge-hz", type=float, default=None)
    ap.add_argument("-o", "--out", default="res_20261124_actual.csv")
    ap.add_argument("--png", default=None, help="final figure path")
    ap.add_argument("--frames", default=None, help="save one PNG per state here")
    ap.add_argument("--no-live", action="store_true", help="headless")
    args = ap.parse_args()

    vna = Scpi(args.host, args.port, 20.0)
    try:
        print(f"VNA     : {vna.query('*IDN?')}")
    except OSError as exc:
        print(f"cannot reach the VNA: {exc}")
        return 1

    a_port = find_arduino(args.arduino)
    if not a_port:
        print("Arduino not found.")
        return 1
    print(f"Arduino : {a_port}")

    orig_start = float(vna.query("SENS1:FREQ:STAR?"))
    orig_stop = float(vna.query("SENS1:FREQ:STOP?"))
    orig_points = int(float(vna.query("SENS1:SWE:POIN?")))
    if args.keep_span:
        f_lo, f_hi = orig_start, orig_stop
    else:
        vna.write(f"SENS1:FREQ:STAR {args.start_hz:.0f}")
        vna.write(f"SENS1:FREQ:STOP {args.stop_hz:.0f}")
        time.sleep(0.3)
        f_lo = float(vna.query("SENS1:FREQ:STAR?"))
        f_hi = float(vna.query("SENS1:FREQ:STOP?"))

    if args.points and args.points != orig_points:
        vna.write(f"SENS1:SWE:POIN {args.points}")
    npts = int(float(vna.query("SENS1:SWE:POIN?")))
    step = (f_hi - f_lo) / max(1, npts - 1)
    print(f"Sweep   : {f_lo/1e3:.3f} .. {f_hi/1e3:.3f} kHz, {npts} pts, "
          f"{step:.1f} Hz/step")
    print(f"Plan    : {args.start}..{args.end}, {args.repeats} sweep(s) each, "
          f"{args.settle:.0f} s settle")
    print(f"Output  : {args.out}")
    print(f"Backend : {matplotlib.get_backend()}\n")

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

    live = LivePlot(args.end - args.start + 1, not args.no_live, args.frames)
    total = args.end - args.start + 1
    t_start = time.time()
    rows = []

    try:
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
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
                exp_nf, word = m.group(3), m.group(5)
                print(f"[{n:2d}] {exp_nf:>7} nF   waiting {args.settle:.0f} s ...",
                      flush=True)
                t_echo = time.time()
                sleep_until(t_echo + args.settle)

                f = acc_re = acc_im = None
                per_sweep = []
                for _ in range(args.repeats):
                    fk, rek, imk = capture(vna)
                    if f is None:
                        f, acc_re, acc_im = fk, list(rek), list(imk)
                    else:
                        for i, v in enumerate(rek):
                            acc_re[i] += v
                        for i, v in enumerate(imk):
                            acc_im[i] += v
                    ck, _ = zero_crossings(fk, [z.imag for z in z_from_gamma(rek, imk)],
                                           args.hysteresis, args.merge_hz)
                    if ck:
                        per_sweep.append(ck[0][2])

                re_ = [v / args.repeats for v in acc_re]
                im = [v / args.repeats for v in acc_im]
                zs = z_from_gamma(re_, im)
                xz = [z.imag for z in zs]

                crosses, thr = zero_crossings(f, xz, args.hysteresis, args.merge_hz)
                std_s = (f"{statistics.pstdev(per_sweep):.1f}"
                         if len(per_sweep) > 1 else "")

                if crosses:
                    lo, hi, f0 = crosses[0]
                    r_ohm = 0.5 * (zs[lo].real + zs[hi].real)
                    z_ohm = 0.5 * (abs(zs[lo]) + abs(zs[hi]))
                    all_c = ";".join(f"{c[2]:.1f}" for c in crosses)
                    print(f"     X=0 {f0/1e3:9.3f} kHz   R {r_ohm:7.1f} ohm   "
                          f"({len(crosses)} candidate(s))", flush=True)
                    rows.append([n, exp_nf, f"{f0:.1f}", f"{r_ohm:.2f}",
                                 f"{z_ohm:.2f}", len(crosses), all_c, std_s,
                                 f"{thr:.3f}", args.repeats, word,
                                 datetime.now().isoformat(timespec="seconds")])
                else:
                    f0 = None
                    r_ohm = None
                    print("     no X=0 in window", flush=True)
                    rows.append([n, exp_nf, "", "", "", 0, "", std_s, "",
                                 args.repeats, word,
                                 datetime.now().isoformat(timespec="seconds")])

                w.writerow(rows[-1])
                fh.flush()

                elapsed = time.time() - t_start
                eta = elapsed / len(rows) * (total - len(rows)) / 60
                live.update(n, exp_nf, [v / 1e3 for v in f], xz, crosses, thr,
                            f0, r_ohm, elapsed, eta)

    except KeyboardInterrupt:
        print("\nstopped by Ctrl+C")
    finally:
        try:
            vna.write(f"TRIG:SOUR {old_trig}")
            if not args.keep_span:
                vna.write(f"SENS1:FREQ:STAR {orig_start:.0f}")
                vna.write(f"SENS1:FREQ:STOP {orig_stop:.0f}")
            if npts != orig_points:
                vna.write(f"SENS1:SWE:POIN {orig_points}")
        except OSError:
            pass
        ard.write(b"0\n")
        ard.close()

    found = sum(1 for r in rows if r[2])
    print(f"\n{len(rows)} states in {(time.time()-t_start)/60:.1f} min, "
          f"{found} with an X=0 crossing -> {args.out}")
    png = args.png or (args.out[:-4] + "_live.png" if args.out.endswith(".csv") else None)
    live.finish(png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
