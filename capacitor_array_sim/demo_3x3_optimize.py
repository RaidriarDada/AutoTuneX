"""Maximise the number of 3 x 3 demo states inside 150-250 pF.

The twelve capacitor values are free positive numbers; only their ratios and
one scale matter. Differential evolution searches in log10 space because the
objective (a count) is a step function, and a soft shortfall term keeps a
gradient while a state is outside the band.

Run ``python capacitor_array_sim/demo_3x3_optimize.py --seeds 6``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import differential_evolution

from demo_3x3_model import BAND_PF, DEFAULT_C_OFF_PF, DemoModel

MIN_PF, MAX_PF = 20.0, 2000.0


def objective(log_values, model, c_off, low, high):
    values = 10.0 ** np.asarray(log_values)
    capacitance = model.capacitances(values, c_off)
    inside = (capacitance >= low) & (capacitance <= high)
    shortfall = np.sum(np.maximum(0.0, low - capacitance) / low
                       + np.maximum(0.0, capacitance - high) / high)
    return -float(inside.sum()) + 0.005 * float(shortfall)


def score(values, model, c_off, low, high):
    capacitance = model.capacitances(np.asarray(values, float), c_off)
    inside = (capacitance >= low) & (capacitance <= high)
    return int(inside.sum()), capacitance


def polish(values, model, c_off, low, high, rng, minimum, maximum, rounds=60):
    """Coordinate-wise multiplicative hill climb on the count."""
    best = np.asarray(values, float).copy()
    best_count, _ = score(best, model, c_off, low, high)
    for _ in range(rounds):
        improved = False
        order = rng.permutation(len(best))
        for index in order:
            for factor in (0.90, 0.94, 0.97, 1.03, 1.06, 1.11):
                candidate = best.copy()
                candidate[index] *= factor
                if candidate[index] < minimum or candidate[index] > maximum:
                    continue
                count, capacitance = score(candidate, model, c_off, low, high)
                if count > best_count:
                    best, best_count = candidate, count
                    improved = True
                    break
        if not improved:
            break
    return best, best_count


def optimise(model, c_off, low, high, seeds, maxiter, popsize, minimum, maximum):
    bounds = [(np.log10(minimum), np.log10(maximum))] * model.edge_count
    best_values = None
    best_count = -1
    for seed in range(seeds):
        result = differential_evolution(
            objective, bounds, args=(model, c_off, low, high),
            seed=seed, maxiter=maxiter, popsize=popsize, tol=1e-8,
            mutation=(0.4, 1.4), recombination=0.9, polish=False, init="sobol")
        values = 10.0 ** result.x
        count, _ = score(values, model, c_off, low, high)
        values, count = polish(values, model, c_off, low, high,
                               np.random.default_rng(seed), minimum, maximum)
        if count > best_count:
            best_values, best_count = values, count
        print(f"seed {seed}: {count}/60 in band")
    return best_values, best_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=6)
    parser.add_argument("--maxiter", type=int, default=400)
    parser.add_argument("--popsize", type=int, default=25)
    parser.add_argument("--min-pf", type=float, default=MIN_PF)
    parser.add_argument("--max-pf", type=float, default=MAX_PF)
    parser.add_argument("--c-off", type=float, default=DEFAULT_C_OFF_PF)
    parser.add_argument("--band-low", type=float, default=BAND_PF[0])
    parser.add_argument("--band-high", type=float, default=BAND_PF[1])
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).with_name("demo_output") / "optimisation.json")
    args = parser.parse_args()

    model = DemoModel()
    values, count = optimise(model, args.c_off, args.band_low, args.band_high,
                             args.seeds, args.maxiter, args.popsize,
                             args.min_pf, args.max_pf)
    capacitance = model.capacitances(values, args.c_off)
    order = np.argsort(capacitance)
    inside = (capacitance >= args.band_low) & (capacitance <= args.band_high)

    print(f"\nBest: {count}/60 in band, C_off {args.c_off} pF")
    print("Capacitor values (pF):", np.round(values, 3).tolist())
    print(f"Range {capacitance.min():.2f}-{capacitance.max():.2f} pF")

    report = {
        "states": model.state_count,
        "c_off_pf": args.c_off,
        "band_pf": [args.band_low, args.band_high],
        "values_pf": [float(value) for value in values],
        "states_in_band": count,
        "minimum_pf": float(capacitance.min()),
        "maximum_pf": float(capacitance.max()),
        "states": [
            {"rank": rank + 1, "state": int(index),
             "capacitance_pf": float(capacitance[index]),
             "in_band": bool(inside[index])}
            for rank, index in enumerate(order)
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
