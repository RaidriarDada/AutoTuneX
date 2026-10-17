# Capacitor array simulator

This folder models a rectangular grid of capacitors and switches. It lets you choose which capacitors connect a source node to one destination node, calculate their equivalent capacitance, and count the distinct valid switch configurations. The model is an ideal capacitor network; it does not include RF losses, switch parasitics, or a physical coil.

## Run the interactive simulator

Use Python 3 with Tkinter available. The tracked scripts use only the Python standard library; no package installation is required. From the repository root, run:

```powershell
python capacitor_array_sim/capacitor_simulator.py
```

In the window:

1. Choose the number of **node rows** and **node columns** (1 to 5 each, with at least two nodes overall). The starting node `S` is at the upper left.
2. Click a switch to include or exclude its capacitor. Click a capacitor symbol to set its value in pF. Each capacitor starts at 1 pF.
3. Select a complete route from `S` to an end node using only rightward and downward connections. You may select several such routes if they all end at the **same** node. Every selected capacitor must belong to one of those routes.
4. Click **Run**. The window shows the equivalent capacitance between `S` and the end node, and marks that node `End`. Invalid selections produce an explanation in a dialog.

Changing the grid size resets the switch selections and capacitor values. For a quick check, choose a 2 × 2 node grid and turn on the top horizontal switch and the right vertical switch. With both capacitors at 1 pF, **Run** should show **0.5 pF**: the two capacitors are in series.

## How the model works

An `m × n` grid has `m` rows and `n` columns of **nodes**, with one switchable capacitor between each pair of horizontally or vertically adjacent nodes. A selected configuration is a union of one or more complete paths from `(0, 0)` to the same destination. The paths move right or down; no selected capacitor may dangle outside them.

The switch input is a `(2m - 1) × (2n - 1)` matrix of `0` and `1`. Using zero-based indices, horizontal capacitors occupy even-row/odd-column positions and vertical capacitors occupy odd-row/even-column positions. All other positions must be `0`. The GUI builds this matrix for you.

The capacitance solver fixes the source at 1 V and the destination at 0 V. It solves charge balance at each internal node, then calculates the charge drawn from the source. That charge divided by 1 V is the equivalent capacitance, in the same units as the input capacitor values. The GUI uses pF.

## Run the counting examples

From the repository root:

```powershell
python capacitor_array_sim/calc_unique_paths.py
python capacitor_array_sim/brute_force_unique_paths.py
```

These scripts run their built-in example grid sizes. To count another size, call `unique_paths(m, n)` or `count_unique_capacitor_sets(rows, columns)` from the corresponding file. The brute-force method grows exponentially with the number of complete paths, so use it for small grids.
