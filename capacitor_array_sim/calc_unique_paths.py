## Given an m by n grid, count ways to turn on capacitors from (0, 0) to any node.
## Rules: 
## 1. You can only move either down or right at any point in time.
## 2. The grid is of size m x n.
## 3. The starting point is always the top-left corner (0,0).
## 4. The destination can be any node of the grid.
## 5. A "Unique Way" can combine multiple paths. But each path is unique (at least one traversed edge should be different). And they should have the same lengths as the shortest possible path (rule 1 already ensures this).
## 6. A "Unique Way" should have a unique set of capacitors that are turned on. If one combination of paths turns on the same capacitors as another, it is not considered unique.

from collections import defaultdict


def _count_networks_to(rows, columns):
    """Count edge sets that are unions of paths to the bottom-right node.

    Scan the target's rectangle row by row. The frontier records selected
    edges entering from above and from the left. In a right/down DAG, each
    used internal node must have an incoming and an outgoing selected edge;
    these local conditions ensure every selected edge belongs to a complete
    path from the source to the target.
    """
    incoming_rows = {0: 1}
    for row in range(rows):
        next_rows = defaultdict(int)
        for above_mask, count in incoming_rows.items():
            # State: (selected downward edges so far, edge from the left).
            frontier = {(0, 0): count}
            for column in range(columns):
                following = defaultdict(int)
                for (down_mask, from_left), ways in frontier.items():
                    has_incoming = bool(from_left or (above_mask & (1 << column)))
                    is_start = row == column == 0
                    is_end = row == rows - 1 and column == columns - 1
                    if is_end:
                        choices = (0,) if has_incoming else ()
                    elif is_start or has_incoming:
                        choices = (1, 2, 3)  # Right, down, or both.
                    else:
                        choices = (0,)

                    for choice in choices:
                        right = choice & 1
                        down = (choice >> 1) & 1
                        if right and column == columns - 1:
                            continue
                        if down and row == rows - 1:
                            continue
                        following[(down_mask | (down << column), right)] += ways
                frontier = following
            for (down_mask, from_left), ways in frontier.items():
                if not from_left:
                    next_rows[down_mask] += ways
        incoming_rows = next_rows
    return incoming_rows.get(0, 0)

def unique_paths(m: int, n: int) -> int:
    """Count distinct capacitor sets formed by paths to any end node.

    A way may contain any nonempty combination of paths to the same node.
    Different end nodes yield different edge sets because each valid set has
    exactly one sink. For a single-node grid, the empty path counts as one way.
    """
    if type(m) is not int or type(n) is not int or m < 1 or n < 1:
        raise ValueError("m and n must be positive integers")
    if m == n == 1:
        return 1
    return sum(
        _count_networks_to(row + 1, column + 1)
        for row in range(m)
        for column in range(n)
        if (row, column) != (0, 0)
    )

if __name__ == "__main__":
    m, n = 3, 4
    print(f"Number of unique ways to turn on capacitors in a {m}x{n} grid: {unique_paths(m, n)}")
