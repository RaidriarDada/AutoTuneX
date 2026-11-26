"""PPI GMC C0G catalogue and at-most-three-part parallel approximations.

Values are the nominal C0G codes printed in the GMC series brochure
(PPIGMCNP0DATASHEET083021RevA). Parts below 1 nF are taken from the 0603
GMC10 table, parts from 1 nF up from the 2225 GMC57 table, which is the
larger case size used for the bulk capacitance.
"""

from __future__ import annotations

from bisect import bisect_left
from itertools import combinations_with_replacement

GMC10_PF = (
    0.5, 1.0, 1.2, 1.3, 1.5, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9,
    4.0, 4.3, 4.7, 5.0, 5.1, 5.6, 6.0, 6.2, 6.8, 7.0, 7.5, 8.0, 8.2, 9.0,
    9.1, 10, 11, 12, 13, 15, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47,
    51, 56, 62, 68, 75, 82, 91, 100, 120, 130, 150, 160, 180, 200, 220,
    240, 270, 300, 330, 390, 430, 470, 510, 560, 680, 750, 820, 910,
)
GMC57_PF = (
    1000, 1200, 1500, 1800, 2200, 2400, 2700, 3300, 3900, 4700, 5600,
    6800, 8200, 10000,
)
GMC21_PF = (
    0.5, 1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3,
    3.6, 3.9, 4.0, 4.3, 4.7, 5.0, 5.1, 5.6, 6.0, 6.2, 6.8, 7.0, 7.5, 8.0,
    8.2, 9.0, 9.1, 10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36,
    39, 43, 47, 51, 56, 62, 68, 75, 82, 91, 100, 120, 130, 150, 160, 180,
    200, 220, 240, 270, 300, 330, 360, 390, 430, 470, 510, 560, 620, 680,
    750, 820, 910, 1000, 1200, 1500, 1800, 2200, 2400, 2700, 3300, 3900,
    4700, 5600, 6800, 8200, 10000,
)


def value_code(pf: float) -> str:
    """Three-character capacitance code, e.g. 470 pF -> 471, 1 nF -> 102."""
    if pf < 10:
        return f"{pf:g}".replace(".", "R")
    value = float(pf)
    multiplier = 0
    while value >= 100:
        value /= 10
        multiplier += 1
    digits = int(round(value))
    if digits == 100:
        digits, multiplier = 10, multiplier + 1
    return f"{digits}{multiplier}"


class Part:
    __slots__ = ("value_pf", "series", "case", "number")

    def __init__(self, value_pf: float, series: str, case: str):
        self.value_pf = float(value_pf)
        self.series = series
        self.case = case
        self.number = f"{series}-{value_code(value_pf)}"

    def __repr__(self) -> str:
        return f"Part({self.number}, {self.value_pf:g} pF, {self.case})"


def catalogue(case: str = "mixed") -> list[Part]:
    """PPI GMC C0G parts.

    ``mixed`` uses 0603 below 1 nF and 2225 from 1 nF up. ``0805`` uses the
    0805 GMC21 table for every value, which is much easier to hand-solder.
    """
    if case == "0805":
        return [Part(value, "PPI-GMC21", "0805") for value in GMC21_PF]
    parts = [Part(value, "PPI-GMC10", "0603") for value in GMC10_PF]
    parts += [Part(value, "PPI-GMC57", "2225") for value in GMC57_PF]
    return parts


class Combos:
    """Nearest parallel combinations of at most three catalogue parts."""

    def __init__(self, parts=None):
        self.parts = parts or catalogue()
        self.values = sorted({part.value_pf for part in self.parts})
        self.by_value = {}
        for part in self.parts:
            self.by_value.setdefault(part.value_pf, part)
        self.pairs = [
            (first + second, (first, second))
            for first, second in combinations_with_replacement(self.values, 2)
        ]
        self.pairs.sort()

    def nearest(self, target: float, count: int = 8):
        """Return the closest combinations as (error, part list) pairs."""
        candidates = {}

        def remember(parts):
            total = sum(self.by_value[value].value_pf for value in parts)
            key = tuple(sorted(parts))
            if key in candidates:
                return
            candidates[key] = abs(total - target)

        index = bisect_left(self.values, target)
        for offset in range(-2, 3):
            position = index + offset
            if 0 <= position < len(self.values):
                remember((self.values[position],))

        pair_values = [sum_ for sum_, _ in self.pairs]
        pair_index = bisect_left(pair_values, target)
        for offset in range(-4, 5):
            position = pair_index + offset
            if 0 <= position < len(self.pairs):
                remember(self.pairs[position][1])

        for total, pair in self.pairs:
            remainder = target - total
            if remainder < pair[-1]:
                continue
            third = bisect_left(self.values, remainder)
            for offset in (-1, 0, 1):
                position = third + offset
                if 0 <= position < len(self.values):
                    value = self.values[position]
                    if value >= pair[-1]:
                        remember(pair + (value,))

        ranked = sorted(
            ((error, tuple(self.by_value[value] for value in values))
             for values, error in candidates.items()),
            key=_rank_key,
        )
        return ranked[:count]


def _rank_key(item):
    """Prefer fewer parts once a combination is already within 0.2 pF."""
    error, parts = item
    if error <= 0.2:
        return (0, len(parts), error)
    return (1, error, len(parts))


def total_pf(parts) -> float:
    return sum(part.value_pf for part in parts)
