"""Re-run the 3 x 3 demo with a KEMET CER ENG KIT 28 style assortment.

The kit manifest is not published on the distributor pages this script can
reach, so the value list below is an assumption: 0402 C0G, E24 (or E12) values
from 0.5 pF to 1 nF. Replace ``KIT_E24_PF``/``KIT_E12_PF`` with the real
manifest and re-run; nothing else needs to change.

Each position may use at most three parts in parallel. Because the kit values
are coarser than the PPI GMC catalogue, the script also searches the achievable
sums directly instead of only rounding each target once.
"""

from __future__ import annotations

import argparse
import csv
import json
from itertools import combinations_with_replacement
from pathlib import Path

import numpy as np

from demo_3x3_build import plot, write_lookup
from demo_3x3_catalog import Part
from demo_3x3_model import BAND_PF, DEFAULT_C_OFF_PF, DemoModel

LOW, HIGH = BAND_PF

KIT_C0G_PF = (10, 22, 120, 180, 270, 1000)
# In-range subset of a typical 15-value radial assortment (10 pF to 100 nF):
# only values at or below 2.2 nF can contribute to a 2 nF position.
CHEAP_E6_PF = (10, 15, 22, 33, 47, 68, 100, 220, 470, 1000, 2200)

KIT_E24_PF = (
    0.5, 1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3,
    3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1, 10, 11, 12, 13,
    15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75,
    82, 91, 100, 110, 120, 130, 150, 160, 180, 200, 220, 240, 270, 300, 330,
    360, 390, 430, 470, 510, 560, 620, 680, 750, 820, 910, 1000,
)
KIT_E12_PF = (
    0.5, 1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2, 10,
    12, 15, 18, 22, 27, 33, 39, 47, 56, 68, 82, 100, 120, 150, 180, 220,
    270, 330, 390, 470, 560, 680, 820, 1000,
)
KIT_VALUES = {"kit": KIT_C0G_PF, "e24": KIT_E24_PF, "e12": KIT_E12_PF,
              "e6": CHEAP_E6_PF}


def kit_parts(series: str):
    return [Part(value, "KEMET-C0G", "0402") for value in KIT_VALUES[series]]


def achievable(parts):
    """Map every sum of at most three parts to its shortest representative."""
    values = sorted({part.value_pf for part in parts})
    lookup = {part.value_pf: part for part in parts}
    best = {}
    for size in (1, 2, 3):
        for combo in combinations_with_replacement(values, size):
            total = round(sum(combo), 6)
            if total not in best:
                best[total] = tuple(lookup[value] for value in combo)
    return best


def total(parts_):
    return sum(part.value_pf for part in parts_)


def in_band(model, values, c_off):
    capacitance = model.capacitances(np.asarray(values), c_off)
    return int(((capacitance >= LOW) & (capacitance <= HIGH)).sum()), capacitance


def project(values, sums):
    order = np.asarray(sums)
    return [float(order[np.argmin(np.abs(order - value))]) for value in values]


def search(model, sums, start_values, c_off, restarts=30, span=12):
    """Hill climb over the achievable sums, one position at a time."""
    order = np.asarray(sums)
    best_values = list(start_values)
    best_count, _ = in_band(model, best_values, c_off)
    rng = np.random.default_rng(2026)

    def climb(values, count):
        improved = True
        while improved:
            improved = False
            for position in rng.permutation(len(values)):
                index = int(np.argmin(np.abs(order - values[position])))
                for step in list(range(-span, span + 1)):
                    if step == 0:
                        continue
                    candidate_index = index + step
                    if not 0 <= candidate_index < len(order):
                        continue
                    candidate = list(values)
                    candidate[position] = float(order[candidate_index])
                    score, _ = in_band(model, candidate, c_off)
                    if score > count:
                        values, count = candidate, score
                        improved = True
                        break
        return values, count

    best_values, best_count = climb(best_values, best_count)
    for _ in range(restarts):
        start = list(best_values)
        for position in rng.choice(len(start), size=4, replace=False):
            index = int(np.argmin(np.abs(order - start[position])))
            offset = int(rng.integers(-span, span + 1))
            candidate_index = min(max(index + offset, 0), len(order) - 1)
            start[position] = float(order[candidate_index])
        values, count = climb(start, in_band(model, start, c_off)[0])
        if count > best_count:
            best_values, best_count = values, count
    return best_values, best_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    base = Path(__file__).with_name("demo_output")
    parser.add_argument("--optimisation", type=Path,
                        default=base / "optimisation.json")
    parser.add_argument("--output", type=Path, default=base)
    parser.add_argument("--series", choices=("kit", "e6", "e24", "e12"),
                        default="kit",
                        help="kit = the six C0G values in CER ENG KIT 28; "
                             "e6 = a 15-value radial assortment")
    parser.add_argument("--c-off", type=float, default=DEFAULT_C_OFF_PF)
    parser.add_argument("--restarts", type=int, default=200)
    args = parser.parse_args()

    payload = json.loads(args.optimisation.read_text(encoding="utf-8"))
    targets = payload["values_pf"]
    model = DemoModel()

    parts = kit_parts(args.series)
    sums = achievable(parts)
    part_for_sum = sums
    ordered = sorted(sums)

    continuous = model.capacitances(np.asarray(targets), args.c_off)
    continuous_count = int(((continuous >= LOW) & (continuous <= HIGH)).sum())

    projected = project(targets, ordered)
    start_count, _ = in_band(model, projected, args.c_off)
    values, count = search(model, ordered, projected, args.c_off,
                           restarts=args.restarts)

    print(f"kit: {'CER ENG KIT 28 C0G subset' if args.series == 'kit' else args.series.upper() + ' assumption'}")
    print(f"kit values: {', '.join(f'{value:g}' for value in KIT_VALUES[args.series])} pF")
    print(f"free values: {continuous_count}/60 in band")
    print(f"kit, nearest rounding: {start_count}/60")
    print(f"kit, searched: {count}/60")

    capacitance = model.capacitances(np.asarray(values), args.c_off)
    chosen = [part_for_sum[round(value, 6)] for value in values]
    total_parts = sum(len(parts_) for parts_ in chosen)

    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / f"capacitors_{args.series}.csv").open(
            "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("position", "target_pf", "part1_pf", "part2_pf",
                         "part3_pf", "nominal_pf", "error_pf", "part_count"))
        for index, (target, parts_) in enumerate(zip(targets, chosen), 1):
            nominal = total(parts_)
            row = [f"{part.value_pf:g}" for part in parts_]
            row += [""] * (3 - len(row))
            writer.writerow((f"C{index}", f"{target:.3f}", row[0], row[1],
                             row[2], f"{nominal:g}", f"{nominal - target:.3f}",
                             len(parts_)))

    usage = {}
    for parts_ in chosen:
        for part in parts_:
            usage[part.value_pf] = usage.get(part.value_pf, 0) + 1
    with (args.output / f"usage_{args.series}.csv").open(
            "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("value_pf", "quantity"))
        for value, quantity in sorted(usage.items()):
            writer.writerow((f"{value:g}", quantity))

    plot(args.output / f"array_3x3_{args.series}.png", model,
         continuous, capacitance,
         label=f"KEMET kit ({args.series.upper()}) values")
    write_lookup(args.output / f"lookup_{args.series}.csv", model,
                 capacitance, args.c_off)

    inside = capacitance[(capacitance >= LOW) & (capacitance <= HIGH)]
    gaps = np.diff(np.sort(inside))
    print(f"parts: {total_parts} capacitors, {len(usage)} distinct values")
    print(f"in-band range {inside.min():.1f}-{inside.max():.1f} pF, median gap "
          f"{np.median(gaps):.2f} pF, largest {gaps.max():.2f} pF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
