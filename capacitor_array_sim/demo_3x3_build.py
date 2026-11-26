"""Build the 3 x 3 Fall-term demo: catalogue values, lookup table, BOM, plot.

Steps
1. Read the optimised capacitor values from ``demo_output/optimisation.json``.
2. Replace each with the nearest parallel combination of at most three PPI
   GMC C0G parts.
3. If the catalogue values lose more than five in-band states, re-tune the
   choice of combinations.
4. Write the lookup table (20 switch bits), the capacitor list, the purchase
   list and the capacitance plot.

Run ``python capacitor_array_sim/demo_3x3_build.py``.
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

from demo_3x3_catalog import Combos, catalogue, total_pf
from demo_3x3_model import BAND_PF, DEFAULT_C_OFF_PF, DemoModel, demo_states
from turn_on_capacitor import build_graph

LOW, HIGH = BAND_PF
LOST_STATES_ALLOWED = 5


def edge_slots(model):
    """Human-readable C-name, source and target for each mesh switch."""
    names = []
    for index, edge in enumerate(model.edges):
        names.append((f"C{index + 1}",
                      f"({edge.source.row},{edge.source.column})",
                      f"({edge.target.row},{edge.target.column})"))
    return names


def approximate(model, combos, targets):
    chosen, values = [], []
    for target in targets:
        ranked = combos.nearest(target, 6)
        chosen.append(ranked[0][1])
        values.append(total_pf(ranked[0][1]))
    return chosen, np.array(values)


def count_in_band(model, values, c_off):
    capacitance = model.capacitances(values, c_off)
    return int(((capacitance >= LOW) & (capacitance <= HIGH)).sum())


def retune(model, combos, chosen, targets, c_off, best):
    """Swap one position at a time for a combination that raises the count."""
    for _ in range(4):
        improved = False
        for index in range(len(targets)):
            for _, parts in combos.nearest(targets[index], 10):
                if parts == chosen[index]:
                    continue
                trial = list(chosen)
                trial[index] = parts
                values = np.array([total_pf(parts_) for parts_ in trial])
                score = count_in_band(model, values, c_off)
                if score > best:
                    chosen, best, improved = trial, score, True
                    break
        if not improved:
            break
    return chosen, best


def write_capacitors(path, model, targets, chosen, names):
    rows = []
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("position", "from_node", "to_node", "target_pf",
                         "part1", "part2", "part3", "nominal_pf", "error_pf",
                         "part_count"))
        for index, (target, parts) in enumerate(zip(targets, chosen)):
            nominal = total_pf(parts)
            numbers = [part.number for part in parts] + [""] * (3 - len(parts))
            writer.writerow((names[index][0], names[index][1], names[index][2],
                             f"{target:.3f}", numbers[0], numbers[1], numbers[2],
                             f"{nominal:.1f}", f"{nominal - target:.4f}",
                             len(parts)))
            rows.append((target, parts, nominal))
    return rows


def write_purchase_list(path, chosen):
    counts = {}
    for parts in chosen:
        for part in parts:
            key = (part.series, part.case, part.value_pf)
            counts[key] = counts.get(key, 0) + 1
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("part_number", "series", "case", "value_pf", "quantity"))
        for (series, case, value), quantity in sorted(
                counts.items(), key=lambda item: (item[0][2], item[0][0])):
            writer.writerow((f"{series}-{_code(value)}", series, case,
                             f"{value:g}", quantity))
    return sum(counts.values())


def _code(value):
    from demo_3x3_catalog import value_code
    return value_code(value)


def write_lookup(path, model, capacitance, c_off):
    names = edge_slots(model)
    order = np.argsort(capacitance)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["level", "state", "capacitance_pf", "in_band", "end_node"]
            + [name for name, _, _ in names]
            + [f"E{index + 1}" for index in range(8)]
            + ["bits_C1_to_C12_then_E1_to_E8", "hex_word"])
        for rank, index in enumerate(order, 1):
            state = model.states[index]
            mesh = [(state.mesh_mask >> bit) & 1 for bit in range(model.edge_count)]
            end = [0] * 8
            end[state.end[0] * 3 + state.end[1] - 1] = 1
            bits = mesh + end
            word = sum(bit << position for position, bit in enumerate(bits))
            value = capacitance[index]
            writer.writerow(
                [rank, index, f"{value:.4f}",
                 int(LOW <= value <= HIGH), f"({state.end[0]},{state.end[1]})"]
                + mesh + end
                + ["".join(str(bit) for bit in bits), f"0x{word:05X}"])
    return order


def plot(path, model, ideal, catalog, label="PPI GMC catalogue values"):
    figure, (full, zoom) = plt.subplots(
        2, 1, figsize=(11.5, 8.6),
        gridspec_kw={"height_ratios": [1.0, 1.0]})
    figure.patch.set_facecolor("white")
    figure.subplots_adjust(left=0.09, right=0.97, top=0.87, bottom=0.10,
                           hspace=0.42)
    figure.suptitle("3 x 3 switched-capacitor array, all 60 states",
                    fontsize=16, fontweight="bold", x=0.09, ha="left", y=0.965)
    figure.text(0.09, 0.925,
                f"Free capacitor values (grey) and {label} (blue); "
                f"relay C_off = {DEFAULT_C_OFF_PF:g} pF",
                fontsize=10.5, color="#475569")

    order = np.arange(1, len(ideal) + 1)
    ideal_values = np.sort(ideal)
    catalog_values = np.sort(catalog)
    in_band = (catalog_values >= LOW) & (catalog_values <= HIGH)

    full.axhspan(LOW, HIGH, color="#dcfce7", zorder=0,
                 label="Target band 150-250 pF")
    full.plot(order, ideal_values, color="#94a3b8", lw=1.6, ls="--",
              label=f"Free values ({int(((ideal >= LOW) & (ideal <= HIGH)).sum())}/60)")
    full.plot(order, catalog_values, color="#2563eb", lw=1.8,
              label=f"Catalogue values ({int(in_band.sum())}/60)")
    full.scatter(order, catalog_values,
                 c=["#16a34a" if flag else "#ea580c" for flag in in_band],
                 s=20, zorder=3)
    full.set_xlim(1, len(order))
    full.set_ylim(0, max(catalog_values.max(), ideal_values.max()) * 1.05)
    full.set_xlabel("Rank after sorting")
    full.set_ylabel("Equivalent capacitance (pF)")
    full.set_title("A  All 60 states", loc="left", fontweight="bold", pad=8)
    full.grid(True, alpha=0.15)
    full.legend(loc="upper left", frameon=False, fontsize=9)

    inside = np.sort(catalog_values[in_band])
    zoom_ranks = np.arange(1, len(inside) + 1)
    zoom.axhspan(LOW, HIGH, color="#dcfce7", zorder=0)
    zoom.plot(zoom_ranks, inside, color="#2563eb", marker="o", markersize=3,
              lw=1.5)
    zoom.set_xlim(1, max(2, len(inside)))
    zoom.set_ylim(LOW - 5, HIGH + 5)
    zoom.set_xlabel(f"Rank among the {len(inside)} in-band states")
    zoom.set_ylabel("Equivalent capacitance (pF)")
    zoom.set_title("B  In-band states", loc="left", fontweight="bold", pad=8)
    zoom.grid(True, alpha=0.15)
    if len(inside) > 1:
        gaps = np.diff(inside)
        summary = (f"median gap {np.median(gaps):.2f} pF, "
                   f"largest {gaps.max():.2f} pF")
    else:
        summary = "no in-band states"
    figure.text(0.09, 0.035,
                f"In band: {len(inside)}/60     Range: {catalog_values.min():.1f}-"
                f"{catalog_values.max():.1f} pF     {summary}",
                fontsize=9.5, color="#334155")

    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=220, facecolor="white")
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    base = Path(__file__).with_name("demo_output")
    parser.add_argument("--optimisation", type=Path,
                        default=base / "optimisation.json")
    parser.add_argument("--output", type=Path, default=base)
    parser.add_argument("--case", choices=("mixed", "0805"), default="mixed",
                        help="mixed = 0603 below 1 nF plus 2225 above; 0805 = all 0805")
    parser.add_argument("--c-off", type=float, default=DEFAULT_C_OFF_PF)
    args = parser.parse_args()

    payload = json.loads(args.optimisation.read_text(encoding="utf-8"))
    targets = payload["values_pf"]
    model = DemoModel()
    combos = Combos(catalogue(args.case))

    ideal = model.capacitances(np.array(targets), args.c_off)
    ideal_count = int(((ideal >= LOW) & (ideal <= HIGH)).sum())

    chosen, values = approximate(model, combos, targets)
    count = count_in_band(model, values, args.c_off)
    print(f"free values: {ideal_count}/60 in band")
    print(f"catalogue values: {count}/60 in band")

    if ideal_count - count > LOST_STATES_ALLOWED:
        print(f"lost more than {LOST_STATES_ALLOWED} states, re-tuning")
        chosen, count = retune(model, combos, chosen, targets, args.c_off,
                               count)
        values = np.array([total_pf(parts) for parts in chosen])
        print(f"after re-tune: {count}/60 in band")

    names = edge_slots(model)
    args.output.mkdir(parents=True, exist_ok=True)
    rows = write_capacitors(args.output / "capacitors.csv", model, targets,
                            chosen, names)
    total_parts = write_purchase_list(args.output / "purchase_list.csv", chosen)
    capacitance = model.capacitances(values, args.c_off)
    write_lookup(args.output / "lookup_table.csv", model, capacitance, args.c_off)
    plot(args.output / "array_3x3_states.png", model, ideal, capacitance)

    maximum_error = max(abs(nominal - target)
                        for (target, _, nominal) in rows)
    print(f"parts: {total_parts} capacitors; maximum nominal error "
          f"{maximum_error:.3f} pF")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
