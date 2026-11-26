"""Find well-spaced equivalent capacitances for the 3x3 capacitor grid.

Run from the repository root with ``python capacitor_array_sim/optimize_3x3.py``.
Each of the twelve edge positions is an independent, continuously valued
capacitor. All sixty valid switch configurations and their terminal nodes are
included in every score.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
import random

from build_array import CapacitorGraph
from calc_equivalent_capacitance import calculate_equivalent_capacitance
from turn_on_capacitor import build_graph, validate_capacitor_array


INITIAL_PF = tuple(float(value) for value in range(12, 0, -1))
CAPACITOR_NAMES = tuple(f"c_{value}" for value in range(12, 0, -1))


@dataclass(frozen=True)
class State:
    mask: int
    destination: tuple[int, int]


@dataclass(frozen=True)
class Metrics:
    minimum_pf: float
    maximum_pf: float
    span_pf: float
    mean_gap_pf: float
    minimum_gap_pf: float
    maximum_gap_pf: float
    gap_std_pf: float
    gap_cv: float
    worst_gap_ratio: float


class ArrayModel:
    """Reuse the existing validator and nodal solver for all 3x3 states."""

    def __init__(self) -> None:
        self.graph: CapacitorGraph = build_graph(3, 3)
        self.edges = sorted(
            self.graph.edges,
            key=lambda edge: (
                edge.source.row + edge.target.row,
                edge.source.column + edge.target.column,
            ),
        )
        self.slots = tuple(
            (edge.source.row + edge.target.row,
             edge.source.column + edge.target.column)
            for edge in self.edges
        )
        if len(self.edges) != 12:
            raise RuntimeError("The 3x3 graph must have twelve capacitors")

        states = []
        for mask in range(1, 1 << len(self.edges)):
            switch_array = [[0] * 5 for _ in range(5)]
            for position, (row, column) in enumerate(self.slots):
                switch_array[row][column] = (mask >> position) & 1
            try:
                selected = validate_capacitor_array(self.graph, switch_array)
            except ValueError:
                continue
            sources = {edge.source for edge in selected}
            sinks = {edge.target for edge in selected} - sources
            if len(sinks) != 1:
                raise RuntimeError("Valid state has no unique destination")
            end = sinks.pop()
            states.append(State(mask, (end.row, end.column)))
        if len(states) != 60:
            raise RuntimeError(f"Expected 60 valid states, found {len(states)}")
        self.states = tuple(states)

    def evaluate(self, capacitances_pf: tuple[float, ...] | list[float]):
        if len(capacitances_pf) != 12 or any(
            not math.isfinite(value) or value <= 0 for value in capacitances_pf
        ):
            raise ValueError("Provide twelve positive, finite capacitances")
        for edge, value in zip(self.edges, capacitances_pf):
            edge.capacitance = float(value)

        outputs = []
        for state in self.states:
            for position, edge in enumerate(self.edges):
                edge.switch = bool(state.mask & (1 << position))
            value = calculate_equivalent_capacitance(self.graph, state.destination)
            outputs.append((value, state))
        return sorted(outputs, key=lambda item: (item[0], item[1].mask))


def summarize(outputs: list[tuple[float, State]]) -> Metrics:
    values = [value for value, _ in outputs]
    gaps = [right - left for left, right in zip(values, values[1:])]
    span = values[-1] - values[0]
    if span <= 0:
        raise ValueError("All state outputs are equal")
    mean_gap = span / len(gaps)
    variance = math.fsum((gap - mean_gap) ** 2 for gap in gaps) / len(gaps)
    return Metrics(
        minimum_pf=values[0],
        maximum_pf=values[-1],
        span_pf=span,
        mean_gap_pf=mean_gap,
        minimum_gap_pf=min(gaps),
        maximum_gap_pf=max(gaps),
        gap_std_pf=math.sqrt(variance),
        gap_cv=math.sqrt(variance) / mean_gap,
        worst_gap_ratio=max(gaps) / mean_gap,
    )


def spacing_score(metrics: Metrics, minimum_span_pf: float,
                  worst_gap_weight: float) -> float:
    """Relative spacing error, worst gap, and a strong span-shortfall penalty."""
    shortfall = max(0.0, minimum_span_pf - metrics.span_pf) / minimum_span_pf
    return (
        metrics.gap_cv
        + worst_gap_weight * (metrics.worst_gap_ratio - 1.0)
        + 100.0 * shortfall
    )


def print_metrics(name: str, metrics: Metrics) -> None:
    print(
        f"{name}: range {metrics.minimum_pf:.6f}..{metrics.maximum_pf:.6f} pF, "
        f"gap std {metrics.gap_std_pf:.6f} pF, "
        f"gap CV {metrics.gap_cv:.6f}, "
        f"smallest/largest gap {metrics.minimum_gap_pf:.6f}/"
        f"{metrics.maximum_gap_pf:.6f} pF"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-cap-pf", type=float, default=0.5)
    parser.add_argument("--max-cap-pf", type=float, default=15.0)
    parser.add_argument("--min-span-pf", type=float, default=None,
                        help="Minimum output span; defaults to the starting span")
    parser.add_argument("--worst-gap-weight", type=float, default=0.1)
    parser.add_argument("--restarts", type=int, default=3,
                        help="Powell runs: descending start plus perturbed starts")
    parser.add_argument("--maxfev", type=int, default=1800,
                        help="Maximum objective evaluations per Powell run")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path,
                        help="Optional JSON file with values and all 60 state outputs")
    args = parser.parse_args()
    if not (math.isfinite(args.min_cap_pf) and math.isfinite(args.max_cap_pf)
            and 0 < args.min_cap_pf <= min(INITIAL_PF)
            and max(INITIAL_PF) <= args.max_cap_pf):
        parser.error("Require 0 < --min-cap-pf <= 1 and --max-cap-pf >= 12")
    if args.min_span_pf is not None and (
        not math.isfinite(args.min_span_pf) or args.min_span_pf <= 0
    ):
        parser.error("--min-span-pf must be positive and finite")
    if not (math.isfinite(args.worst_gap_weight)
            and args.worst_gap_weight >= 0 and args.restarts >= 1
            and args.maxfev >= 1):
        parser.error("Require a nonnegative weight and positive restart/evaluation counts")

    try:
        from scipy.optimize import minimize
    except ImportError:
        parser.exit(2, "Install the optimizer dependency: python -m pip install scipy\n")

    model = ArrayModel()
    initial_outputs = model.evaluate(INITIAL_PF)
    initial_metrics = summarize(initial_outputs)
    minimum_span = (initial_metrics.span_pf if args.min_span_pf is None
                    else args.min_span_pf)
    feasible_tolerance = 1e-8
    best_values = INITIAL_PF if initial_metrics.span_pf + feasible_tolerance >= minimum_span else None
    best_score = (spacing_score(initial_metrics, minimum_span, args.worst_gap_weight)
                  if best_values is not None else math.inf)
    rng = random.Random(args.seed)

    def objective(values) -> float:
        nonlocal best_values, best_score
        proposed = tuple(float(value) for value in values)
        metrics = summarize(model.evaluate(proposed))
        score = spacing_score(metrics, minimum_span, args.worst_gap_weight)
        if (metrics.span_pf + feasible_tolerance >= minimum_span
                and score < best_score):
            best_values, best_score = proposed, score
        return score

    bounds = [(args.min_cap_pf, args.max_cap_pf)] * 12
    for restart in range(args.restarts):
        if restart == 0:
            start = INITIAL_PF
        else:
            center = best_values if best_values is not None else INITIAL_PF
            start = tuple(
                min(args.max_cap_pf, max(args.min_cap_pf,
                    value * math.exp(rng.gauss(0, 0.18))))
                for value in center
            )
        result = minimize(
            objective, start, method="Powell", bounds=bounds,
            options={"maxfev": args.maxfev, "xtol": 1e-4, "ftol": 1e-5},
        )
        print(f"Run {restart + 1}/{args.restarts}: {result.nfev} evaluations; "
              f"best feasible score {best_score:.6f}")

    if best_values is None:
        parser.exit(1, "No placement met the minimum output span within the search budget.\n")
    final_outputs = model.evaluate(best_values)
    final_metrics = summarize(final_outputs)
    print(f"States: {len(model.states)}; minimum output span: {minimum_span:.6f} pF")
    print_metrics("Start", initial_metrics)
    print_metrics("Best ", final_metrics)
    print("Capacitor values (pF), top-to-bottom and left-to-right:")
    for name, slot, value in zip(CAPACITOR_NAMES, model.slots, best_values):
        print(f"  {name:>4} at slot {slot}: {value:.9f}")

    if args.output is not None:
        report = {
            "method": "bounded Powell search with seeded restarts",
            "states": len(model.states),
            "minimum_span_pf": minimum_span,
            "component_bounds_pf": [args.min_cap_pf, args.max_cap_pf],
            "worst_gap_weight": args.worst_gap_weight,
            "seed": args.seed,
            "slot_order": [
                {"capacitor": name, "switch_matrix_row": row,
                 "switch_matrix_column": column}
                for name, (row, column) in zip(CAPACITOR_NAMES, model.slots)
            ],
            "initial": {"capacitances_pf": INITIAL_PF,
                        "metrics": vars(initial_metrics)},
            "best": {
                "capacitances_pf": dict(zip(CAPACITOR_NAMES, best_values)),
                "metrics": vars(final_metrics),
                "score": best_score,
                "outputs": [
                    {"rank": index, "equivalent_capacitance_pf": value,
                     "state_mask": format(state.mask, "012b"),
                     "active_capacitors": [
                         name for position, name in enumerate(CAPACITOR_NAMES)
                         if state.mask & (1 << position)
                     ],
                     "destination": state.destination}
                    for index, (value, state) in enumerate(final_outputs, 1)
                ],
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
