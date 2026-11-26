#!/usr/bin/env python3
"""
给一个目标频率, 现场把电容阵列调到最近的状态.

思路 (不搜索, 先标定):
    1. 在 [lo, hi] 里挑 3 个分散的状态做探针, 各测一次;
    2. 用 (2*pi*f)^2 = (1/L)*(1/C) - (R/L)^2 做线性最小二乘,
       解出等效 L 和 R —— 这一步"学会"了整块板;
    3. 用拟合结果预测区间内全部状态的频率, 取出最接近目标的 3 个候选;
    4. 实测这 3 个, 以实测为准选最好的, 锁定.

画图和 sweep_and_show.py 一致:
    左半  : x = 理论电容, y = 频率 (实测点 + 拟合曲线 + 目标线)
    右上  : 当前与上一次测量的 Re(Zin)
    右下  : 当前与上一次测量的 Im(Zin)

用法:
    python tune_demo.py --target-khz 38
    python tune_demo.py --target-khz 38 --lo 4 --hi 30
    python tune_demo.py --target-khz 38 --fake        # 无硬件测试
    python tune_demo.py --target-khz 38 --no-live --png tune.png
"""

from __future__ import annotations

import argparse
import math
import os
import random
import re
import statistics
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

from sweep_states import find_arduino, handshake, read_state_line
from sweep_vna_states import Scpi, capture, z_from_gamma
from sweep_resonance import zero_crossings

FIRMWARE = os.path.join("firmware", "relay_sequencer", "relay_sequencer.ino")
STEP_RE = re.compile(r"\{\s*(0x[0-9A-Fa-f]+)u?\s*,\s*(\d+)\s*,\s*(\d+)\s*\}")


def _gui_backend(name: str) -> bool:
    return name.lower().startswith(("tk", "qt", "wx", "gtk", "macosx"))


def load_c_table(path: str = FIRMWARE) -> list[float]:
    """从固件源码里读 60 个状态的期望电容 (nF)."""
    text = open(path, encoding="utf-8", errors="replace").read()
    rows = STEP_RE.findall(text)
    if len(rows) < 2:
        raise SystemExit(f"could not parse the state table from {path}")
    return [int(c) / 10.0 for _, c, _ in rows]


def fit_line(xs: list[float], ys: list[float]):
    """最小二乘拟合 y = a*x + b."""
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    den = n * sxx - sx * sx
    if abs(den) < 1e-30:
        raise ValueError("probe states are too close in 1/C to fit")
    a = (n * sxy - sx * sy) / den
    b = (sy - a * sx) / n
    return a, b


def model_f(c_nf: float, a: float, b: float) -> float:
    """(2*pi*f)^2 = a/C + b  ->  f in Hz."""
    c = c_nf * 1e-9
    w2 = a / c + b
    if w2 <= 0:
        return float("nan")
    return math.sqrt(w2) / (2 * math.pi)


class TuneDashboard:
    def __init__(self, target_hz: float, c_table: list[float], lo: int, hi: int,
                 interactive: bool):
        self.target_khz = target_hz / 1e3
        self.c_table = c_table
        self.lo, self.hi = lo, hi
        self.interactive = interactive
        self.meas: list[dict] = []      # 已测状态
        self.model = None               # (a, b, L, R, residual_pct)
        self.locked = None              # state
        self._status = None

        if interactive:
            plt.ion()
        self.fig = plt.figure(figsize=(14, 8), constrained_layout=True)
        self.fig.get_layout_engine().set(w_pad=0.06, h_pad=0.05)
        gs = self.fig.add_gridspec(2, 2, width_ratios=[1.0, 1.0],
                                   hspace=0.30, wspace=0.18)
        self.axL = self.fig.add_subplot(gs[:, 0])
        self.axTR = self.fig.add_subplot(gs[0, 1])
        self.axBR = self.fig.add_subplot(gs[1, 1])
        if interactive:
            self.fig.show()

    # ---------------------------------------------------------------- utils --
    def _set_status(self, text: str) -> None:
        if self.fig is None:
            return
        if self._status is None:
            self._status = self.fig.text(0.5, 0.004, text, ha="center",
                                         fontsize=9, color="#666666")
        else:
            self._status.set_text(text)

    def wait_until(self, t: float, label: str) -> None:
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
        if self.interactive:
            self._set_status("")

    def pump(self) -> None:
        if self.interactive:
            plt.pause(0.01)

    # ---------------------------------------------------------------- draw --
    def add(self, rec: dict) -> None:
        self.meas.append(rec)
        self.draw()

    def draw(self) -> None:
        ax = self.axL
        ax.clear()
        ax.set_xlabel("theoretical C  [nF]")
        ax.set_ylabel("resonant f  [kHz]")
        ax.grid(True, alpha=0.3)

        caps = [self.c_table[i - 1] for i in range(self.lo, self.hi + 1)]

        # 拟合出来的模型曲线 + 预测候选
        if self.model is not None:
            a, b = self.model[0], self.model[1]
            grid = np.linspace(min(caps), max(caps), 300)
            fy = [model_f(c, a, b) / 1e3 for c in grid]
            ax.plot(grid, fy, "-", lw=1.6, color="#7f7f7f", alpha=0.8,
                    label="fitted model")

        # 实测点: 探针 / 候选
        probes = [m for m in self.meas if m["kind"] == "probe"]
        cands = [m for m in self.meas if m["kind"] != "probe"]
        if probes:
            ax.scatter([m["cap"] for m in probes], [m["f0_hz"] / 1e3 for m in probes],
                       s=55, alpha=0.75, color="#1f77b4", marker="o",
                       label="probe")
        if cands:
            ax.scatter([m["cap"] for m in cands], [m["f0_hz"] / 1e3 for m in cands],
                       s=70, alpha=0.9, color="#ff7f0e", marker="s",
                       label="candidate")

        for m in self.meas:
            if m["state"] == self.locked:
                ax.annotate(f"state {m['state']}", (m["cap"], m["f0_hz"] / 1e3),
                            xytext=(8, -14), textcoords="offset points",
                            fontsize=9, color="#2ca02c", weight="bold")

        if self.locked:
            lm = next(m for m in self.meas if m["state"] == self.locked)
            ax.scatter([lm["cap"]], [lm["f0_hz"] / 1e3], s=260,
                       facecolors="none", edgecolors="#2ca02c", linewidths=2.2,
                       zorder=6, label="locked")

        ax.axhline(self.target_khz, color="#d62728", ls="--", lw=1.3,
                   label=f"target {self.target_khz:.2f} kHz")

        title = f"target {self.target_khz:.2f} kHz"
        if self.locked:
            lm = next(m for m in self.meas if m["state"] == self.locked)
            err = (lm["f0_hz"] - self.target_khz * 1e3) / 1e3
            title += f"   ->   state {self.locked} at {lm['f0_hz']/1e3:.2f} kHz" \
                     f"  (error {err:+.2f} kHz)"
        ax.set_title(title, fontsize=11)
        ax.legend(loc="upper right", fontsize=8)

        if self.model is not None:
            L, R, res = self.model[2], self.model[3], self.model[4]
            ax.text(0.02, 0.03,
                    f"L_eff = {L*1e6:.0f} uH\nR_eff = {R:.1f} ohm\n"
                    f"fit residual = {res:.1f} %\nstates {self.lo}-{self.hi}",
                    transform=ax.transAxes, ha="left", va="bottom",
                    fontsize=9, family="monospace",
                    bbox=dict(boxstyle="round", fc="white", ec="#bbbbbb",
                              alpha=0.85))

        # 右上下: 最近两次测量的 Re / Im
        recent = self.meas[-2:]
        for axis, key, color, ylabel in (
                (self.axTR, "rz", "#1f77b4", "Re(Zin)  [ohm]"),
                (self.axBR, "xz", "#d62728", "Im(Zin)  [ohm]")):
            axis.clear()
            for i, m in enumerate(recent):
                alpha = 0.30 if i == 0 and len(recent) == 2 else 1.0
                axis.plot(m["f_khz"], m[key], lw=1.6, color=color, alpha=alpha,
                          label=f"state {m['state']}")
            if key == "xz":
                axis.axhline(0, color="k", lw=0.9)
                for m in recent[-1:]:
                    for c in m["crosses"]:
                        axis.axvline(c[2] / 1e3, color="g", ls="--", lw=1.1)
            axis.set_ylabel(ylabel)
            axis.grid(True, alpha=0.3)
            axis.legend(loc="upper right", fontsize=8)
        self.axBR.set_xlabel("frequency  [kHz]")

        if self.interactive:
            plt.pause(0.02)

    def finish(self, path: str | None) -> None:
        if path:
            self.fig.savefig(path, dpi=130)
            print(f"Saved: {path}")
        if self.interactive:
            plt.ioff()
            print("Live window stays open - close it to exit.")
            plt.show(block=True)


def measure(ard, vna, state: int, kind: str, settle: float, repeats: int,
            dash: TuneDashboard, c_table: list[float], fake: bool = False) -> dict:
    """切到 state, 稳定, 扫描, 返回一条记录."""
    if fake:
        c_nf = c_table[state - 1]
        w2 = 1 / (179e-6 * c_nf * 1e-9) - (12.0 / 179e-6) ** 2
        f0 = math.sqrt(w2) / (2 * math.pi) * (1 + random.gauss(0, 0.004))
        f = np.linspace(20.0, 200.0, 400)
        rz = 25 + 90 * np.exp(-((f - f0 / 1e3) / 9.0) ** 2)
        xz = 70 * np.tanh((f0 / 1e3 - f) / 7.0)
        dash.wait_until(time.time() + 0.4, f"state {state} (fake)")
        return {"state": state, "cap": c_nf, "kind": kind, "f0_hz": f0,
                "r_ohm": 25.0, "f_khz": f, "rz": rz, "xz": xz,
                "crosses": [(0, 0, f0)]}

    ard.write(f"{state}\n".encode())
    m = read_state_line(ard, state)
    if m is None:
        raise RuntimeError(f"state {state}: no reply from the Arduino")
    c_nf = float(m.group(3))
    print(f"[{kind}] state {state}  ({c_nf:.1f} nF)", flush=True)
    dash.wait_until(time.time() + settle, f"state {state} settling")

    f = acc_re = acc_im = None
    for _ in range(repeats):
        fk, rek, imk = capture(vna)
        if f is None:
            f, acc_re, acc_im = fk, list(rek), list(imk)
        else:
            for i, v in enumerate(rek):
                acc_re[i] += v
            for i, v in enumerate(imk):
                acc_im[i] += v
        dash.pump()
    re_ = [v / repeats for v in acc_re]
    im = [v / repeats for v in acc_im]
    zs = z_from_gamma(re_, im)
    rz = [z.real for z in zs]
    xz = [z.imag for z in zs]
    crosses, _thr = zero_crossings(f, xz)
    if not crosses:
        raise RuntimeError(f"state {state}: no X=0 crossing in the sweep window")
    lo, hi, f0 = crosses[0]
    r_ohm = 0.5 * (rz[lo] + rz[hi])
    print(f"          -> X=0 at {f0/1e3:8.3f} kHz   R {r_ohm:7.1f} ohm",
          flush=True)
    return {"state": state, "cap": c_nf, "kind": kind, "f0_hz": f0,
            "r_ohm": r_ohm, "f_khz": [v / 1e3 for v in f], "rz": rz, "xz": xz,
            "crosses": crosses}


def main() -> int:
    ap = argparse.ArgumentParser(description="tune the array to a target frequency")
    ap.add_argument("--target-khz", type=float, default=38.0)
    ap.add_argument("--lo", type=int, default=4, help="lowest state to consider")
    ap.add_argument("--hi", type=int, default=30, help="highest state to consider")
    ap.add_argument("--tol-khz", type=float, default=0.6)
    ap.add_argument("--probes", type=int, default=3)
    ap.add_argument("--candidates", type=int, default=3)
    ap.add_argument("--settle", type=float, default=10.0)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--points", type=int, default=2001)
    ap.add_argument("--start-hz", type=float, default=20000.0)
    ap.add_argument("--stop-hz", type=float, default=200000.0)
    ap.add_argument("--keep-span", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5025)
    ap.add_argument("--arduino", default=None)
    ap.add_argument("--png", default=None)
    ap.add_argument("--no-live", action="store_true")
    ap.add_argument("--fake", action="store_true", help="synthetic data, no hardware")
    args = ap.parse_args()

    target_hz = args.target_khz * 1e3
    c_table = load_c_table()
    print(f"Target  : {args.target_khz:.2f} kHz")
    print(f"Range   : state {args.lo}..{args.hi}"
          f"  (C {c_table[args.hi-1]:.1f} .. {c_table[args.lo-1]:.1f} nF)")

    dash = TuneDashboard(target_hz, c_table, args.lo, args.hi,
                         interactive=not args.no_live and
                         _gui_backend(matplotlib.get_backend()))
    print(f"Backend : {matplotlib.get_backend()}  "
          f"({'live' if dash.interactive else 'headless'})\n")

    ard = None
    vna = None
    orig = None
    old_trig = "INT"
    try:
        if not args.fake:
            vna = Scpi(args.host, args.port, 20.0)
            print(f"VNA     : {vna.query('*IDN?')}")
            orig = (float(vna.query("SENS1:FREQ:STAR?")),
                    float(vna.query("SENS1:FREQ:STOP?")),
                    int(float(vna.query("SENS1:SWE:POIN?"))))
            if not args.keep_span:
                vna.write(f"SENS1:FREQ:STAR {args.start_hz:.0f}")
                vna.write(f"SENS1:FREQ:STOP {args.stop_hz:.0f}")
                time.sleep(0.3)
            if args.points and args.points != orig[2]:
                vna.write(f"SENS1:SWE:POIN {args.points}")
            a_port = find_arduino(args.arduino)
            if not a_port:
                print("Arduino not found.")
                return 1
            print(f"Arduino : {a_port}")
            ard = serial.Serial(a_port, 115200, timeout=0.2)
            if not handshake(ard):
                print("Arduino did not answer 'status'.")
                return 1
            try:
                old_trig = vna.query("TRIG:SOUR?").strip()
            except OSError:
                pass
            vna.write("TRIG:SOUR BUS")

        # ---------------- 阶段 1: 探针 ----------------
        span = args.hi - args.lo
        probes = [args.lo + round(span * k / max(1, args.probes - 1))
                  for k in range(args.probes)]
        print(f"\n--- phase 1: {len(probes)} probe states {probes} ---")
        for st in probes:
            try:
                rec = measure(ard, vna, st, "probe", args.settle, 1, dash,
                              c_table, args.fake)
            except RuntimeError as exc:
                print(f"    {exc} - skipped")
                continue
            dash.add(rec)

        usable = [m for m in dash.meas if m["kind"] == "probe"]
        if len(usable) < 2:
            print("not enough probes succeeded")
            return 1

        # ---------------- 阶段 2: 拟合 ----------------
        xs = [1.0 / (m["cap"] * 1e-9) for m in usable]
        ys = [(2 * math.pi * m["f0_hz"]) ** 2 for m in usable]
        a, b = fit_line(xs, ys)
        L = 1.0 / a
        R = L * math.sqrt(-b) if b < 0 else 0.0
        resid = statistics.median(
            abs(model_f(m["cap"], a, b) - m["f0_hz"]) / m["f0_hz"] * 100
            for m in usable)
        dash.model = (a, b, L, R, resid)
        print(f"\n--- phase 2: fit ---")
        print(f"    L_eff = {L*1e6:.1f} uH     R_eff = {R:.2f} ohm"
              f"     residual = {resid:.2f} %")

        # ---------------- 阶段 3: 预测 ----------------
        preds = []
        for st in range(args.lo, args.hi + 1):
            fp = model_f(c_table[st - 1], a, b)
            if math.isfinite(fp):
                preds.append((abs(fp - target_hz), st, fp))
        preds.sort()
        shortlist = [st for _, st, _ in preds[:args.candidates]]
        print(f"\n--- phase 3: predicted best states {shortlist} ---")
        for _, st, fp in preds[:args.candidates]:
            print(f"    state {st:2d}  predicted {fp/1e3:8.3f} kHz  "
                  f"(C {c_table[st-1]:.1f} nF)")
        dash.draw()

        # ---------------- 阶段 4: 实测候选 ----------------
        print(f"\n--- phase 4: measure the candidates ---")
        tested = {m["state"] for m in dash.meas}
        for st in shortlist:
            if st in tested:
                continue
            try:
                rec = measure(ard, vna, st, "candidate", args.settle,
                              args.repeats, dash, c_table, args.fake)
            except RuntimeError as exc:
                print(f"    {exc} - skipped")
                continue
            dash.add(rec)

        if not dash.meas:
            print("no measurement succeeded")
            return 1

        best = min(dash.meas, key=lambda m: abs(m["f0_hz"] - target_hz))
        dash.locked = best["state"]
        dash.draw()

        err = (best["f0_hz"] - target_hz) / 1e3
        print(f"\n=== LOCKED ===")
        print(f"    state     : {best['state']}  (C {best['cap']:.1f} nF)")
        print(f"    achieved  : {best['f0_hz']/1e3:.3f} kHz")
        print(f"    target    : {args.target_khz:.3f} kHz")
        print(f"    error     : {err:+.3f} kHz  ({err/args.target_khz*100:+.2f} %)")
        print(f"    tolerance : {args.tol_khz:.2f} kHz  -> "
              f"{'PASS' if abs(err) <= args.tol_khz else 'closest achievable'}")
        print(f"    measured  : {len(dash.meas)} states "
              f"(full sweep would be {args.hi - args.lo + 1})")

    except KeyboardInterrupt:
        print("\nstopped by Ctrl+C")
    finally:
        if vna is not None and orig is not None:
            try:
                vna.write(f"TRIG:SOUR {old_trig}")
                if not args.keep_span:
                    vna.write(f"SENS1:FREQ:STAR {orig[0]:.0f}")
                    vna.write(f"SENS1:FREQ:STOP {orig[1]:.0f}")
                if args.points and args.points != orig[2]:
                    vna.write(f"SENS1:SWE:POIN {orig[2]}")
            except OSError:
                pass
        if ard is not None:
            ard.close()      # 不关继电器: 让调好的状态留在板上

    png = args.png or f"tune_{datetime.now():%Y%m%d_%H%M%S}.png"
    dash.finish(png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
