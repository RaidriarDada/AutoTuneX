"""Draw where C1..C12 sit on the 3 x 3 board.

The capacitor numbers come from the edge order of ``build_graph(3, 3)``, which
is the order every table, plot and lookup file uses.  The drawing puts row 0 at
the top and column 0 on the left, marks the feed node S and the eight nodes
that can be grounded as ``End``.

Run ``python capacitor_array_sim/draw_capacitor_map.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_3x3_model import DemoModel

ASSIGNMENT_NF = (300.0, 247.0, 210.0, 200.0, 194.0, 157.0,
                 147.0, 120.0, 110.0, 100.0, 104.0, 94.0)

INK = "#0f172a"
CAP = "#334155"
FEED = "#2563eb"
END = "#16a34a"
SPAN = 3.0
NODE_RADIUS = 0.20


def coordinates(row, column):
    return column * SPAN, -row * SPAN


def draw_capacitor(axis, start, end):
    (x0, y0), (x1, y1) = start, end
    dx, dy = x1 - x0, y1 - y0
    length = (dx ** 2 + dy ** 2) ** 0.5
    ux, uy = dx / length, dy / length
    px, py = -uy, ux

    gap = 0.16
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    axis.plot([x0, mx - ux * gap], [y0, my - uy * gap], color=CAP, lw=1.6)
    axis.plot([mx + ux * gap, x1], [my + uy * gap, y1], color=CAP, lw=1.6)
    for sign in (-1, 1):
        cx, cy = mx + ux * gap * sign, my + uy * gap * sign
        axis.plot([cx - px * 0.26, cx + px * 0.26],
                  [cy - py * 0.26, cy + py * 0.26], color=INK, lw=2.4)


def main() -> int:
    model = DemoModel()
    figure, axis = plt.subplots(figsize=(11.0, 8.4))
    figure.patch.set_facecolor("white")
    axis.set_facecolor("white")

    for index, edge in enumerate(model.edges):
        start = coordinates(edge.source.row, edge.source.column)
        end = coordinates(edge.target.row, edge.target.column)
        draw_capacitor(axis, start, end)

        mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
        horizontal = start[1] == end[1]
        if horizontal:
            label_x, label_y = mx, my - 0.62
            align = "center"
        else:
            label_x, label_y = mx + 0.44, my
            align = "left"
        axis.text(label_x, label_y + (0.16 if horizontal else 0.10),
                  f"C{index + 1}", ha=align, va="center",
                  fontsize=11, fontweight="bold", color=INK)
        axis.text(label_x, label_y - (0.16 if horizontal else 0.10),
                  f"{ASSIGNMENT_NF[index]:g} nF", ha=align, va="center",
                  fontsize=10, color="#475569")

    for row in range(3):
        for column in range(3):
            x, y = coordinates(row, column)
            if (row, column) == (0, 0):
                colour = FEED
            else:
                colour = INK
            axis.add_patch(Circle((x, y), NODE_RADIUS, facecolor=colour,
                                  edgecolor="white", linewidth=2.0, zorder=5))
    feed_x, feed_y = coordinates(0, 0)
    axis.text(feed_x, feed_y + 0.52, "S", ha="center", va="center",
              fontsize=15, fontweight="bold", color=FEED)
    axis.text(feed_x, feed_y + 0.18, "feed", ha="center", va="bottom",
              fontsize=8.5, color=FEED)

    axis.text(SPAN, -2 * SPAN - 1.15,
              "E1..E8 are the eight end switches: close exactly one to ground "
              "that node",
              ha="center", va="center", fontsize=9, color=END)
    for row in range(3):
        for column in range(3):
            if (row, column) == (0, 0):
                continue
            x, y = coordinates(row, column)
            axis.add_patch(Circle((x, y), 0.40, facecolor="none",
                                  edgecolor=END, linewidth=1.2, alpha=0.55,
                                  zorder=4))
            # E_k is the end switch on node (row, column): 3 * row + column.
            # Offset diagonally so the label never sits on a branch wire.
            axis.text(x + 0.52, y + 0.44, f"E{3 * row + column}",
                      ha="left", va="bottom", fontsize=11, fontweight="bold",
                      color=END, zorder=6)

    for column, name in enumerate(("column 0", "column 1", "column 2")):
        axis.text(column * SPAN, 1.35, name, ha="center", va="center",
                  fontsize=9, color="#94a3b8")
    for row in range(3):
        axis.text(-1.15, -row * SPAN, f"row {row}", ha="center", va="center",
                  fontsize=9, color="#94a3b8", rotation=90)

    axis.set_xlim(-1.6, 2 * SPAN + 1.6)
    axis.set_ylim(-2 * SPAN - 1.6, 1.15)
    axis.set_aspect("equal")
    axis.axis("off")
    figure.subplots_adjust(left=0.02, right=0.98, top=0.82, bottom=0.03)
    figure.suptitle("Where C1 to C12 go on the 3 x 3 board",
                    fontsize=16, fontweight="bold", x=0.02, ha="left", y=0.965)
    figure.text(0.02, 0.925,
                "Numbers follow build_graph(3, 3) edge order, the same order as "
                "every CSV and plot.  One capacitor per branch, "
                "10 / 47 / 100 nF parts.",
                fontsize=9.5, color="#475569")

    output = Path(__file__).with_name("demo_output") / "capacitor_map.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=220, facecolor="white")
    plt.close(figure)

    for index, edge in enumerate(model.edges):
        orientation = ("horizontal" if edge.source.row == edge.target.row
                       else "vertical")
        print(f"C{index + 1:<2}  ({edge.source.row},{edge.source.column})"
              f"-({edge.target.row},{edge.target.column})  "
              f"{orientation:<10} {ASSIGNMENT_NF[index]:g} nF")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
