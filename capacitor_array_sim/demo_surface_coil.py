"""What the 3 x 3 array does on the real surface coil at low frequency.

The Winter target is 31P at 3 T (51.705 MHz) on a single-turn surface loop.  The
Fall-term demo only has to show that the array produces different capacitances
and can be tuned, at a much lower frequency, using ordinary nanofarad parts
from the 0.1 nF-100 nF through-hole kit.

This script answers that question for the *actual* coil instead of a stand-in
inductor.

Coil model
----------
The lecture slides describe the loop as six series breaks ``CS1..CS6`` plus a
parallel capacitor ``Cp`` across the coax feed (parallel-series circuit, two
resonances).  The Winter coil is tuned with 200 pF at every break, so the
series capacitance is ``200/6 = 33.33 pF``.  Resonating that at 51.705 MHz
gives

    L = 1 / ((2 pi f)^2 C) = 284 nH

which is exactly what a 14 cm single-turn loop of 6 mm copper should measure,
so the number is trusted rather than assumed.

Two resonances
--------------
With the array as the series capacitance ``Cs`` and a fixed ``Cp`` at the port:

    f_series   = 1 / (2 pi sqrt(L Cs))
    f_parallel = 1 / (2 pi sqrt(L (Cs || Cp)))

The VNA sees the anti-resonance ``f_parallel``.  If ``Cp`` stays at 200 pF it
is far smaller than a nanofarad array, so ``Cs || Cp ~ Cp`` and the
anti-resonance does not move at all: ``Cp`` has to be raised with ``Cs`` for
the array to be visible.  That is the reason to scale the fixed capacitors.

Run ``python capacitor_array_sim/demo_surface_coil.py``.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from demo_3x3_lowfreq import KIT_LF_PF, KitCombos
from demo_3x3_model import DemoModel

F_WINTER_HZ = 51.705e6
C_SERIES_WINTER_PF = 200.0
BREAKS = 6
BAND_KHZ = (15.0, 30.0)
KIT_MAX_PF = max(KIT_LF_PF)


# --------------------------------------------------------------------------
# Coil and resonance
# --------------------------------------------------------------------------

def coil_inductance(f_hz=F_WINTER_HZ, series_pf=C_SERIES_WINTER_PF,
                    breaks=BREAKS):
    """Loop inductance implied by the Winter tuning, in henry."""
    capacitance = series_pf * 1e-12 / breaks
    return 1.0 / ((2.0 * np.pi * f_hz) ** 2 * capacitance)


def series_resonance(c_pf, inductance_h):
    return 1.0 / (2.0 * np.pi * np.sqrt(inductance_h * np.asarray(c_pf) * 1e-12))


def parallel_capacitance(cs_pf, cp_pf):
    """Series combination of the tuning and the matching capacitor."""
    return 1.0 / (1.0 / np.asarray(cs_pf, dtype=float) + 1.0 / float(cp_pf))


def parallel_resonance(cs_pf, cp_pf, inductance_h):
    return series_resonance(parallel_capacitance(cs_pf, cp_pf), inductance_h)


def turns_for(inductance_h, reference_h=None):
    """Turns of the same geometry needed, since L scales as N squared."""
    reference = coil_inductance() if reference_h is None else reference_h
    return float(np.sqrt(inductance_h / reference))


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def sweep(model, branch_pf, parallel_parts):
    """Equivalent capacitance and both resonances for all 60 states."""
    value = branch_pf * parallel_parts
    capacitance = model.capacitances(np.full(model.edge_count, value), 0.0)
    return capacitance


def main() -> int:
    base = Path(__file__).with_name("demo_output")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch-nf", type=float, default=KIT_MAX_PF / 1000,
                        help="capacitor on every array branch, nF (default: kit max)")
    parser.add_argument("--fixed-nf", type=float, default=KIT_MAX_PF / 1000,
                        help="Cp and the other fixed capacitors, nF")
    parser.add_argument("--band-low", type=float, default=BAND_KHZ[0])
    parser.add_argument("--band-high", type=float, default=BAND_KHZ[1])
    parser.add_argument("--coil-nh", type=float, default=None,
                        help="override the derived loop inductance")
    parser.add_argument("--coil-ohm", type=float, default=0.05,
                        help="loop resistance at the demo frequency")
    parser.add_argument("--relay-ohm", type=float, default=0.05,
                        help="contact resistance of one closed relay")
    parser.add_argument("--relays-in-path", type=int, default=5)
    parser.add_argument("--output", type=Path, default=base)
    args = parser.parse_args()

    inductance = (args.coil_nh * 1e-9 if args.coil_nh is not None
                  else coil_inductance())
    cp_pf = args.fixed_nf * 1000.0
    model = DemoModel()

    check = 1.0 / (2.0 * np.pi * np.sqrt(
        inductance * C_SERIES_WINTER_PF * 1e-12 / BREAKS))
    print(f"loop inductance from the Winter tuning: {inductance * 1e9:.1f} nH")
    print(f"  check: 6 x {C_SERIES_WINTER_PF:g} pF across it -> {check / 1e6:.3f} MHz")

    rows = []
    for parts in (1, 2):
        capacitance = sweep(model, args.branch_nf * 1000, parts)
        levels = np.unique(np.round(capacitance, 4))
        series = np.sort(series_resonance(levels, inductance))
        anti = np.sort(parallel_resonance(levels, cp_pf, inductance))
        print(f"\n{args.branch_nf:g} nF x {parts} per branch "
              f"({args.branch_nf * parts:g} nF):")
        print(f"  C_eq {capacitance.min() / 1000:.1f}-{capacitance.max() / 1000:.1f} nF, "
              f"{levels.size} distinct levels out of 60 states")
        print(f"  series resonance     {series[0] / 1e3:.1f}-{series[-1] / 1e3:.1f} kHz"
              f"  ({series[0] / 1e6:.3f}-{series[-1] / 1e6:.3f} MHz)")
        print(f"  anti-resonance (Cp)  {anti[0] / 1e3:.1f}-{anti[-1] / 1e3:.1f} kHz"
              f"  ({anti[0] / 1e6:.3f}-{anti[-1] / 1e6:.3f} MHz)")
        resistance = args.coil_ohm + args.relays_in_path * args.relay_ohm
        quality = 2 * np.pi * series * inductance / resistance
        print(f"  Q with {resistance:.2f} ohm in the loop  "
              f"{quality[0]:.1f}-{quality[-1]:.1f}")
        rows.append((parts, capacitance, levels, series, anti, quality))

    # Reachability: what it would take to sit at 15-30 kHz.
    print(f"\nto resonate at {args.band_low:g}-{args.band_high:g} kHz "
          f"the tank needs L*C = 1/(2 pi f)^2:")
    reach = []
    for frequency in (args.band_low, args.band_high):
        for capacitance_nf in (args.branch_nf, 2 * args.branch_nf):
            needed = 1.0 / ((2.0 * np.pi * frequency * 1e3) ** 2
                            * capacitance_nf * 1e-9)
            reach.append((frequency, capacitance_nf, needed))
            print(f"  f = {frequency:>4g} kHz with {capacitance_nf:>5g} nF "
                  f"-> L = {needed * 1e3:7.3f} mH "
                  f"({needed / inductance:6.0f} x this coil, "
                  f"{turns_for(needed, inductance):.0f} turns)")
    lowest = 1.0 / (2.0 * np.pi * np.sqrt(
        inductance * 2 * args.branch_nf * 1000 * 1e-12))
    print(f"\nlowest resonance the kit can reach on this coil: "
          f"{lowest / 1e3:.1f} kHz ({lowest / 1e6:.3f} MHz), "
          f"{lowest / (args.band_high * 1e3):.0f} x above {args.band_high:g} kHz")

    # The Cp trap.
    fixed_200 = parallel_resonance(np.array([rows[0][1].min(), rows[0][1].max()]),
                                   200.0, inductance)
    print(f"keeping Cp at 200 pF would park the anti-resonance at "
          f"{fixed_200.min() / 1e6:.1f}-{fixed_200.max() / 1e6:.1f} MHz: the array "
          f"moves it by {(fixed_200.max() - fixed_200.min()) / 1e3:.0f} kHz only, "
          f"so Cp must be raised too")

    # The array always spans a factor of four in capacitance, which is a factor
    # of two in frequency, so a coil that puts the largest level at 15 kHz
    # sweeps exactly 15-30 kHz.  Which kit and how many turns that implies is
    # independent of the branch values themselves.
    print(f"\nloop that would put the whole 4x array span on "
          f"{args.band_low:g}-{args.band_high:g} kHz:")
    paths = []
    for label, cmax_nf in (("100 nF kit, one part", 100.0),
                           ("100 nF kit, two parts", 200.0),
                           ("10 uF kit, one part", 10_000.0),
                           ("10 uF kit, two parts", 20_000.0)):
        needed = 1.0 / ((2.0 * np.pi * args.band_low * 1e3) ** 2
                        * cmax_nf * 1e-9)
        turns = turns_for(needed, inductance)
        paths.append({"kit": label, "c_max_nf": cmax_nf,
                      "inductance_uh": needed * 1e6, "turns": turns})
        print(f"  {label:22s} C_max {cmax_nf:>7g} nF -> L = {needed * 1e6:8.2f} uH "
              f"({needed / inductance:5.0f} x, {turns:4.1f} turns)")

    args.output.mkdir(parents=True, exist_ok=True)
    parts, capacitance, levels, series, anti, quality = rows[0]
    order = np.argsort(capacitance)
    with (args.output / "surface_coil_states.csv").open(
            "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("rank", "state", "capacitance_nf", "f_series_khz",
                         "f_parallel_khz", "end_node", "branch_nf"))
        for rank, index in enumerate(order, 1):
            state = model.states[index]
            writer.writerow((rank, index, f"{capacitance[index] / 1000:.4f}",
                             f"{series_resonance(capacitance[index], inductance) / 1e3:.2f}",
                             f"{parallel_resonance(capacitance[index], cp_pf, inductance) / 1e3:.2f}",
                             f"({state.end[0]},{state.end[1]})",
                             f"{args.branch_nf * parts:g}"))

    figure, (full, need) = plt.subplots(
        1, 2, figsize=(14.5, 6.4), gridspec_kw={"width_ratios": [1.15, 1.0]})
    figure.patch.set_facecolor("white")
    figure.subplots_adjust(left=0.07, right=0.985, top=0.83, bottom=0.13,
                           wspace=0.24)
    figure.suptitle("Fall demo on the real 31P surface coil",
                    fontsize=17, fontweight="bold", x=0.07, ha="left", y=0.965)
    figure.text(0.07, 0.905,
                f"Single-turn loop, L = {inductance * 1e9:.0f} nH; "
                f"every array branch {args.branch_nf * parts:g} nF (kit maximum)",
                fontsize=10.5, color="#475569")

    for _, cap, lev, ser, ant, _q in rows:
        style = "-" if _ == 1 else "--"
        full.plot(np.arange(1, lev.size + 1), np.sort(series_resonance(lev, inductance)) / 1e3,
                  style, color="#2563eb" if _ == 1 else "#7c3aed", lw=1.8,
                  marker="o", markersize=4,
                  label=f"{args.branch_nf * _:g} nF per branch ({lev.size} levels)")
    full.axhspan(args.band_low, args.band_high, color="#dcfce7", zorder=0,
                 label=f"Requested {args.band_low:g}-{args.band_high:g} kHz")
    full.axhline(F_WINTER_HZ / 1e3, color="#ea580c", lw=1.2, ls=":",
                 label="51.705 MHz, the Winter target")
    full.set_yscale("log")
    full.set_ylim(10, 1e5)
    full.set_xlim(0.5, 12.5)
    ticks = [10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000]
    full.set_yticks(ticks)
    full.set_yticklabels([f"{value:,}" for value in ticks])
    full.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    full.set_xlabel("Distinct capacitance level (of 60 states)")
    full.set_ylabel("Series resonance (kHz)")
    full.set_title("A  Where the coil actually lands", loc="left",
                   fontweight="bold", pad=8)
    full.grid(True, alpha=0.15, which="both")
    full.legend(loc="upper left", frameon=False, fontsize=8.5)

    frequency = np.geomspace(1e3, 1e6, 400)
    for capacitance_nf, colour in ((args.branch_nf, "#2563eb"),
                                   (2 * args.branch_nf, "#7c3aed")):
        needed = 1.0 / ((2.0 * np.pi * frequency) ** 2 * capacitance_nf * 1e-9)
        need.plot(frequency / 1e3, needed * 1e6, color=colour, lw=2.0,
                  label=f"{capacitance_nf:g} nF")
    need.axvspan(args.band_low, args.band_high, color="#dcfce7", zorder=0)
    need.axhline(inductance * 1e6, color="#ea580c", lw=1.4, ls="--")
    need.text(1.15, inductance * 1e6 * 1.8,
              f"this coil, {inductance * 1e9:.0f} nH",
              color="#ea580c", fontsize=9, fontweight="bold")
    need.set_xscale("log")
    need.set_yscale("log")
    need.set_xlim(1.0, 1e3)
    need.set_ylim(1e-1, 1e4)
    need.set_xlabel("Resonance frequency (kHz)")
    need.set_ylabel("Loop inductance needed (uH)")
    need.set_title("B  Inductance a 15-30 kHz demo would need", loc="left",
                   fontweight="bold", pad=8)
    need.grid(True, alpha=0.15, which="both")
    need.legend(loc="upper right", frameon=False, fontsize=9,
                title="Tank capacitance", title_fontsize=9)

    path = args.output / "surface_coil_band.png"
    figure.savefig(path, dpi=200, facecolor="white")
    plt.close(figure)

    report = {
        "coil_inductance_nh": inductance * 1e9,
        "winter_check_mhz": check / 1e6,
        "branch_nf": args.branch_nf,
        "fixed_nf": args.fixed_nf,
        "band_khz": [args.band_low, args.band_high],
        "levels": [
            {"parts": parts_,
             "branch_nf": args.branch_nf * parts_,
             "levels": int(len(lev)),
             "c_min_nf": float(cap.min() / 1000),
             "c_max_nf": float(cap.max() / 1000),
             "f_series_khz": [float(ser[0] / 1e3), float(ser[-1] / 1e3)],
             "f_parallel_khz": [float(ant[0] / 1e3), float(ant[-1] / 1e3)]}
            for parts_, cap, lev, ser, ant, _q in rows
        ],
        "needed_inductance": [
            {"frequency_khz": float(f), "capacitance_nf": float(c),
             "inductance_mh": float(l * 1e3), "turns": float(turns_for(l, inductance))}
            for f, c, l in reach
        ],
        "lowest_reachable_khz": float(lowest / 1e3),
    }
    (args.output / "surface_coil_design.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
