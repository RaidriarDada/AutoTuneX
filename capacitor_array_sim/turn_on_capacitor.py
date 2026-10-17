##Turn on capacitors using an interleaved grid of edge switches.

##For an m-by-n graph of nodes, the switch grid is (2m-1)-by-(2n-1).
## Horizontal edges occupy even-row/odd-column positions, and vertical edges occupy odd-row/even-column positions. All other positions are 0. 

from build_array import CapacitorEdge, CapacitorGraph, Node


def build_graph(rows, columns):
    graph = CapacitorGraph(rows, columns)
    graph.build_array()
    return graph


def validate_capacitor_array(graph, on_capacitor_array):
    """Return selected edges if the input represents a valid way.

    A valid way is a union of one or more down/right paths from (0, 0)
    to the same destination node. Validation does not change switches.
    """
    if not isinstance(graph, CapacitorGraph):
        raise TypeError("graph must be a CapacitorGraph")

    m, n = graph.rows, graph.columns
    if type(m) is not int or type(n) is not int or m < 1 or n < 1:
        raise ValueError("graph dimensions must be positive integers")

    expected_nodes = {(row, col) for row in range(m) for col in range(n)}
    if set(graph.nodes) != expected_nodes or any(
        not isinstance(node, Node) or (node.row, node.column) != position
        for position, node in graph.nodes.items()
    ):
        raise ValueError("graph must contain every grid node")

    expected_edges = {
        ((row, col), (row + 1, col))
        for row in range(m - 1) for col in range(n)
    } | {
        ((row, col), (row, col + 1))
        for row in range(m) for col in range(n - 1)
    }
    edges_by_slot = {}
    for edge in graph.edges:
        if not isinstance(edge, CapacitorEdge):
            raise ValueError("graph contains an invalid capacitor edge")
        source = (edge.source.row, edge.source.column)
        target = (edge.target.row, edge.target.column)
        if (source, target) not in expected_edges:
            raise ValueError("graph edges must connect adjacent nodes down or right")
        slot = (source[0] + target[0], source[1] + target[1])
        if slot in edges_by_slot:
            raise ValueError("graph contains a duplicate capacitor edge")
        edges_by_slot[slot] = edge
    if len(edges_by_slot) != len(expected_edges):
        raise ValueError("graph must contain every grid capacitor")

    height, width = 2 * m - 1, 2 * n - 1
    if not isinstance(on_capacitor_array, list) or len(on_capacitor_array) != height:
        raise ValueError(f"capacitor array must have {height} rows")

    selected_edges = []
    for row, values in enumerate(on_capacitor_array):
        if not isinstance(values, list) or len(values) != width:
            raise ValueError(f"row {row} must contain {width} values")
        for col, value in enumerate(values):
            if type(value) is not int or value not in (0, 1):
                raise ValueError(f"array[{row}][{col}] must be 0 or 1")
            edge = edges_by_slot.get((row, col))
            if edge is None:
                if value != 0:
                    raise ValueError(f"array[{row}][{col}] is not a capacitor position")
            elif value == 1:
                selected_edges.append(edge)

    if (m, n) == (1, 1):
        return selected_edges
    if not selected_edges:
        raise ValueError("at least one capacitor must be selected")

    outgoing = {node: [] for node in graph.nodes.values()}
    incoming = {node: [] for node in graph.nodes.values()}
    for edge in selected_edges:
        outgoing[edge.source].append(edge.target)
        incoming[edge.target].append(edge.source)

    def reachable(start, adjacency):
        found = {start}
        pending = [start]
        while pending:
            for node in adjacency[pending.pop()]:
                if node not in found:
                    found.add(node)
                    pending.append(node)
        return found

    origin = graph.nodes[(0, 0)]
    from_origin = reachable(origin, outgoing)
    # A union of paths to one end node has exactly one selected sink.
    sinks = {edge.target for edge in selected_edges} - {
        edge.source for edge in selected_edges
    }
    if len(sinks) == 1:
        destination = sinks.pop()
        to_destination = reachable(destination, incoming)
        if destination in from_origin and all(
            edge.source in from_origin and edge.target in to_destination
            for edge in selected_edges
        ):
            return selected_edges

    raise ValueError(
        "selected capacitors must form complete down/right paths "
        "from (0, 0) to the same destination node"
    )


def turn_on_capacitor(graph, on_capacitor_array):
    """Update every switch from a validated array and return the graph."""
    selected = set(validate_capacitor_array(graph, on_capacitor_array))
    for edge in graph.edges:
        edge.switch = edge in selected
    graph.equivalent_capacitance = 0

    return graph

if __name__ == "__main__":
    from calc_equivalent_capacitance import calculate_equivalent_capacitance

    m, n = 3, 3
    capacitor_array = [
        [0, 1, 0, 1, 0],
        [1, 0, 0, 0, 1],
        [0, 1, 0, 1, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0]
    ]

    graph = build_graph(m, n)
    graph = turn_on_capacitor(graph, capacitor_array)
    result = calculate_equivalent_capacitance(graph, (1, 2))
    print(f"Equivalent capacitance: {result}")
