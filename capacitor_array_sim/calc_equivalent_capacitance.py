"""Equivalent capacitance of the active graph between a source and grounded nodes."""

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


def _live_network(graph, active, ground_nodes):
    """Split an active network into live capacitors and live nodes.

    The mesh is an undirected capacitor network, so current may flow left or
    up as well as right or down. A capacitor carries current only when both of
    its nodes are connected to the source and to a grounded node through the
    active network. A branch that ends open holds no charge, so it is dropped
    rather than rejected: it cannot change the equivalent capacitance.
    """
    adjacency = {node: [] for node in graph.nodes.values()}
    for edge in active:
        adjacency[edge.source].append(edge.target)
        adjacency[edge.target].append(edge.source)
    start = graph.nodes[(0, 0)]
    from_start = _reachable(start, adjacency)
    to_ground = set()
    for ground in ground_nodes:
        to_ground |= _reachable(ground, adjacency)
    region = from_start & to_ground
    grounded = set(ground_nodes)
    live = [edge for edge in active
            if edge.source in region and edge.target in region
            and not (edge.source in grounded and edge.target in grounded)]
    return live, region


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

    return calculate_equivalent_capacitance_to_grounds(graph, (destination,))


def _validated_grounds(graph, grounds):
    m, n = graph.rows, graph.columns
    start_position = (0, 0)
    if start_position not in graph.nodes:
        raise ValueError("graph must be built before calculating capacitance")
    positions = list(grounds)
    if not positions:
        raise ValueError("at least one grounded node is required")
    for ground in positions:
        if (not isinstance(ground, tuple) or len(ground) != 2
                or any(type(coordinate) is not int for coordinate in ground)):
            raise ValueError("each grounded node must be a (row, column) tuple")
        if ground == start_position or not (
            0 <= ground[0] < m and 0 <= ground[1] < n
        ):
            raise ValueError("a grounded node must be a grid node other than (0, 0)")
        if ground not in graph.nodes:
            raise ValueError("graph must be built before calculating capacitance")
    if len(set(positions)) != len(positions):
        raise ValueError("grounded nodes must be distinct")
    return [graph.nodes[position] for position in positions]


def calculate_equivalent_capacitance_to_grounds(graph: CapacitorGraph, grounds,
                                                strict: bool = True) -> float:
    """Calculate capacitance from (0, 0) to one or more grounded nodes.

    The source is held at 1 V and every grounded node at 0 V, so the charge
    drawn from the source is the equivalent capacitance. With several grounded
    nodes the network may have any number of parallel paths.

    With ``strict`` every active capacitor must lie on a path to a grounded
    node, which is the rule a path-union state obeys. Without it, an active
    capacitor that ends open is ignored; it carries no current and cannot
    change the result, but it must not reject an otherwise valid state.
    """
    if not isinstance(graph, CapacitorGraph):
        raise TypeError("graph must be a CapacitorGraph")
    m, n = graph.rows, graph.columns
    if type(m) is not int or type(n) is not int or m < 1 or n < 1:
        raise ValueError("graph dimensions must be positive integers")

    end_nodes = _validated_grounds(graph, grounds)
    active = [edge for edge in graph.edges if edge.switch]
    if not active:
        raise ValueError("no capacitors are turned on")

    outgoing = {node: [] for node in graph.nodes.values()}
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
        except KeyError as error:
            raise ValueError("active capacitor refers to a node outside the graph") from error

    live, region = _live_network(graph, active, end_nodes)
    if strict and len(live) != len(active):
        raise ValueError("active capacitors must form paths to a grounded node")
    if not live:
        raise ValueError("active capacitors must form paths to a grounded node")

    start = graph.nodes[(0, 0)]
    grounded = set(end_nodes)
    internal = sorted(
        (node for node in region if node != start and node not in grounded),
        key=lambda node: (node.row, node.column),
    )
    index = {node: position for position, node in enumerate(internal)}
    matrix = [[0.0] * len(internal) for _ in internal]
    rhs = [0.0] * len(internal)

    # At every initially uncharged internal node i:
    #     sum(C_ij * (V_i - V_j)) = 0.
    for edge in live:
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
                rhs[row] += capacitance  # V_start = 1; grounded nodes are 0 V.

    solved = _solve(matrix, rhs)
    voltage = {start: 1.0}
    for node in grounded:
        voltage[node] = 0.0
    voltage.update(zip(internal, solved))

    # Q_start / 1 volt is the equivalent capacitance.
    equivalent = math.fsum(
        capacitances[edge] * (1.0 - voltage[edge.get_other_node(start)])
        for edge in live
        if edge.source == start or edge.target == start
    )
    graph.equivalent_capacitance = equivalent
    return equivalent


def conducting_edges(graph: CapacitorGraph, grounds) -> list:
    """Return the active capacitors that carry current to a grounded node."""
    if not isinstance(graph, CapacitorGraph):
        raise TypeError("graph must be a CapacitorGraph")
    end_nodes = _validated_grounds(graph, grounds)
    active = [edge for edge in graph.edges if edge.switch]
    live, _ = _live_network(graph, active, end_nodes)
    return live


def calculate_equivalent_capacitance_with_parasitics(graph: CapacitorGraph, grounds,
                                                     off_capacitance: float = 0.0,
                                                     shunts=None) -> float:
    """Equivalent capacitance including the off capacitance of every open switch.

    An open switch is not an ideal break: it is ``off_capacitance`` in series
    with its capacitor, so the branch still couples its two nodes weakly. A
    capacitor with value ``0`` is treated as not fitted. ``shunts`` maps a grid
    position to a capacitance to ground, which models an open return switch
    sitting between that node and the ground plane.

    The whole mesh conducts once ``off_capacitance`` is positive, so this
    solver does not reduce the network to a path union; it solves every fitted
    branch at once.
    """
    if not isinstance(graph, CapacitorGraph):
        raise TypeError("graph must be a CapacitorGraph")
    m, n = graph.rows, graph.columns
    if type(m) is not int or type(n) is not int or m < 1 or n < 1:
        raise ValueError("graph dimensions must be positive integers")
    if (isinstance(off_capacitance, bool) or not isinstance(off_capacitance, Real)
            or not math.isfinite(off_capacitance) or off_capacitance < 0):
        raise ValueError("off_capacitance must be a nonnegative finite number")

    end_nodes = _validated_grounds(graph, grounds)
    shunt_nodes = {}
    for position, value in (shunts or {}).items():
        if position not in graph.nodes:
            raise ValueError("a shunt refers to a node outside the graph")
        if (isinstance(value, bool) or not isinstance(value, Real)
                or not math.isfinite(value) or value < 0):
            raise ValueError("shunt capacitances must be nonnegative finite numbers")
        if value > 0:
            shunt_nodes[graph.nodes[position]] = float(value)

    start = graph.nodes[(0, 0)]
    grounded = set(end_nodes)
    branches = []
    for edge in graph.edges:
        value = edge.capacitance
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("capacitor values must be nonnegative finite numbers")
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError("capacitor values must be nonnegative finite numbers")
        if value == 0:
            continue
        if edge.switch:
            effective = value
        elif off_capacitance > 0:
            effective = value * off_capacitance / (value + off_capacitance)
        else:
            effective = 0.0
        if effective > 0:
            branches.append((edge.source, edge.target, effective))
    for node, value in shunt_nodes.items():
        branches.append((node, None, value))

    touched = {node for a, b, _ in branches for node in (a, b) if node is not None}
    internal = sorted((node for node in graph.nodes.values()
                       if node != start and node not in grounded and node in touched),
                      key=lambda node: (node.row, node.column))
    index = {node: position for position, node in enumerate(internal)}
    matrix = [[0.0] * len(internal) for _ in internal]
    rhs = [0.0] * len(internal)

    for first, second, capacitance in branches:
        if second is None:
            if first in index:
                matrix[index[first]][index[first]] += capacitance
            continue
        for node, neighbour in ((first, second), (second, first)):
            if node not in index:
                continue
            row = index[node]
            matrix[row][row] += capacitance
            if neighbour in index:
                matrix[row][index[neighbour]] -= capacitance
            elif neighbour == start:
                rhs[row] += capacitance

    solved = _solve(matrix, rhs)
    voltage = {start: 1.0}
    for node in grounded:
        voltage[node] = 0.0
    voltage.update(zip(internal, solved))

    equivalent = 0.0
    for first, second, capacitance in branches:
        if second is None:
            if first == start:
                equivalent += capacitance
        elif first == start:
            equivalent += capacitance * (1.0 - voltage[second])
        elif second == start:
            equivalent += capacitance * (1.0 - voltage[first])
    graph.equivalent_capacitance = equivalent
    return equivalent
