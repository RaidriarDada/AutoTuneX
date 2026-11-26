#!/usr/bin/env python3
"""
把每个状态都扫一遍, 同时用三个面板实时显示.

布局:
    左半 (整高) : x = 理论电容, y = 测出来的谐振频率
                  每到一个新状态加一个点, 旧点全部用同一个透明度保留
    右上        : 当前状态 + 上一个状态的 Re(Zin)
    右下        : 当前状态 + 上一个状态的 Im(Zin)
                  上一个状态的曲线用较低透明度作对比

用法:
    python sweep_and_show.py
    python sweep_and_show.py --start 1 --end 30
    python sweep_and_show.py --no-live --png dash.png
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime

import matplotlib

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
import numpy as np

try:
    import serial
except ImportError:  # pragma: no cover
    sys.exit("缺少 pyserial: pip install pyserial")

from sweep_states import find_arduino, handshake, read_state_line, sleep_until
from sweep_vna_states import Scpi, capture, z_from_gamma
from sweep_resonance import zero_crossings

L_MODEL = 220e-6      # 名义电感, 只用来画参考曲线
R_MODEL = 1.5         # 名义串联电阻


def _gui_backend(name: str) -> bool:
    """TkAgg/QtAgg 里也含有 'agg' 子串, 不能用 'agg' in name 判断."""
    return name.lower().startswith(("tk", "qt", "wx", "gtk", "macosx"))


class Dashboard:
    def __init__(self, total: int, interactive: bool):
        self.total = total
        self.interactive = interactive
        self.caps: list[float] = []
        self.f0s: list[float] = []
        self.state_ids: list[int] = []
        self.prev = None            # (state, f_kHz, rz, xz)
        self.fig = None
        self._status = None

        if interactive:
            plt.ion()
        self.fig = plt.figure(figsize=(14, 8), constrained_layout=True)
        gs = self.fig.add_gridspec(2, 2, width_ratios=[1.0, 1.0],
                                   hspace=0.30, wspace=0.18)
        self.axL = self.fig.add_subplot(gs[:, 0])
        self.axTR = self.fig.add_subplot(gs[0, 1])
        self.axBR = self.fig.add_subplot(gs[1, 1])
        if interactive:
            self.fig.show()

    def _set_status(self, text: str) -> None:
        if self.fig is None:
            return
        if self._status is None:
            self._status = self.fig.text(0.5, 0.004, text, ha="center",
                                         fontsize=9, color="#666666")
        else:
            self._status.set_text(text)

    def wait_until(self, t: float, label: str) -> None:
        """等待到时刻 t, 期间泵 GUI 事件循环, 否则窗口会被系统判成无响应."""
        while True:
            left = t - time.time()
            if left <= 0:
                break
            msg = f"{label}  {left:4.1f} s"
            print(f"\r     {msg}      ", end="", flush=True)
            if self.interactive:
                self._set_status(msg)
                plt.pause(0.05)
            else:
                time.sleep(min(left, 0.2))
        print("\r" + " " * 70 + "\r", end="", flush=True)

    def pump(self) -> None:
        if self.interactive:
            plt.pause(0.01)

    def update(self, state: int, cap_nf: float, f_khz, rz, xz,
               f0_hz, crosses, thr, elapsed: float, eta_min: float) -> None:
        if f0_hz:
            self.caps.append(cap_nf)
            self.f0s.append(f0_hz / 1e3)
            self.state_ids.append(state)

        current = (state, f_khz, rz, xz)

        # ---------------- 左: 电容 vs 频率 ----------------
        ax = self.axL
        ax.clear()
        ax.set_xlabel("theoretical capacitance  [nF]")
        ax.set_ylabel("measured resonant frequency  [kHz]")
        ax.set_title("state sweep: C_eq vs f0", fontsize=11)
        ax.grid(True, alpha=0.3)

        if self.caps:
            if len(self.caps) > 1:
                ax.scatter(self.caps[:-1], self.f0s[:-1], s=34, alpha=0.35,
                           color="#1f77b4", label="previous states")
            ax.scatter([self.caps[-1]], [self.f0s[-1]], s=90, alpha=1.0,
                       color="#d62728", zorder=5,
                       label=f"state {self.state_ids[-1]}")

            # 名义模型参考线
            c_lo, c_hi = min(self.caps), max(self.caps)
            pad = max(1.0, 0.05 * (c_hi - c_lo))
            grid = np.linspace(c_lo - pad, c_hi + pad, 200)
            f_model = 1.0 / (2 * np.pi * np.sqrt(L_MODEL * grid * 1e-9)) / 1e3
            ax.plot(grid, f_model, "--", lw=1.0, color="#999999", alpha=0.7,
                    label=f"model L={L_MODEL*1e6:.0f} uH, R={R_MODEL} ohm")
            ax.set_xlim(c_lo - pad, c_hi + pad)
            ax.legend(loc="upper right", fontsize=8)

        ax.set_title(f"state {state}/{self.total}   |   C_eq {cap_nf:.1f} nF"
                     f"   |   elapsed {elapsed/60:.1f} min,  ~{eta_min:.1f} min left",
                     fontsize=10)

        # ---------------- 右上: Re(Z) ----------------
        ax = self.axTR
        ax.clear()
        if self.prev is not None:
            _, pf, prz, _ = self.prev
            ax.plot(pf, prz, lw=1.4, color="#1f77b4", alpha=0.30,
                    label=f"state {self.prev[0]}")
        ax.plot(f_khz, rz, lw=1.6, color="#1f77b4", alpha=1.0,
                label=f"state {state}")
        ax.set_ylabel("Re(Zin)  [ohm]")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)

        # ---------------- 右下: Im(Z) ----------------
        ax = self.axBR
        ax.clear()
        if self.prev is not None:
            _, pf, _, pxz = self.prev
            ax.plot(pf, pxz, lw=1.4, color="#d62728", alpha=0.30,
                    label=f"state {self.prev[0]}")
        ax.plot(f_khz, xz, lw=1.6, color="#d62728", alpha=1.0,
                label=f"state {state}")
        ax.axhline(0, color="k", lw=0.9)
        ax.axhspan(-thr, thr, color="grey", alpha=0.15)
        for lo, hi, fm in crosses:
            ax.axvline(fm / 1e3, color="g", ls="--", lw=1.1)
            ax.annotate(f"{fm/1e3:.2f} kHz", xy=(fm / 1e3, 0),
                        xytext=(4, 12), textcoords="offset points",
                        fontsize=8, color="g")
        ax.set_xlabel("frequency  [kHz]")
        ax.set_ylabel("Im(Zin)  [ohm]")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)

        if self.interactive:
            plt.pause(0.02)
        self.prev = current

    def finish(self, path: str | None) -> None:
        if self.fig is None:
            return
        if path:
            self.fig.savefig(path, dpi=130)
            print(f"Saved dashboard: {path}")
        if self.interactive:
            plt.ioff()
            print("Live window stays open - close it to exit.")
            plt.show(block=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="sweep all states with a live 3-panel view")
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
    ap.add_argument("-o", "--out", default=None, help="summary CSV")
    ap.add_argument("--png", default=None, help="final dashboard image")
    ap.add_argument("--no-live", action="store_true")
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

    try:
        orig_start = float(vna.query("SENS1:FREQ:STAR?"))
        orig_stop = float(vna.query("SENS1:FREQ:STOP?"))
        orig_points = int(float(vna.query("SENS1:SWE:POIN?")))
    except (OSError, ValueError, TimeoutError) as exc:
        print(f"VNA stopped responding during setup: {exc}")
        print("Is the VNA application still running? Its Socket Server may have "
              "crashed or a modal dialog may be blocking it.")
        return 1
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
    print(f"Sweep   : {f_lo/1e3:.2f} .. {f_hi/1e3:.2f} kHz, {npts} pts, "
          f"{step:.1f} Hz/step")
    print(f"Plan    : {args.start}..{args.end}, {args.repeats} sweep(s) each, "
          f"{args.settle:.0f} s settle\n")

    out = args.out or f"sweepshow_{datetime.now():%Y%m%d_%H%M%S}.csv"

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

    dash = Dashboard(args.end - args.start + 1,
                     interactive=not args.no_live and
                     _gui_backend(matplotlib.get_backend()))
    print(f"Backend : {matplotlib.get_backend()}  "
          f"({'live' if dash.interactive else 'headless'})\n")
    if dash.interactive:
        print("A live window should be open now. If you cannot see it, look "
              "behind this terminal window or on the taskbar.\n")
    else:
        print("Running headless: no window will appear, only the final PNG.\n")

    total = args.end - args.start + 1
    t_start = time.time()
    rows = []

    try:
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["state", "theoretical_C_nF", "f0_Hz", "R_ohm",
                        "n_crossings", "hyst_ohm", "word", "iso_time"])

            for n in range(args.start, args.end + 1):
                ard.write(f"{n}\n".encode())
                m = read_state_line(ard, n)
                if m is None:
                    print(f"state {n}: no reply, skipped")
                    continue
                exp_nf, word = m.group(3), m.group(5)
                print(f"[{n:2d}] {exp_nf:>7} nF", flush=True)
                dash.wait_until(time.time() + args.settle,
                                f"state {n} settling")

                f = acc_re = acc_im = None
                vna_dead = False
                for k in range(args.repeats):
                    try:
                        fk, rek, imk = capture(vna)
                    except (OSError, TimeoutError, RuntimeError) as exc:
                        print(f"\nVNA stopped responding at state {n}: {exc}")
                        vna_dead = True
                        break
                    if f is None:
                        f, acc_re, acc_im = fk, list(rek), list(imk)
                    else:
                        for i, v in enumerate(rek):
                            acc_re[i] += v
                        for i, v in enumerate(imk):
                            acc_im[i] += v
                    dash.pump()
                if vna_dead:
                    break
                re_ = [v / args.repeats for v in acc_re]
                im = [v / args.repeats for v in acc_im]

                zs = z_from_gamma(re_, im)
                rz = [z.real for z in zs]
                xz = [z.imag for z in zs]
                fk_khz = [v / 1e3 for v in f]

                crosses, thr = zero_crossings(f, xz, args.hysteresis, args.merge_hz)
                if crosses:
                    lo, hi, f0 = crosses[0]
                    r_ohm = 0.5 * (rz[lo] + rz[hi])
                    print(f"     X=0 {f0/1e3:9.3f} kHz   R {r_ohm:7.1f} ohm   "
                          f"({len(crosses)} candidate(s))", flush=True)
                else:
                    f0, r_ohm = None, None
                    print("     no X=0 in window", flush=True)

                rows.append([n, exp_nf, f"{f0:.1f}" if f0 else "",
                             f"{r_ohm:.2f}" if r_ohm else "", len(crosses),
                             f"{thr:.3f}", word,
                             datetime.now().isoformat(timespec="seconds")])
                w.writerow(rows[-1])
                fh.flush()

                elapsed = time.time() - t_start
                eta = elapsed / len(rows) * (total - len(rows)) / 60
                dash.update(n, float(exp_nf), fk_khz, rz, xz, f0, crosses, thr,
                            elapsed, eta)

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
          f"{found} with an X=0 crossing -> {out}")
    png = args.png or (out[:-4] + "_dash.png" if out.endswith(".csv") else None)
    dash.finish(png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
