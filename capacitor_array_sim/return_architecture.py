"""Return architectures for the switched-capacitor array.

An m x n node grid has one switched capacitor on every pair of adjacent nodes.
The mesh alone does not say how the far side of the array gets back to the RF
reference, and that choice decides which switch states are physically usable.
This module implements the two architectures that were evaluated for the
modular tuner:

``MUX``
    Every node on the far edge (last row or last column) owns a switch to the
    ground plane. A hardware one-hot decoder closes exactly one of them, so the
    mesh always sees one sink and a state is ``(mesh switches, end node)``.
    All ``(m - 1) * n + m * (n - 1)`` capacitors are populated. For a 3 x 4
    grid this is 17 mesh switches plus 6 end switches.

``RAIL``
    All far-edge nodes are joined by one copper rail and a single master
    switch connects that rail to ground. Every capacitor whose two ends both
    sit on the rail is short-circuited by the rail and is not populated, so a
    3 x 4 grid uses 12 mesh switches plus one master switch. A state is only
    the mesh switches; paths may terminate anywhere on the rail, and several
    paths in parallel are allowed.

    A rail state can put a short path in parallel with a long one and return
    the two through different lengths of rail, so their series reactance
    differs. That breaks the equal-length rule the design uses to keep a state
    a single predictable capacitance, and is why the rail is kept here only as
    a comparison; ``MUX`` is the architecture that is built.

The module enumerates every usable state of either architecture, returns the
equivalent capacitance of each state through the existing nodal solver, and
reports the switch budget so the two can be compared before layout.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from numbers import Real
from pathlib import Path

from calc_equivalent_capacitance import (
    calculate_equivalent_capacitance,
    calculate_equivalent_capacitance_to_grounds,
    calculate_equivalent_capacitance_with_parasitics,
    conducting_edges,
)
from turn_on_capacitor import build_graph

MUX = "mux"
RAIL = "rail"
ARCHITECTURES = (MUX, RAIL)

FAR_EDGE = "far-edge"
ALL_ENDS = "all-ends"
END_SCOPES = (FAR_EDGE, ALL_ENDS)

TARGET_LOW_PF = 150.0
TARGET_HIGH_PF = 250.0


@dataclass(frozen=True)
class ArrayState:
    """One usable switch configuration.

    ``mesh_mask`` has one bit per capacitor edge, in ``CapacitorGraph.edges``
    order. ``end`` is the grounded node for the mux architecture and ``None``
    for the rail architecture, where the rail is the only return.
    """

    mesh_mask: int
    end: tuple[int, int] | None
    capacitance_pf: float


@dataclass(frozen=True)
class SwitchPlan:
    architecture: str
    rows: int
    columns: int
    mesh_switches: int
    end_switches: int
    master_switches: int
    unpopulated_slots: tuple[tuple[int, int], ...]

    @property
    def total_switches(self) -> int:
        return self.mesh_switches + self.end_switches + self.master_switches


@dataclass(frozen=True)
class Summary:
    architecture: str
    states: int
    distinct_capacitances: int
    minimum_pf: float
    maximum_pf: float
    median_gap_pf: float
    maximum_gap_pf: float
    states_in_band: int
    distinct_in_band: int
    band_pf: tuple[float, float]
    band_median_gap_pf: float
    band_maximum_gap_pf: float


def all_end_nodes(rows: int, columns: int) -> tuple[tuple[int, int], ...]:
    """Every node a path can terminate on, in row-major order."""
    return tuple((row, column) for row in range(rows) for column in range(columns)
                 if (row, column) != (0, 0))


def far_edge_nodes(rows: int, columns: int) -> tuple[tuple[int, int], ...]:
    """The end nodes on the last row or the last column.

    Paths can terminate on any node, but a state that ends short of the far
    edge is reachable without touching the return. Keeping the return switches
    on the far edge only costs a few states and removes the switches that would
    otherwise sit next to the source.
    """
    return tuple((row, column) for row in range(rows) for column in range(columns)
                 if (row, column) != (0, 0)
                 and (row == rows - 1 or column == columns - 1))


def _slot(edge) -> tuple[int, int]:
    return (edge.source.row + edge.target.row,
            edge.source.column + edge.target.column)


def switch_plan(rows: int, columns: int, architecture: str,
                end_scope: str = FAR_EDGE) -> SwitchPlan:
    """Count switches for an architecture without enumerating any state."""
    if architecture not in ARCHITECTURES:
        raise ValueError(f"architecture must be one of {ARCHITECTURES}")
    if end_scope not in END_SCOPES:
        raise ValueError(f"end_scope must be one of {END_SCOPES}")
    graph = build_graph(rows, columns)
    edges = graph.edges
    if architecture == MUX:
        ends = (far_edge_nodes(rows, columns) if end_scope == FAR_EDGE
                else all_end_nodes(rows, columns))
        return SwitchPlan(architecture, rows, columns, len(edges), len(ends), 0, ())
    rail = set(far_edge_nodes(rows, columns))
    shorted = tuple(
        _slot(edge) for edge in edges
        if (edge.source.row, edge.source.column) in rail
        and (edge.target.row, edge.target.column) in rail
    )
    return SwitchPlan(architecture, rows, columns, len(edges) - len(shorted),
                      0, 1, shorted)


def _path_union_masks(edges, end: tuple[int, int]):
    """Yield every mesh mask that is a union of paths from (0, 0) to ``end``.

    The check is local: in a right/down graph, an edge set is a union of
    complete paths exactly when every used internal node has both an incoming
    and an outgoing selected edge, the source has only outgoing edges and the
    end has only incoming edges.
    """
    max_row, max_column = end
    local = [index for index, edge in enumerate(edges)
             if edge.source.row <= max_row and edge.source.column <= max_column]
    incoming_bits: dict[tuple[int, int], int] = {}
    outgoing_bits: dict[tuple[int, int], int] = {}
    for bit, edge_index in enumerate(local):
        edge = edges[edge_index]
        source = (edge.source.row, edge.source.column)
        target = (edge.target.row, edge.target.column)
        outgoing_bits[source] = outgoing_bits.get(source, 0) | (1 << bit)
        incoming_bits[target] = incoming_bits.get(target, 0) | (1 << bit)
    nodes = sorted(set(incoming_bits) | set(outgoing_bits))
    source_node = (0, 0)

    for local_mask in range(1, 1 << len(local)):
        for node in nodes:
            incoming = local_mask & incoming_bits.get(node, 0)
            outgoing = local_mask & outgoing_bits.get(node, 0)
            if node == source_node:
                valid = bool(outgoing) and not incoming
            elif node == end:
                valid = bool(incoming) and not outgoing
            else:
                valid = bool(incoming) == bool(outgoing)
            if not valid:
                break
        else:
            global_mask = 0
            for bit, edge_index in enumerate(local):
                if local_mask >> bit & 1:
                    global_mask |= 1 << edge_index
            yield global_mask


def _apply_mask(graph, mask: int) -> None:
    for index, edge in enumerate(graph.edges):
        edge.switch = bool(mask >> index & 1)


def _set_capacitances(graph, capacitances) -> None:
    for edge, value in zip(graph.edges, capacitances):
        edge.capacitance = float(value)


def enumerate_states(rows: int, columns: int, architecture: str,
                     capacitances=None,
                     end_scope: str = FAR_EDGE,
                     off_capacitance: float = 0.0) -> list[ArrayState]:
    """Return every usable state of one architecture, sorted by capacitance.

    ``capacitances`` is one value per capacitor edge in ``CapacitorGraph.edges``
    order; omitted values default to 1 pF so the result is a ratio study.
    ``end_scope`` applies to the mux architecture only.

    ``off_capacitance`` is the capacitance of one open switch. With a positive
    value every open mesh branch still couples its two nodes through the series
    combination of its capacitor and that capacitance, and every unselected end
    switch shunts its node to ground. The set of states is unchanged; only the
    capacitance of each state moves.
    """
    if architecture not in ARCHITECTURES:
        raise ValueError(f"architecture must be one of {ARCHITECTURES}")
    if end_scope not in END_SCOPES:
        raise ValueError(f"end_scope must be one of {END_SCOPES}")
    if (isinstance(off_capacitance, bool) or not isinstance(off_capacitance, Real)
            or not math.isfinite(off_capacitance) or off_capacitance < 0):
        raise ValueError("off_capacitance must be a nonnegative finite number")
    graph = build_graph(rows, columns)
    edges = graph.edges
    if capacitances is None:
        capacitances = [1.0] * len(edges)
    if len(capacitances) != len(edges):
        raise ValueError(f"expected {len(edges)} capacitances, got {len(capacitances)}")
    _set_capacitances(graph, capacitances)

    states: list[ArrayState] = []
    if architecture == MUX:
        ends = (far_edge_nodes(rows, columns) if end_scope == FAR_EDGE
                else all_end_nodes(rows, columns))
        for end in ends:
            shunts = {node: off_capacitance for node in ends if node != end}
            for mask in _path_union_masks(edges, end):
                _apply_mask(graph, mask)
                if off_capacitance > 0:
                    value = calculate_equivalent_capacitance_with_parasitics(
                        graph, (end,), off_capacitance, shunts)
                else:
                    value = calculate_equivalent_capacitance(graph, end)
                states.append(ArrayState(mask, end, value))
    else:
        rail = tuple(sorted(far_edge_nodes(rows, columns)))
        rail_set = set(rail)
        plan = switch_plan(rows, columns, RAIL)
        shorted = set(plan.unpopulated_slots)
        for edge in edges:
            if _slot(edge) in shorted:
                edge.capacitance = 0.0
        useful = [index for index, edge in enumerate(edges)
                  if not ((edge.source.row, edge.source.column) in rail_set
                          and (edge.target.row, edge.target.column) in rail_set)]
        seen: set[int] = set()
        for subset in range(1, 1 << len(useful)):
            for edge in edges:
                edge.switch = False
            for bit, edge_index in enumerate(useful):
                if subset >> bit & 1:
                    edges[edge_index].switch = True
            try:
                value = calculate_equivalent_capacitance_to_grounds(
                    graph, rail, strict=False)
            except ValueError:
                continue
            # Several subsets reduce to the same live network once capacitors
            # on an open-ended branch are ignored; keep one of each.
            live = conducting_edges(graph, rail)
            mask = 0
            for index, edge in enumerate(edges):
                if any(edge is item for item in live):
                    mask |= 1 << index
            if mask in seen:
                continue
            seen.add(mask)
            if off_capacitance > 0:
                value = calculate_equivalent_capacitance_with_parasitics(
                    graph, rail, off_capacitance)
            states.append(ArrayState(mask, None, value))

    states.sort(key=lambda state: (state.capacitance_pf, state.mesh_mask))
    return states


def summarize(states, architecture: str,
              band: tuple[float, float] = (TARGET_LOW_PF, TARGET_HIGH_PF)) -> Summary:
    if not states:
        raise ValueError("no states to summarize")
    values = [state.capacitance_pf for state in states]
    unique = sorted({round(value, 9) for value in values})
    gaps = [right - left for left, right in zip(unique, unique[1:])]
    low, high = band
    levels = [value for value in unique if low <= value <= high]
    band_gaps = [right - left for left, right in zip(levels, levels[1:])]
    return Summary(
        architecture=architecture,
        states=len(states),
        distinct_capacitances=len(unique),
        minimum_pf=unique[0],
        maximum_pf=unique[-1],
        median_gap_pf=(sorted(gaps)[len(gaps) // 2] if gaps else 0.0),
        maximum_gap_pf=(max(gaps) if gaps else 0.0),
        states_in_band=sum(1 for value in values if low <= value <= high),
        distinct_in_band=len(levels),
        band_pf=(low, high),
        band_median_gap_pf=(sorted(band_gaps)[len(band_gaps) // 2]
                            if band_gaps else 0.0),
        band_maximum_gap_pf=(max(band_gaps) if band_gaps else 0.0),
    )


@dataclass(frozen=True)
class OffComparison:
    architecture: str
    end_switches: int
    states: int
    states_in_band_ideal: int
    states_in_band_off: int
    mean_shift_pf: float
    maximum_shift_pf: float
    maximum_relative_shift: float
    maximum_shift_steps: float
    median_gap_ideal: float
    median_gap_off: float
    maximum_gap_ideal: float
    maximum_gap_off: float


def compare_off_capacitance(ideal_states, realistic_states, plan: SwitchPlan,
                            band: tuple[float, float] = (TARGET_LOW_PF, TARGET_HIGH_PF)) -> OffComparison:
    """Compare one architecture with and without the open-switch capacitance."""
    realistic = {(state.mesh_mask, state.end): state.capacitance_pf
                 for state in realistic_states}
    pairs = []
    for state in ideal_states:
        key = (state.mesh_mask, state.end)
        if key not in realistic:
            raise ValueError("the two enumerations do not cover the same states")
        pairs.append((state.capacitance_pf, realistic[key]))
    shifts = [after - before for before, after in pairs]
    before_summary = summarize(ideal_states, plan.architecture, band)
    after_summary = summarize(realistic_states, plan.architecture, band)
    largest = max(shifts, key=abs)
    return OffComparison(
        architecture=plan.architecture,
        end_switches=plan.end_switches,
        states=len(pairs),
        states_in_band_ideal=before_summary.states_in_band,
        states_in_band_off=after_summary.states_in_band,
        mean_shift_pf=sum(shifts) / len(shifts),
        maximum_shift_pf=largest,
        maximum_relative_shift=max(abs(shift) / before
                                   for shift, (before, _) in zip(shifts, pairs)),
        maximum_shift_steps=(abs(largest) / before_summary.median_gap_pf
                             if before_summary.median_gap_pf > 0 else float("inf")),
        median_gap_ideal=before_summary.median_gap_pf,
        median_gap_off=after_summary.median_gap_pf,
        maximum_gap_ideal=before_summary.maximum_gap_pf,
        maximum_gap_off=after_summary.maximum_gap_pf,
    )


def load_capacitances(graph, path) -> list[float]:
    """Read capacitor values from a study JSON with slot_order and values."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "capacitors_pf" not in payload or "slot_order" not in payload:
        raise ValueError("capacitance file needs 'capacitors_pf' and 'slot_order'")
    by_slot = {(item["switch_matrix_row"], item["switch_matrix_column"]): item["capacitor"]
               for item in payload["slot_order"]}
    values = []
    for edge in graph.edges:
        slot = _slot(edge)
        if slot not in by_slot:
            raise ValueError(f"capacitance file is missing slot {slot}")
        values.append(float(payload["capacitors_pf"][by_slot[slot]]))
    return values


def _format_row(plan: SwitchPlan, summary: Summary) -> str:
    return (f"{plan.architecture:<5} {plan.mesh_switches:>5} {plan.end_switches:>5} "
            f"{plan.master_switches:>7} {plan.total_switches:>6} {summary.states:>7} "
            f"{summary.distinct_capacitances:>9} {summary.states_in_band:>7} "
            f"{summary.minimum_pf:>9.2f} {summary.maximum_pf:>9.2f} "
            f"{summary.maximum_gap_pf:>8.2f}")


def _variant_label(architecture: str, end_scope: str) -> str:
    if architecture == MUX:
        return "mux (far edge)" if end_scope == FAR_EDGE else "mux (all ends)"
    return "rail (compare)"


def _print_off_comparison(args, capacitances, band) -> int:
    print(f"{args.rows} x {args.columns} node grid, {len(capacitances)} capacitors, "
          f"C_off = {args.c_off:g} pF")
    if args.capacitors is None and min(capacitances) < 10 * args.c_off:
        print("note: the capacitors are unrealistic uniform values, so the relative "
              "shift is not meaningful; pass --capacitors or a larger --cap-pf")
    print(f"{'variant':<15} {'ends':>4} {'states':>6} {'in band':>12} "
          f"{'mean dC':>8} {'max dC':>8} {'max rel':>8} {'dC/steps':>9} "
          f"{'median gap':>15} {'max gap':>15}")

    report = {"rows": args.rows, "columns": args.columns,
              "capacitances_pf": capacitances, "c_off_pf": args.c_off,
              "comparison": []}
    variants = ((MUX, FAR_EDGE), (MUX, ALL_ENDS), (RAIL, FAR_EDGE))
    for architecture, end_scope in variants:
        plan = switch_plan(args.rows, args.columns, architecture, end_scope)
        ideal = enumerate_states(args.rows, args.columns, architecture,
                                 capacitances, end_scope)
        realistic = enumerate_states(args.rows, args.columns, architecture,
                                     capacitances, end_scope, args.c_off)
        comparison = compare_off_capacitance(ideal, realistic, plan, band)
        print(f"{_variant_label(architecture, end_scope):<15} "
              f"{comparison.end_switches:>4} {comparison.states:>6} "
              f"{comparison.states_in_band_ideal:>4} -> {comparison.states_in_band_off:<4} "
              f"{comparison.mean_shift_pf:>+8.2f} {comparison.maximum_shift_pf:>+8.2f} "
              f"{100 * comparison.maximum_relative_shift:>7.2f}% "
              f"{comparison.maximum_shift_steps:>9.1f} "
              f"{comparison.median_gap_ideal:>6.2f} -> {comparison.median_gap_off:<6.2f} "
              f"{comparison.maximum_gap_ideal:>6.2f} -> {comparison.maximum_gap_off:<6.2f}")
        report["comparison"].append({
            "variant": _variant_label(architecture, end_scope),
            "architecture": architecture,
            "end_scope": end_scope,
            "end_switches": plan.end_switches,
            "total_switches": plan.total_switches,
            "states": comparison.states,
            "states_in_band_ideal": comparison.states_in_band_ideal,
            "states_in_band_off": comparison.states_in_band_off,
            "mean_shift_pf": comparison.mean_shift_pf,
            "maximum_shift_pf": comparison.maximum_shift_pf,
            "maximum_relative_shift": comparison.maximum_relative_shift,
            "maximum_shift_steps": comparison.maximum_shift_steps,
            "median_gap_ideal_pf": comparison.median_gap_ideal,
            "median_gap_off_pf": comparison.median_gap_off,
            "maximum_gap_ideal_pf": comparison.maximum_gap_ideal,
            "maximum_gap_off_pf": comparison.maximum_gap_off,
        })

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Saved {args.output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--architecture", choices=("both",) + ARCHITECTURES,
                        default="both")
    parser.add_argument("--cap-pf", type=float, default=1.0,
                        help="uniform capacitance for every edge (default 1.0)")
    parser.add_argument("--capacitors", type=Path,
                        help="study JSON with slot_order and capacitors_pf")
    parser.add_argument("--band-low", type=float, default=TARGET_LOW_PF)
    parser.add_argument("--band-high", type=float, default=TARGET_HIGH_PF)
    parser.add_argument("--c-off", type=float, default=0.0,
                        help="open-switch capacitance in pF; a positive value "
                             "compares every variant with and without it")
    parser.add_argument("--output", type=Path,
                        help="optional JSON file with every state")
    args = parser.parse_args()
    if args.rows < 2 and args.columns < 2:
        parser.error("the grid needs at least two nodes")
    if not (math.isfinite(args.cap_pf) and args.cap_pf > 0):
        parser.error("--cap-pf must be positive and finite")
    if not (0 < args.band_low < args.band_high):
        parser.error("require 0 < --band-low < --band-high")
    if not (math.isfinite(args.c_off) and args.c_off >= 0):
        parser.error("--c-off must be a nonnegative finite number")

    graph = build_graph(args.rows, args.columns)
    if args.capacitors is not None:
        capacitances = load_capacitances(graph, args.capacitors)
    else:
        capacitances = [args.cap_pf] * len(graph.edges)

    band = (args.band_low, args.band_high)
    if args.c_off > 0:
        return _print_off_comparison(args, capacitances, band)

    architectures = ARCHITECTURES if args.architecture == "both" else (args.architecture,)
    print(f"{args.rows} x {args.columns} node grid, {len(graph.edges)} capacitors")
    print(f"{'arch':<5} {'mesh':>5} {'end':>5} {'master':>7} {'total':>6} "
          f"{'states':>7} {'distinct':>9} {'in-band':>7} {'min pF':>9} {'max pF':>9} "
          f"{'max gap':>8}")

    report = {"rows": args.rows, "columns": args.columns,
              "capacitances_pf": capacitances, "architectures": {}}
    for architecture in architectures:
        plan = switch_plan(args.rows, args.columns, architecture)
        states = enumerate_states(args.rows, args.columns, architecture,
                                  capacitances)
        summary = summarize(states, architecture, (args.band_low, args.band_high))
        print(_format_row(plan, summary))
        print(f"      in {summary.band_pf[0]:g}-{summary.band_pf[1]:g} pF: "
              f"{summary.states_in_band} states ({summary.distinct_in_band} distinct "
              f"levels), in-band gap median {summary.band_median_gap_pf:.2f} pF, "
              f"in-band max gap {summary.band_maximum_gap_pf:.2f} pF")
        if plan.unpopulated_slots:
            print(f"      rail shorts out {len(plan.unpopulated_slots)} capacitor slot(s): "
                  f"{list(plan.unpopulated_slots)}")
        report["architectures"][architecture] = {
            "plan": {
                "mesh_switches": plan.mesh_switches,
                "end_switches": plan.end_switches,
                "master_switches": plan.master_switches,
                "total_switches": plan.total_switches,
                "unpopulated_slots": [list(slot) for slot in plan.unpopulated_slots],
            },
            "summary": {
                "states": summary.states,
                "distinct_capacitances": summary.distinct_capacitances,
                "minimum_pf": summary.minimum_pf,
                "maximum_pf": summary.maximum_pf,
                "median_gap_pf": summary.median_gap_pf,
                "maximum_gap_pf": summary.maximum_gap_pf,
                "states_in_band": summary.states_in_band,
                "distinct_in_band": summary.distinct_in_band,
                "band_pf": list(summary.band_pf),
                "band_median_gap_pf": summary.band_median_gap_pf,
                "band_maximum_gap_pf": summary.band_maximum_gap_pf,
            },
            "states": [
                {"mesh_mask": format(state.mesh_mask, "b"),
                 "end": list(state.end) if state.end is not None else None,
                 "capacitance_pf": state.capacitance_pf}
                for state in states
            ],
        }

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
