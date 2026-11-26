"""Fall-term low-frequency demo: the same 3 x 3 array, tuned to 15-30 kHz.

Why this script exists
----------------------
The Winter-term target is 51.705 MHz (31P at 3 T), where the array has to
produce 150-250 pF out of sub-picofarad parts.  The Fall-term deliverable is
much weaker: only show that the array *produces different capacitances and can
be tuned*.  The measurement band for that demo is 15-30 kHz, so the same 60
switch states are re-scaled onto an audio-frequency LC tank.

The scaling is not arbitrary.  The equivalent capacitance of a capacitor
network is a homogeneous function of degree one: multiplying every branch
capacitor by ``k`` multiplies every state's ``C_eq`` by ``k``.  The resonance
frequency of an LC tank only sees ``L * C_eq``, so a design is fixed by the
*ratios* of the twelve capacitors plus one overall scale, and that scale can be
absorbed into the inductor.  The demo therefore buys ordinary nanofarad parts
and a millinery-scale choke instead of picofarad parts and a 43 nH loop.

Two facts drive the whole design:

1.  With every branch equal, the 3 x 3 array spans exactly a factor of four
    (a one-edge path from the source gives ``C``, a four-edge path gives
    ``C / 4``), which is exactly the 15 kHz -> 30 kHz ratio.
2.  So the useful question is not "how wide a range" but "how evenly do the 60
    states fill that factor-of-four window".

The script fixes the inductor at a purchasable value, converts 15-30 kHz into
the capacitance window that the tank needs, optimises the twelve branch values
to land as many of the 60 states inside that window as possible, then snaps
each branch to one or two parts from the 24-value 0.1 nF-100 nF through-hole
kit and re-tunes.

Run ``python capacitor_array_sim/demo_3x3_lowfreq.py``.
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
from scipy.optimize import differential_evolution

from demo_3x3_catalog import value_code
from demo_3x3_model import DemoModel

BAND_KHZ = (15.0, 30.0)
MAX_PARALLEL = 2
DEFAULT_L_H = 4.7e-3

# Values of the 24-value 0.1 nF-100 nF through-hole kit (Tnisesm Tn-19 and the
# identical DYWISHKEY box).  The published manifest is not reachable from the
# distributor pages, so this is the E6 ladder that such a box always contains;
# it is a superset of every value the optimiser asks for.  Override with
# --kit-csv (one pF value per line) once the physical box is in hand.
KIT_LF_PF = (
    100, 150, 220, 330, 470, 680,
    1000, 1500, 2200, 3300, 4700, 6800,
    10000, 15000, 22000, 33000, 47000, 68000,
    100000,
)


# --------------------------------------------------------------------------
# Frequency <-> capacitance
# --------------------------------------------------------------------------

def window_pf(low_khz=BAND_KHZ[0], high_khz=BAND_KHZ[1],
              inductance_h=DEFAULT_L_H):
    """Capacitance window that puts the tank at low_khz and high_khz.

    Returns ``(c_low, c_high)`` in pF, with ``c_low`` resonating at ``high_khz``
    because capacitance and frequency run in opposite directions.
    """
    c_low = 1.0 / ((2.0 * np.pi * high_khz * 1e3) ** 2 * inductance_h) * 1e12
    c_high = 1.0 / ((2.0 * np.pi * low_khz * 1e3) ** 2 * inductance_h) * 1e12
    return c_low, c_high


def frequency_khz(capacitance_pf, inductance_h=DEFAULT_L_H):
    capacitance = np.asarray(capacitance_pf, dtype=float) * 1e-12
    return 1.0 / (2.0 * np.pi * np.sqrt(inductance_h * capacitance)) / 1e3


def inductance_for(capacitance_pf, frequency_khz_):
    """Inductance that resonates this capacitance at this frequency."""
    capacitance = float(capacitance_pf) * 1e-12
    return 1.0 / ((2.0 * np.pi * frequency_khz_ * 1e3) ** 2 * capacitance)


# --------------------------------------------------------------------------
# Kit values and parallel combinations
# --------------------------------------------------------------------------

class KitCombos:
    """Every parallel combination of at most ``MAX_PARALLEL`` kit parts."""

    def __init__(self, values=KIT_LF_PF, max_parallel=MAX_PARALLEL):
        self.values = tuple(sorted(set(float(value) for value in values)))
        self.max_parallel = max_parallel
        self.sums = {}
        for size in range(1, max_parallel + 1):
            for combo in combinations_with_replacement(self.values, size):
                total = round(sum(combo), 6)
                if total not in self.sums:
                    self.sums[total] = combo
        self.order = np.array(sorted(self.sums))

    def nearest(self, target, count=6):
        """Closest achievable sums, ranked by error and then by part count."""
        index = int(np.searchsorted(self.order, target))
        low = max(0, index - 12)
        high = min(self.order.size, index + 13)
        candidates = sorted(self.order[low:high],
                            key=lambda total: (abs(total - target),
                                               len(self.sums[total])))
        return [(abs(total - target), self.sums[total]) for total in candidates][:count]

    def snap(self, targets):
        chosen = []
        for target in targets:
            ranked = self.nearest(target, 4)
            chosen.append(ranked[0][1])
        return chosen


def total_of(parts):
    return float(sum(parts))


# --------------------------------------------------------------------------
# Optimisation
# --------------------------------------------------------------------------

def window_stats(capacitance, low, high):
    """Count in band, how much of the window it fills, and its worst log gap.

    ``coverage`` is the logarithmic span of the in-band states divided by the
    span of the window: 1.0 means the states run from one edge of the window to
    the other, so the demo sweeps the whole 15-30 kHz band.
    """
    capacitance = np.asarray(capacitance, dtype=float)
    inside = (capacitance >= low) & (capacitance <= high)
    count = int(inside.sum())
    if count < 2:
        return count, 0.0, 0.0
    values = np.sort(capacitance[inside])
    span = float(np.log(values[-1] / values[0]) / np.log(high / low))
    return count, min(span, 1.0), float(np.diff(np.log(values)).max())


def better(candidate, incumbent):
    """Lexicographic: more states, then wider coverage, then smaller worst gap."""
    return (candidate[0], round(candidate[1], 6), -candidate[2]) > (
        incumbent[0], round(incumbent[1], 6), -incumbent[2])


def objective(log_values, model, c_off, low, high):
    """Count in the window, with soft terms so differential evolution can move."""
    values = 10.0 ** np.asarray(log_values)
    capacitance = model.capacitances(values, c_off)
    inside = (capacitance >= low) & (capacitance <= high)
    shortfall = np.sum(np.maximum(0.0, low - capacitance) / low
                       + np.maximum(0.0, capacitance - high) / high)
    count, coverage, _ = window_stats(capacitance, low, high)
    return -float(count) - 0.5 * coverage + 0.004 * float(shortfall)


def score(values, model, c_off, low, high):
    capacitance = model.capacitances(np.asarray(values, dtype=float), c_off)
    return window_stats(capacitance, low, high) + (capacitance,)


def polish(values, model, c_off, low, high, rng, minimum, maximum, rounds=100):
    """Multiplicative hill climb on the count, then on coverage and worst gap."""
    best = np.asarray(values, dtype=float).copy()
    best_stats = score(best, model, c_off, low, high)[:3]
    for _ in range(rounds):
        improved = False
        for index in rng.permutation(len(best)):
            for factor in (0.88, 0.92, 0.96, 0.98, 1.02, 1.04, 1.08, 1.14):
                candidate = best.copy()
                candidate[index] *= factor
                if not minimum <= candidate[index] <= maximum:
                    continue
                stats = score(candidate, model, c_off, low, high)[:3]
                if better(stats, best_stats):
                    best, best_stats = candidate, stats
                    improved = True
                    break
        if not improved:
            break
    return best, best_stats[0]


def optimise(model, c_off, low, high, seeds, maxiter, popsize, minimum, maximum):
    bounds = [(np.log10(minimum), np.log10(maximum))] * model.edge_count
    best_values, best_stats = None, (0, 0.0, np.inf)
    for seed in range(seeds):
        result = differential_evolution(
            objective, bounds, args=(model, c_off, low, high),
            seed=seed, maxiter=maxiter, popsize=popsize, tol=1e-9,
            mutation=(0.4, 1.4), recombination=0.9, polish=False, init="sobol")
        values = 10.0 ** result.x
        values, _ = polish(values, model, c_off, low, high,
                           np.random.default_rng(seed), minimum, maximum)
        stats = score(values, model, c_off, low, high)[:3]
        print(f"  seed {seed}: {stats[0]}/60 in window, coverage "
              f"{stats[1]:.2f}, largest log gap {stats[2]:.4f}")
        if best_values is None or better(stats, best_stats):
            best_values, best_stats = values, stats
    return best_values, best_stats[0]


def retune_kit(model, combos, chosen, c_off, low, high, rounds=6, span=14):
    """Swap one branch at a time for a kit combination that improves the sweep."""
    values = np.array([total_of(parts) for parts in chosen])
    best_stats = score(values, model, c_off, low, high)[:3]
    for _ in range(rounds):
        improved = False
        for index in range(len(chosen)):
            for _, parts in combos.nearest(values[index], span):
                if parts == chosen[index]:
                    continue
                trial = list(chosen)
                trial[index] = parts
                trial_values = np.array([total_of(parts_) for parts_ in trial])
                stats = score(trial_values, model, c_off, low, high)[:3]
                if better(stats, best_stats):
                    chosen, values = trial, trial_values
                    best_stats = stats
                    improved = True
                    break
        if not improved:
            break
    return chosen, values, best_stats[0]


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def edge_names(model):
    names = []
    for index, edge in enumerate(model.edges):
        names.append((f"C{index + 1}",
                      f"({edge.source.row},{edge.source.column})",
                      f"({edge.target.row},{edge.target.column})"))
    return names


def write_capacitors(path, model, targets, chosen):
    names = edge_names(model)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("position", "from_node", "to_node", "target_pf",
                         "target_nf", "part1_nf", "part2_nf", "nominal_nf",
                         "part_count", "part1_code", "part2_code"))
        for index, (target, parts) in enumerate(zip(targets, chosen)):
            codes = [value_code(part) for part in parts] + [""] * (MAX_PARALLEL - len(parts))
            writer.writerow(
                (names[index][0], names[index][1], names[index][2],
                 f"{target:.1f}", f"{target / 1000:.2f}",
                 f"{parts[0] / 1000:.2f}",
                 f"{parts[1] / 1000:.2f}" if len(parts) > 1 else "",
                 f"{total_of(parts) / 1000:.2f}", len(parts),
                 codes[0], codes[1]))


def write_bom(path, chosen):
    counts = {}
    for parts in chosen:
        for part in parts:
            counts[part] = counts.get(part, 0) + 1
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("value_nf", "marking", "quantity"))
        for value, quantity in sorted(counts.items()):
            writer.writerow((f"{value / 1000:g}", value_code(value), quantity))
    return counts


def write_lookup(path, model, capacitance, inductance_h, low, high):
    names = edge_names(model)
    order = np.argsort(capacitance)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ("level", "state", "capacitance_nf", "frequency_khz", "in_band",
             "end_node")
            + tuple(name for name, _, _ in names)
            + tuple(f"E{index + 1}" for index in range(8))
            + ("bits_C1_to_C12_then_E1_to_E8", "hex_word"))
        for level, index in enumerate(order, 1):
            state = model.states[index]
            mesh = [(state.mesh_mask >> bit) & 1 for bit in range(model.edge_count)]
            end = [0] * 8
            end[state.end[0] * 3 + state.end[1] - 1] = 1
            bits = mesh + end
            word = sum(bit << position for position, bit in enumerate(bits))
            value = float(capacitance[index])
            hertz = float(frequency_khz(value, inductance_h))
            writer.writerow(
                (level, index, f"{value / 1000:.4f}", f"{hertz:.3f}",
                 int(low <= value <= high), f"({state.end[0]},{state.end[1]})")
                + tuple(mesh) + tuple(end)
                + ("".join(str(bit) for bit in bits), f"0x{word:05X}"))
    return order


def write_uniform(path, model, capacitance, inductance_h, uniform_nf):
    """Lookup table for the one-part-number build.

    With every branch equal, many of the 60 states collapse onto the same
    resonance, so this table lists the distinct levels and one state that
    produces each.
    """
    representatives = {}
    for index, value in enumerate(capacitance):
        representatives.setdefault(round(float(value), 4), []).append(index)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("level", "capacitance_nf", "frequency_khz",
                         "state_count", "example_state", "end_node"))
        for level, value in enumerate(sorted(representatives), 1):
            states = representatives[value]
            example = model.states[states[0]]
            writer.writerow((level, f"{value / 1000:.3f}",
                             f"{float(frequency_khz(value, inductance_h)):.2f}",
                             len(states), states[0],
                             f"({example.end[0]},{example.end[1]})"))
    return len(representatives)


def plot(path, capacitance, inductance_h, low, high, free_capacitance,
         label="1-2 kit parts per branch"):
    figure, (wide, zoom) = plt.subplots(
        2, 1, figsize=(11.5, 8.8),
        gridspec_kw={"height_ratios": [1.0, 1.0]})
    figure.patch.set_facecolor("white")
    figure.subplots_adjust(left=0.10, right=0.97, top=0.86, bottom=0.10,
                           hspace=0.42)
    figure.suptitle("3 x 3 switched-capacitor array, 15-30 kHz Fall demo",
                    fontsize=16, fontweight="bold", x=0.10, ha="left", y=0.965)
    figure.text(0.10, 0.925,
                f"L = {inductance_h * 1e3:g} mH; 60 switch states ranked by the "
                f"resonance frequency of the tank they produce",
                fontsize=10.5, color="#475569")

    frequency = frequency_khz(np.sort(capacitance), inductance_h)
    free_frequency = frequency_khz(np.sort(free_capacitance), inductance_h)
    rank = np.arange(1, len(frequency) + 1)
    inside = (frequency >= BAND_KHZ[0]) & (frequency <= BAND_KHZ[1])
    free_inside = (free_frequency >= BAND_KHZ[0]) & (free_frequency <= BAND_KHZ[1])

    wide.axhspan(BAND_KHZ[0], BAND_KHZ[1], color="#dcfce7", zorder=0,
                 label="Target band 15-30 kHz")
    wide.plot(rank, free_frequency, color="#94a3b8", lw=1.6, ls="--",
              label=f"Free branch values ({int(free_inside.sum())}/60 in band)")
    wide.plot(rank, frequency, color="#2563eb", lw=1.8,
              label=f"Kit values ({int(inside.sum())}/60 in band)")
    wide.scatter(rank, frequency,
                 c=["#16a34a" if flag else "#ea580c" for flag in inside],
                 s=20, zorder=3)
    wide.set_xlim(1, len(rank))
    wide.set_yscale("log")
    wide.set_ylim(frequency.min() / 1.45, frequency.max() * 1.45)
    ticks = [value for value in (12.5, 15, 20, 25, 30, 35, 40, 50)
             if frequency.min() / 1.45 <= value <= frequency.max() * 1.45]
    wide.set_yticks(ticks)
    wide.set_yticklabels([f"{value:g}" for value in ticks])
    wide.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    wide.set_xlabel("Rank after sorting by frequency")
    wide.set_ylabel("Resonance frequency (kHz)")
    wide.set_title("A  All 60 states", loc="left", fontweight="bold", pad=8)
    wide.grid(True, alpha=0.15, which="both")
    wide.legend(loc="upper right", frameon=False, fontsize=9)

    band_frequency = np.sort(frequency[inside])
    zoom_rank = np.arange(1, len(band_frequency) + 1)
    zoom.axhspan(BAND_KHZ[0], BAND_KHZ[1], color="#dcfce7", zorder=0)
    zoom.plot(zoom_rank, band_frequency, color="#2563eb", marker="o",
              markersize=4, lw=1.5)
    zoom.set_xlim(0.5, max(1.5, len(band_frequency) + 0.5))
    zoom.set_ylim(BAND_KHZ[0] - 1.5, BAND_KHZ[1] + 1.5)
    zoom.set_xlabel(f"Rank among the {len(band_frequency)} in-band states")
    zoom.set_ylabel("Resonance frequency (kHz)")
    zoom.set_title("B  In-band states", loc="left", fontweight="bold", pad=8)
    zoom.grid(True, alpha=0.15)
    if len(band_frequency) > 1:
        gaps = np.diff(band_frequency)
        summary = (f"median step {np.median(gaps):.2f} kHz, "
                   f"largest {gaps.max():.2f} kHz")
    else:
        summary = "no in-band states"
    figure.text(0.10, 0.035,
                f"In band: {len(band_frequency)}/60     "
                f"C window: {low:,.0f}-{high:,.0f} pF     "
                f"{summary}", fontsize=9.5, color="#334155")

    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=220, facecolor="white")
    plt.close(figure)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def load_kit(path):
    if path is None:
        return KIT_LF_PF
    text = Path(path).read_text(encoding="utf-8")
    values = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if line:
            values.append(float(line.split(",")[0]))
    return tuple(values)


def main() -> int:
    base = Path(__file__).with_name("demo_output")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inductance-mh", type=float, default=DEFAULT_L_H * 1e3,
                        help="tank inductance in mH (default 4.7)")
    parser.add_argument("--band-low", type=float, default=BAND_KHZ[0])
    parser.add_argument("--band-high", type=float, default=BAND_KHZ[1])
    parser.add_argument("--min-nf", type=float, default=0.1)
    parser.add_argument("--max-nf", type=float, default=200.0)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--maxiter", type=int, default=300)
    parser.add_argument("--popsize", type=int, default=22)
    parser.add_argument("--c-off", type=float, default=0.0,
                        help="relay off capacitance, pF; negligible at 15-30 kHz")
    parser.add_argument("--kit-csv", type=Path, default=None,
                        help="optional file of real kit values in pF")
    parser.add_argument("--uniform-nf", type=float, default=22.0,
                        help="one-part-number baseline value, nF")
    parser.add_argument("--output", type=Path, default=base)
    args = parser.parse_args()

    inductance = args.inductance_mh * 1e-3
    low, high = window_pf(args.band_low, args.band_high, inductance)
    model = DemoModel()
    kit = load_kit(args.kit_csv)
    combos = KitCombos(kit)

    print(f"band {args.band_low:g}-{args.band_high:g} kHz, "
          f"L = {args.inductance_mh:g} mH")
    print(f"capacitance window {low:,.1f}-{high:,.1f} pF "
          f"({high / low:.2f} x)")
    print(f"kit: {len(kit)} values, {combos.order.size} branch values "
          f"(up to {MAX_PARALLEL} in parallel)")

    targets, count = optimise(model, args.c_off, low, high, args.seeds,
                              args.maxiter, args.popsize,
                              args.min_nf * 1000, args.max_nf * 1000)
    free_capacitance = model.capacitances(targets, args.c_off)
    free_count = int(((free_capacitance >= low) & (free_capacitance <= high)).sum())
    print(f"free branch values: {free_count}/60 in band")

    chosen = combos.snap(targets)
    chosen, values, kit_count = retune_kit(model, combos, chosen, args.c_off,
                                          low, high)
    kit_capacitance = model.capacitances(values, args.c_off)
    print(f"kit branch values:  {kit_count}/60 in band")

    args.output.mkdir(parents=True, exist_ok=True)
    write_capacitors(args.output / "lowfreq_capacitors.csv", model, targets, chosen)
    counts = write_bom(args.output / "lowfreq_bom.csv", chosen)
    order = write_lookup(args.output / "lowfreq_lookup.csv", model,
                         kit_capacitance, inductance, low, high)
    plot(args.output / "lowfreq_states.png", kit_capacitance, inductance,
         low, high, free_capacitance)

    inside = kit_capacitance[(kit_capacitance >= low) & (kit_capacitance <= high)]
    inside_frequency = np.sort(frequency_khz(inside, inductance))
    all_frequency = np.sort(frequency_khz(kit_capacitance, inductance))
    stats = window_stats(kit_capacitance, low, high)

    # Baseline: one part number on every branch.  It cannot separate all 60
    # states but it shows the topology's natural factor-of-four span.
    uniform_nf = args.uniform_nf
    uniform = model.capacitances(np.full(model.edge_count, uniform_nf * 1000), args.c_off)
    uniform_levels = np.unique(np.round(uniform, 6))
    uniform_frequency = np.sort(frequency_khz(uniform_levels, inductance))
    uniform_rows = write_uniform(args.output / "lowfreq_uniform.csv", model,
                                 uniform, inductance, uniform_nf)

    report = {
        "band_khz": [args.band_low, args.band_high],
        "inductance_mh": args.inductance_mh,
        "window_pf": [float(low), float(high)],
        "kit_values_pf": list(kit),
        "max_parallel": MAX_PARALLEL,
        "free_values_pf": [float(value) for value in targets],
        "free_states_in_band": free_count,
        "kit_states_in_band": kit_count,
        "kit_coverage": float(stats[1]),
        "kit_distinct_levels": int(np.unique(np.round(kit_capacitance, 6)).size),
        "kit_branch_pf": [float(value) for value in values],
        "bom": {f"{value:g}": quantity for value, quantity in sorted(counts.items())},
        "uniform_nf": uniform_nf,
        "uniform_levels": int(uniform_rows),
        "uniform_frequency_khz": [float(value) for value in uniform_frequency],
        "frequency_khz_all": [float(value) for value in all_frequency],
        "frequency_khz_in_band": [float(value) for value in inside_frequency],
        "states": [
            {"level": level + 1, "state": int(index),
             "capacitance_pf": float(kit_capacitance[index]),
             "frequency_khz": float(frequency_khz(kit_capacitance[index], inductance)),
             "in_band": bool(low <= kit_capacitance[index] <= high)}
            for level, index in enumerate(order)
        ],
    }
    (args.output / "lowfreq_design.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\nbranch values: {', '.join(f'{value / 1000:g}' for value in values)} nF")
    print(f"BOM: {sum(counts.values())} capacitors, "
          f"{len(counts)} distinct values")
    print(f"distinct capacitance levels: {report['kit_distinct_levels']}/60")
    print(f"all 60 states: {all_frequency[0]:.2f}-{all_frequency[-1]:.2f} kHz")
    if inside.size:
        gaps = np.diff(inside_frequency)
        print(f"in band: {inside.size}/60 ({stats[1] * 100:.0f}% of the window), "
              f"{inside_frequency[0]:.2f}-{inside_frequency[-1]:.2f} kHz, ")
        print(f"         median step {np.median(gaps):.2f} kHz, "
              f"largest {gaps.max():.2f} kHz")
    print(f"uniform {uniform_nf:g} nF baseline: {uniform_rows} levels, "
          f"{uniform_frequency[0]:.1f}-{uniform_frequency[-1]:.1f} kHz")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
