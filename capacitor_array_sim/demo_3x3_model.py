"""Batched capacitance model for the 3 x 3 Fall-term demo array.

The demo uses all eight end switches (one per node except the source), so the
state set is the 60 single-destination path unions of a 3 x 3 grid. Every state
is evaluated with the open-switch capacitance of the relays in place: an open
mesh switch still couples its two nodes through ``C_off`` in series with its
capacitor, and each of the seven unselected end switches shunts its node to
ground through ``C_off``.

The nodal matrix of a state is a linear combination of twelve fixed basis
matrices, so one ``einsum`` assembles all sixty states at once. The result
matches ``calculate_equivalent_capacitance_with_parasitics`` exactly; the fast
path exists because the optimizer calls it tens of thousands of times.
"""

from __future__ import annotations

import numpy as np

from return_architecture import ALL_ENDS, MUX, enumerate_states
from turn_on_capacitor import build_graph

ROWS = 3
COLUMNS = 3
NODE_COUNT = ROWS * COLUMNS
SOURCE = 0
DEFAULT_C_OFF_PF = 0.1
BAND_PF = (150.0, 250.0)
INTERNAL = NODE_COUNT - 1


def demo_states():
    """The 60 valid switch configurations of a 3 x 3 grid with every end node."""
    return enumerate_states(ROWS, COLUMNS, MUX, end_scope=ALL_ENDS)


class DemoModel:
    """Vectorised evaluator for every demo state at once."""

    def __init__(self):
        graph = build_graph(ROWS, COLUMNS)
        self.edges = graph.edges
        self.edge_count = len(self.edges)
        self.states = demo_states()
        self.state_count = len(self.states)

        self.on = np.zeros((self.state_count, self.edge_count), dtype=bool)
        self.end_index = np.zeros(self.state_count, dtype=int)
        for position, state in enumerate(self.states):
            self.end_index[position] = state.end[0] * COLUMNS + state.end[1] - 1
            for index in range(self.edge_count):
                self.on[position, index] = bool(state.mesh_mask >> index & 1)

        # Basis matrices act on nodes 1..8 (the source is eliminated).
        self.basis = np.zeros((self.edge_count, INTERNAL, INTERNAL))
        self.source_basis = np.zeros((self.edge_count, INTERNAL))
        for index, edge in enumerate(self.edges):
            first = edge.source.row * COLUMNS + edge.source.column
            second = edge.target.row * COLUMNS + edge.target.column
            if first == SOURCE:
                self.basis[index, second - 1, second - 1] += 1.0
                self.source_basis[index, second - 1] += 1.0
            elif second == SOURCE:
                self.basis[index, first - 1, first - 1] += 1.0
                self.source_basis[index, first - 1] += 1.0
            else:
                self.basis[index, first - 1, first - 1] += 1.0
                self.basis[index, second - 1, second - 1] += 1.0
                self.basis[index, first - 1, second - 1] -= 1.0
                self.basis[index, second - 1, first - 1] -= 1.0

        self.source_edges = [
            index for index, edge in enumerate(self.edges)
            if (edge.source.row == 0 and edge.source.column == 0)
            or (edge.target.row == 0 and edge.target.column == 0)
        ]

    def effective(self, values, c_off=DEFAULT_C_OFF_PF):
        values = np.asarray(values, dtype=float)
        if values.shape != (self.edge_count,):
            raise ValueError(f"expected {self.edge_count} capacitor values")
        if np.any(values <= 0):
            raise ValueError("capacitor values must be positive")
        series = values * c_off / (values + c_off)
        return np.where(self.on, values[None, :], series[None, :])

    def capacitances(self, values, c_off=DEFAULT_C_OFF_PF):
        """Equivalent capacitance of every state, in the same order as states."""
        effective = self.effective(values, c_off)
        matrices = np.einsum("se,eij->sij", effective, self.basis, optimize=True)
        rhs = effective @ self.source_basis

        # Ground the selected end node: its row becomes V = 0 and the coupling
        # column disappears because V_end is zero.
        diagonal = np.arange(INTERNAL)
        # With C_off = 0 an unused node can float on its own; a 1e-9 pF shunt
        # keeps the matrix solvable without changing the result.
        matrices[:, diagonal, diagonal] += c_off + (1e-9 if c_off == 0 else 0.0)
        rows = np.arange(self.state_count)
        matrices[rows, self.end_index, :] = 0.0
        matrices[rows[:, None], diagonal[None, :], self.end_index[:, None]] = 0.0
        matrices[rows, self.end_index, self.end_index] = 1.0
        rhs[rows, self.end_index] = 0.0

        voltage = np.linalg.solve(matrices, rhs[..., None])[..., 0]

        charge = np.zeros(self.state_count)
        for index in self.source_edges:
            capacitance = effective[:, index]
            first = self.edges[index].source
            second = self.edges[index].target
            other = (second.row * COLUMNS + second.column
                     if first.row == 0 and first.column == 0
                     else first.row * COLUMNS + first.column)
            charge += capacitance * (1.0 - voltage[:, other - 1])
        return charge


def state_bits(model: DemoModel, position: int):
    """Return (mesh_bits, end_bits) as lists of 12 and 8 Booleans."""
    state = model.states[position]
    mesh = [(state.mesh_mask >> index) & 1 for index in range(model.edge_count)]
    end = [0] * (NODE_COUNT - 1)
    end[state.end[0] * COLUMNS + state.end[1] - 1] = 1
    return mesh, end


def band_stats(values, low=BAND_PF[0], high=BAND_PF[1]):
    values = np.asarray(values, dtype=float)
    inside = (values >= low) & (values <= high)
    return inside, int(inside.sum())
