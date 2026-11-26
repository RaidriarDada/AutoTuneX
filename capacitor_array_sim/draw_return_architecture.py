"""Draw the two return architectures for a 3 x 4 node array.

Run with ``python capacitor_array_sim/draw_return_architecture.py``; writes
``figures/return_architecture.png`` and ``.svg`` next to this file. The drawing
needs matplotlib, which only this script uses.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from return_architecture import far_edge_nodes
from turn_on_capacitor import build_graph

ROWS, COLUMNS = 3, 4
WIRE = "#475569"
DARK = "#0f172a"
END_SWITCH = "#16a34a"
RAIL = "#ea580c"
GND = "#94a3b8"
MISSING = "#dc2626"
SOURCE = "#2563eb"


def _frame(p0, p1):
    p0 = np.asarray(p0, float)
    p1 = np.asarray(p1, float)
    direction = p1 - p0
    length = np.linalg.norm(direction)
    unit = direction / length
    normal = np.array([-unit[1], unit[0]])
    return p0, unit, normal, length


def draw_edge(ax, p0, p1, cap=True, switch=True, switch_color=DARK,
              lw=1.5, alpha=1.0):
    """Draw one series capacitor and one series switch between two points."""
    p0, unit, normal, length = _frame(p0, p1)

    def at(t):
        return p0 + unit * t * length

    def wire(a, b, **kwargs):
        ax.plot([a[0], b[0]], [a[1], b[1]], color=WIRE, lw=lw, alpha=alpha,
                solid_capstyle="round", zorder=3, **kwargs)

    if cap:
        wire(at(0.0), at(0.26))
        for t in (0.30, 0.36):
            centre = at(t)
            ax.plot([centre[0] - normal[0] * 0.12, centre[0] + normal[0] * 0.12],
                    [centre[1] - normal[1] * 0.12, centre[1] + normal[1] * 0.12],
                    color=DARK, lw=2.2, alpha=alpha, solid_capstyle="round")
        wire(at(0.40), at(0.58))
    else:
        wire(at(0.0), at(0.58))

    if switch:
        contact_a, contact_b = at(0.58), at(0.73)
        ax.plot([contact_a[0], contact_b[0]], [contact_a[1], contact_b[1]],
                "o", ms=2.4, color=switch_color, alpha=alpha, zorder=4)
        lever = contact_b + normal * 0.11
        ax.plot([contact_a[0], lever[0]], [contact_a[1], lever[1]],
                color=switch_color, lw=2.0, alpha=alpha, solid_capstyle="round",
                zorder=4)
        wire(at(0.75), at(1.0))
    else:
        wire(at(0.58), at(1.0))


def draw_ground(ax, point, size=0.16, color=DARK):
    x, y = point
    for index, scale in enumerate((1.0, 0.66, 0.33)):
        ax.plot([x - size * scale, x + size * scale],
                [y - index * size * 0.42, y - index * size * 0.42],
                color=color, lw=2.0, solid_capstyle="round")


def node_xy(row, column):
    return column, -row


def draw_mesh(ax, skip_slots=(), mute=False):
    for edge in build_graph(ROWS, COLUMNS).edges:
        slot = (edge.source.row + edge.target.row,
                edge.source.column + edge.target.column)
        if slot in skip_slots:
            continue
        draw_edge(ax, node_xy(edge.source.row, edge.source.column),
                  node_xy(edge.target.row, edge.target.column),
                  alpha=0.30 if mute else 1.0)


def draw_nodes(ax):
    for row in range(ROWS):
        for column in range(COLUMNS):
            x, y = node_xy(row, column)
            ax.plot([x], [y], "o", ms=7, color="#1e293b", zorder=5,
                    markeredgecolor="white", markeredgewidth=1.0)


def draw_source(ax):
    x, y = node_xy(0, 0)
    ax.plot([x], [y], "o", ms=13, color=SOURCE, zorder=6,
            markeredgecolor="white", markeredgewidth=1.2)
    ax.annotate("S\n(from coil)", xy=(x, y), xytext=(x - 1.32, y - 0.62),
                fontsize=9, color=SOURCE, fontweight="bold", ha="left",
                va="center",
                arrowprops=dict(arrowstyle="-|>", color=SOURCE, lw=1.2,
                                shrinkA=0, shrinkB=6))


def finish(ax, title, caption):
    ax.set_xlim(-1.45, 4.75)
    ax.set_ylim(-3.95, 0.45)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", pad=10)
    ax.text(0.0, -0.015, caption, transform=ax.transAxes, fontsize=9.5,
            color="#475569", va="top", ha="left", linespacing=1.55)


def panel_mux(ax):
    draw_mesh(ax)
    draw_nodes(ax)

    plane_y, plane_x = -3.02, 4.02
    ax.plot([-0.45, plane_x], [plane_y, plane_y], color=GND, lw=6,
            solid_capstyle="butt", zorder=1)
    ax.plot([plane_x, plane_x], [0.30, plane_y], color=GND, lw=6,
            solid_capstyle="butt", zorder=1)
    ax.text(plane_x - 0.05, plane_y - 0.20, "GND plane (layer 2)",
            fontsize=8.5, color="#64748b", ha="right", va="top")

    for row, column in sorted(far_edge_nodes(ROWS, COLUMNS)):
        if row == ROWS - 1:
            draw_edge(ax, node_xy(row, column), (column, plane_y),
                      cap=False, switch_color=END_SWITCH, lw=1.4)
        else:
            draw_edge(ax, node_xy(row, column), (plane_x, -row),
                      cap=False, switch_color=END_SWITCH, lw=1.4)

    draw_source(ax)
    finish(ax,
           "A. One-hot end mux:  17 mesh + 6 end = 23 switches",
           "Every far-edge node owns a switch to the plane. A one-hot decoder closes exactly one,\n"
           "so the mesh always sees a single sink and every path ends at the same node.\n"
           "All 17 capacitors stay fitted.")


def panel_rail(ax):
    rail_y, rail_x = -2.55, 3.55
    far = set(far_edge_nodes(ROWS, COLUMNS))
    skipped = set()
    for (row, column) in far:
        for neighbour in ((row + 1, column), (row, column + 1)):
            if neighbour in far:
                skipped.add((row + neighbour[0], column + neighbour[1]))

    draw_mesh(ax, skip_slots=skipped, mute=True)
    draw_nodes(ax)

    ax.plot([-0.45, rail_x], [rail_y, rail_y], color=RAIL, lw=4.5,
            solid_capstyle="round", zorder=2)
    ax.plot([rail_x, rail_x], [0.30, rail_y], color=RAIL, lw=4.5,
            solid_capstyle="round", zorder=2)
    ax.text(-0.40, rail_y - 0.20, "common return rail", fontsize=8.5,
            color=RAIL, ha="left", va="top")

    for row, column in sorted(far):
        if row == ROWS - 1:
            draw_edge(ax, node_xy(row, column), (column, rail_y), cap=False,
                      switch=False, lw=1.4)
        else:
            draw_edge(ax, node_xy(row, column), (rail_x, -row), cap=False,
                      switch=False, lw=1.4)

    master_x = 1.35
    draw_edge(ax, (master_x, rail_y), (master_x, -3.28), cap=False, lw=1.6)
    draw_ground(ax, (master_x, -3.34), size=0.19)
    ax.annotate("1 master return switch", xy=(master_x, -2.98),
                xytext=(master_x + 0.25, -3.05), fontsize=8.6, color=DARK,
                va="center",
                arrowprops=dict(arrowstyle="-", color=DARK, lw=0.9))

    for edge in build_graph(ROWS, COLUMNS).edges:
        slot = (edge.source.row + edge.target.row,
                edge.source.column + edge.target.column)
        if slot not in skipped:
            continue
        x0, y0 = node_xy(edge.source.row, edge.source.column)
        x1, y1 = node_xy(edge.target.row, edge.target.column)
        x, y = (x0 + x1) / 2, (y0 + y1) / 2
        ax.plot([x - 0.075, x + 0.075], [y - 0.075, y + 0.075], color=MISSING,
                lw=2.0, zorder=6)
        ax.plot([x - 0.075, x + 0.075], [y + 0.075, y - 0.075], color=MISSING,
                lw=2.0, zorder=6)

    draw_source(ax)
    finish(ax,
           "B. Common rail (comparison only):  12 mesh + 1 master = 13 switches",
           "All far-edge nodes share one rail; a single switch returns it to ground. The 5 capacitors\n"
           "between two rail nodes (x) are shorted and not fitted. Paths may end on any rail node,\n"
           "so branches of different length end up in parallel; this violates the equal-length rule.")


def main():
    figure, (left, right) = plt.subplots(1, 2, figsize=(15.5, 7.8))
    figure.patch.set_facecolor("white")
    panel_mux(left)
    panel_rail(right)
    figure.subplots_adjust(left=0.02, right=0.98, top=0.82, bottom=0.16,
                           wspace=0.05)
    figure.text(0.02, 0.955,
                "Return path of a 3 x 4 switched-capacitor array: two ways to close "
                "the circuit at the far edge",
                fontsize=12, color="#1e293b", fontweight="bold")
    figure.text(0.02, 0.925,
                "Each mesh edge is one capacitor in series with one PIN switch. "
                "The mesh is identical in both panels; only the return differs.",
                fontsize=9.5, color="#64748b")

    output = Path(__file__).resolve().parent / "figures"
    output.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "svg"):
        path = output / f"return_architecture.{extension}"
        figure.savefig(path, dpi=220, facecolor="white")
        print(path)
    plt.close(figure)


if __name__ == "__main__":
    main()
