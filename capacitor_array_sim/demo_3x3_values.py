"""Run the 3 x 3 array with the real capacitor set 10 / 47 / 100 nF.

The Fall build does not need matched values: three part numbers (10 nF, 47 nF,
100 nF) and at most three in parallel give 19 reachable branch values, and the
spreadsheet in the design notes lists twelve of them:

    300 247 210 200 194 157 147 120 110 100 104 94   (nF)

Those twelve go on the twelve branches of the grid, one each.  The script then
evaluates all 60 switch states on the real 31P surface loop (284 nH) and writes
the frequency of every state, the branch assignment and the figure.

Compared with putting the same 100 nF part everywhere (which collapses the 60
states onto 12 resonances), handing every branch a different total separates
all 60.

Run ``python capacitor_array_sim/demo_3x3_values.py``.
"""

from __future__ import annotations

import argparse
import csv
import json
from itertools import combinations_with_replacement
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from demo_3x3_model import DemoModel
from demo_surface_coil import coil_inductance, series_resonance

PARTS_NF = (10.0, 47.0, 100.0)
MAX_PARALLEL = 3

#: The twelve totals from the design spreadsheet, with the parts that make them.
ASSIGNMENT_NF = (
    (300.0, (100.0, 100.0, 100.0)),
    (247.0, (100.0, 100.0, 47.0)),
    (210.0, (100.0, 100.0, 10.0)),
    (200.0, (100.0, 100.0)),
    (194.0, (100.0, 47.0, 47.0)),
    (157.0, (100.0, 47.0, 10.0)),
    (147.0, (100.0, 47.0)),
    (120.0, (100.0, 10.0, 10.0)),
    (110.0, (100.0, 10.0)),
    (100.0, (100.0,)),
    (104.0, (47.0, 47.0, 10.0)),
    (94.0, (47.0, 47.0)),
)


def achievable(values=PARTS_NF, max_parallel=MAX_PARALLEL):
    """Every parallel sum of at most ``max_parallel`` parts, with one build."""
    sums = {}
    for size in range(1, max_parallel + 1):
        for combo in combinations_with_replacement(values, size):
            sums.setdefault(round(sum(combo), 6), combo)
    return dict(sorted(sums.items()))


def check_assignment():
    for total, parts in ASSIGNMENT_NF:
        if abs(sum(parts) - total) > 1e-9:
            raise ValueError(f"{parts} does not add to {total}")
        if len(parts) > MAX_PARALLEL:
            raise ValueError(f"{parts} uses more than {MAX_PARALLEL} parts")


def main() -> int:
    base = Path(__file__).with_name("demo_output")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coil-nh", type=float, default=None)
    parser.add_argument("--output", type=Path, default=base)
    args = parser.parse_args()

    check_assignment()
    inductance = (args.coil_nh * 1e-9 if args.coil_nh is not None
                  else coil_inductance())
    model = DemoModel()
    values = np.array([total for total, _ in ASSIGNMENT_NF], dtype=float) * 1000.0

    capacitance = model.capacitances(values, 0.0)
    frequency = series_resonance(capacitance, inductance) / 1e3
    levels = np.unique(np.round(capacitance, 6))
    order = np.argsort(frequency)

    uniform = model.capacitances(np.full(model.edge_count, 100_000.0), 0.0)
    uniform_levels = np.unique(np.round(uniform, 6))
    uniform_frequency = series_resonance(uniform_levels, inductance) / 1e3

    sums = achievable()
    print(f"loop {inductance * 1e9:.0f} nH, parts {PARTS_NF} nF, "
          f"up to {MAX_PARALLEL} in parallel")
    print(f"{len(sums)} reachable branch values: "
          f"{', '.join(f'{value:g}' for value in sums)} nF")
    print(f"\nassignment C1..C12 (nF): "
          f"{', '.join(f'{total:g}' for total, _ in ASSIGNMENT_NF)}")
    print(f"C_eq {capacitance.min() / 1000:.1f}-{capacitance.max() / 1000:.1f} nF, "
          f"{levels.size} distinct levels out of {model.state_count} states")
    print(f"resonance {frequency.min():.1f}-{frequency.max():.1f} kHz "
          f"({frequency.min() / 1e3:.3f}-{frequency.max() / 1e3:.3f} MHz)")
    gaps = np.diff(np.sort(frequency))
    print(f"median step {np.median(gaps):.1f} kHz, largest {gaps.max():.1f} kHz")
    print(f"uniform 100 nF build for comparison: {uniform_levels.size} levels, "
          f"{uniform_frequency.min():.0f}-{uniform_frequency.max():.0f} kHz")

    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "values_lookup.csv").open(
            "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("level", "state", "capacitance_nf", "frequency_khz",
                         "end_node", "C1_nf", "C2_nf", "C3_nf", "C4_nf",
                         "C5_nf", "C6_nf", "C7_nf", "C8_nf", "C9_nf", "C10_nf",
                         "C11_nf", "C12_nf", "E1", "E2", "E3", "E4", "E5",
                         "E6", "E7", "E8"))
        for level, index in enumerate(order, 1):
            state = model.states[index]
            end = [0] * 8
            end[state.end[0] * 3 + state.end[1] - 1] = 1
            mesh = [(state.mesh_mask >> bit) & 1 for bit in range(model.edge_count)]
            writer.writerow(
                (level, index, f"{capacitance[index] / 1000:.3f}",
                 f"{series_resonance(capacitance[index], inductance) / 1e3:.2f}",
                 f"({state.end[0]},{state.end[1]})")
                + tuple(f"{value / 1000:g}" for value in values)
                + tuple(end))
    with (args.output / "values_branches.csv").open(
            "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("position", "total_nf", "parts_nf", "part_count"))
        for position, (total, parts) in enumerate(ASSIGNMENT_NF, 1):
            writer.writerow((f"C{position}", f"{total:g}",
                             " + ".join(f"{part:g}" for part in parts),
                             len(parts)))

    figure, (full, bars) = plt.subplots(
        2, 1, figsize=(11.5, 8.8),
        gridspec_kw={"height_ratios": [1.35, 1.0]})
    figure.patch.set_facecolor("white")
    figure.subplots_adjust(left=0.10, right=0.97, top=0.86, bottom=0.10,
                           hspace=0.40)
    figure.suptitle("3 x 3 array with 10 / 47 / 100 nF parts",
                    fontsize=16, fontweight="bold", x=0.10, ha="left", y=0.965)
    figure.text(0.10, 0.925,
                f"Real single-turn 31P loop, L = {inductance * 1e9:.0f} nH; "
                f"one of the twelve totals on each branch, at most "
                f"{MAX_PARALLEL} parts in parallel",
                fontsize=10.5, color="#475569")

    rank = np.arange(1, len(order) + 1)
    full.plot(rank, np.sort(frequency), color="#2563eb", lw=1.8, marker="o",
              markersize=4, label=f"12 different totals ({levels.size}/60 distinct)")
    full.axhspan(uniform_frequency.min(), uniform_frequency.max(),
                 color="#e2e8f0", zorder=0,
                 label=f"100 nF everywhere: {uniform_levels.size} levels, "
                       f"{uniform_frequency.min():.0f}-{uniform_frequency.max():.0f} kHz")
    full.set_yscale("log")
    full.set_xlim(0.5, 61)
    full.set_ylim(430, 2400)
    ticks = [450, 500, 600, 700, 850, 1000, 1250, 1500, 1750, 2000]
    full.set_yticks(ticks)
    full.set_yticklabels([f"{value:,}" for value in ticks])
    full.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    full.set_xlabel("Rank after sorting by resonance frequency")
    full.set_ylabel("Resonance frequency (kHz)")
    full.set_title("A  All 60 switch states", loc="left", fontweight="bold",
                   pad=8)
    full.grid(True, alpha=0.15, which="both")
    full.legend(loc="upper left", frameon=False, fontsize=9)

    positions = np.arange(1, len(ASSIGNMENT_NF) + 1)
    totals = [total for total, _ in ASSIGNMENT_NF]
    colours = {1: "#0ea5e9", 2: "#6366f1", 3: "#a855f7"}
    for position, (total, parts) in zip(positions, ASSIGNMENT_NF):
        bars.bar(position, total, width=0.68, color=colours[len(parts)],
                 edgecolor="white")
        bars.text(position, total + 8, f"{total:g}", ha="center", va="bottom",
                  fontsize=8.5, color="#334155")
    bars.set_xticks(positions)
    bars.set_xticklabels([f"C{index}" for index in positions], fontsize=9)
    bars.set_ylim(0, 340)
    bars.set_xlim(0.4, len(positions) + 0.6)
    bars.set_ylabel("Branch capacitance (nF)")
    bars.set_xlabel("Branch position in the 3 x 3 grid, (0,0) at the feed")
    bars.set_title("B  What goes where", loc="left", fontweight="bold", pad=8)
    bars.grid(True, axis="y", alpha=0.15)
    handles = [plt.Rectangle((0, 0), 1, 1, color=colours[count])
               for count in (1, 2, 3)]
    bars.legend(handles, ["1 part", "2 parts", "3 parts"], loc="upper right",
                frameon=False, fontsize=9)

    path = args.output / "values_3x3_states.png"
    figure.savefig(path, dpi=220, facecolor="white")
    plt.close(figure)

    report = {
        "loop_nh": inductance * 1e9,
        "parts_nf": list(PARTS_NF),
        "max_parallel": MAX_PARALLEL,
        "reachable_nf": [float(value) for value in sums],
        "assignment_nf": [float(total) for total, _ in ASSIGNMENT_NF],
        "distinct_levels": int(levels.size),
        "c_min_nf": float(capacitance.min() / 1000),
        "c_max_nf": float(capacitance.max() / 1000),
        "frequency_khz": [float(frequency.min()), float(frequency.max())],
        "uniform_levels": int(uniform_levels.size),
        "states": [
            {"level": level + 1, "state": int(index),
             "capacitance_nf": float(capacitance[index] / 1000),
             "frequency_khz": float(series_resonance(capacitance[index],
                                                     inductance) / 1e3)}
            for level, index in enumerate(order)
        ],
    }
    (args.output / "values_design.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
