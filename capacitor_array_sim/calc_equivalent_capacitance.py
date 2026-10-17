"""Equivalent capacitance of the active graph between two nodes."""

import math
from numbers import Real

from build_array import CapacitorGraph


def _reachable(start, adjacency):
    found = {start}
    pending = [start]
    while pending:
        for node in adjacency[pending.pop()]:
            if node not in found:
                found.add(node)
                pending.append(node)
    return found


def _solve(matrix, rhs):
    """Solve a small dense linear system using partial pivoting."""
    size = len(rhs)
    coefficients = [row[:] for row in matrix]
    values = rhs[:]

    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(coefficients[row][column]))
        if coefficients[pivot][column] == 0:
            raise ValueError("capacitor network has an unsolvable floating node")
        coefficients[column], coefficients[pivot] = coefficients[pivot], coefficients[column]
        values[column], values[pivot] = values[pivot], values[column]

        for row in range(column + 1, size):
            factor = coefficients[row][column] / coefficients[column][column]
            coefficients[row][column] = 0.0
            for other_column in range(column + 1, size):
                coefficients[row][other_column] -= factor * coefficients[column][other_column]
            values[row] -= factor * values[column]

    solution = [0.0] * size
    for row in range(size - 1, -1, -1):
        remainder = values[row] - math.fsum(
            coefficients[row][column] * solution[column]
            for column in range(row + 1, size)
        )
        solution[row] = remainder / coefficients[row][row]
    return solution


def calculate_equivalent_capacitance(graph: CapacitorGraph, destination: tuple[int, int]) -> float:
    """Calculate capacitance from (0, 0) to a selected end node.

    Active capacitors must be a union of complete down/right paths to
    ``destination``. Each internal node is assumed to have zero initial
    net charge. The result uses the same units as edge.capacitance.
    """
    if not isinstance(graph, CapacitorGraph):
        raise TypeError("graph must be a CapacitorGraph")
    if (not isinstance(destination, tuple) or len(destination) != 2
            or any(type(coordinate) is not int for coordinate in destination)):
        raise ValueError("destination must be a (row, column) tuple")

    m, n = graph.rows, graph.columns
    if type(m) is not int or type(n) is not int or m < 1 or n < 1:
        raise ValueError("graph dimensions must be positive integers")
    start_position = (0, 0)
    if destination == start_position or not (
        0 <= destination[0] < m and 0 <= destination[1] < n
    ):
        raise ValueError("destination must be a grid node other than (0, 0)")
    if start_position not in graph.nodes or destination not in graph.nodes:
        raise ValueError("graph must be built before calculating capacitance")

    active = [edge for edge in graph.edges if edge.switch]
    if not active:
        raise ValueError("no capacitors are turned on")

    outgoing = {node: [] for node in graph.nodes.values()}
    incoming = {node: [] for node in graph.nodes.values()}
    capacitances = {}
    for edge in active:
        value = edge.capacitance
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("active capacitor values must be positive finite numbers")
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("active capacitor values must be positive finite numbers")
        capacitances[edge] = value
        try:
            outgoing[edge.source].append(edge.target)
            incoming[edge.target].append(edge.source)
        except KeyError as error:
            raise ValueError("active capacitor refers to a node outside the graph") from error

    start = graph.nodes[start_position]
    end = graph.nodes[destination]
    from_start = _reachable(start, outgoing)
    to_end = _reachable(end, incoming)
    if end not in from_start or any(
        edge.source not in from_start or edge.target not in to_end
        for edge in active
    ):
        raise ValueError("active capacitors must form paths to destination")

    internal = sorted(
        (node for node in from_start if node != start and node != end),
        key=lambda node: (node.row, node.column),
    )
    index = {node: position for position, node in enumerate(internal)}
    matrix = [[0.0] * len(internal) for _ in internal]
    rhs = [0.0] * len(internal)

    # At every initially uncharged internal node i:
    #     sum(C_ij * (V_i - V_j)) = 0.
    for edge in active:
        capacitance = capacitances[edge]
        for node, neighbor in ((edge.source, edge.target),
                               (edge.target, edge.source)):
            if node not in index:
                continue
            row = index[node]
            matrix[row][row] += capacitance
            if neighbor in index:
                matrix[row][index[neighbor]] -= capacitance
            elif neighbor == start:
                rhs[row] += capacitance  # V_start = 1; V_end = 0.

    solved = _solve(matrix, rhs)
    voltage = {start: 1.0, end: 0.0}
    voltage.update(zip(internal, solved))

    # Q_start / 1 volt is the equivalent capacitance.
    equivalent = math.fsum(
        capacitances[edge] * (1.0 - voltage[edge.get_other_node(start)])
        for edge in active
        if edge.source == start or edge.target == start
    )
    graph.equivalent_capacitance = equivalent
    return equivalent
