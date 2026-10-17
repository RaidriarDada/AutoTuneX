"""Count capacitor sets by enumerating every combination of complete paths.

This is deliberately independent of calc_unique_paths.py. It is practical
for small grids, but the number of path combinations grows exponentially.
"""

from itertools import combinations


def _edge_bits(rows, columns):
    """Assign one bit to each capacitor between adjacent grid nodes."""
    bits = {}
    for row in range(rows):
        for column in range(columns):
            source = (row, column)
            if row + 1 < rows:
                bits[(source, (row + 1, column))] = 1 << len(bits)
            if column + 1 < columns:
                bits[(source, (row, column + 1))] = 1 << len(bits)
    return bits


def _paths_to(destination, edge_bits):
    """List the capacitor masks for every right/down path to destination."""
    paths = []
    end_row, end_column = destination

    def visit(row, column, on_capacitors):
        if (row, column) == destination:
            paths.append(on_capacitors)
            return
        source = (row, column)
        if row < end_row:
            next_node = (row + 1, column)
            visit(*next_node, on_capacitors | edge_bits[(source, next_node)])
        if column < end_column:
            next_node = (row, column + 1)
            visit(*next_node, on_capacitors | edge_bits[(source, next_node)])

    visit(0, 0, 0)
    return paths


def count_unique_capacitor_sets(rows, columns):
    """Return per-destination counts and their sum for an m-by-n node grid."""
    if type(rows) is not int or type(columns) is not int or rows < 1 or columns < 1:
        raise ValueError("rows and columns must be positive integers")

    edge_bits = _edge_bits(rows, columns)
    per_destination = {}
    for row in range(rows):
        for column in range(columns):
            if (row, column) == (0, 0):
                continue

            paths = _paths_to((row, column), edge_bits)
            unique_on_capacitors = set()
            for group_size in range(1, len(paths) + 1):
                for path_group in combinations(paths, group_size):
                    on_capacitors = 0
                    for path in path_group:
                        on_capacitors |= path
                    unique_on_capacitors.add(on_capacitors)

            per_destination[(row, column)] = {
                "paths": len(paths),
                "path_combinations": (1 << len(paths)) - 1,
                "unique_capacitor_sets": len(unique_on_capacitors),
            }

    return per_destination, sum(
        counts["unique_capacitor_sets"] for counts in per_destination.values()
    )


if __name__ == "__main__":
    for grid_rows, grid_columns in ((3, 3), (3, 4), (4, 4)):
        counts, total = count_unique_capacitor_sets(grid_rows, grid_columns)
        print(f"\n{grid_rows} x {grid_columns} nodes")
        for destination, details in counts.items():
            print(
                f"  {destination}: {details['paths']} paths, "
                f"{details['path_combinations']} path combinations, "
                f"{details['unique_capacitor_sets']} unique capacitor sets"
            )
        print(f"  TOTAL: {total}")
