# Capacitor array simulator

This folder models a rectangular grid of capacitors and switches. It lets you choose which capacitors connect a source node to one destination node, calculate their equivalent capacitance, and count the distinct valid switch configurations. The model is an ideal capacitor network; it does not include RF losses, switch parasitics, or a physical coil.

## Run the interactive simulator

Use Python 3 with Tkinter available. The interactive simulator and counting scripts use only the Python standard library; no package installation is required for them. From the repository root, run:

```powershell
python capacitor_array_sim/capacitor_simulator.py
```

In the window:

1. Choose the number of **node rows** and **node columns** (1 to 5 each, with at least two nodes overall). The starting node `S` is at the upper left.
2. Click a switch to include or exclude its capacitor. Click a capacitor symbol to set its value in pF. Each capacitor starts at 1 pF.
3. Select a complete route from `S` to an end node using only rightward and downward connections. You may select several such routes if they all end at the **same** node. Every selected capacitor must belong to one of those routes.
4. Click **Run**. The window shows the equivalent capacitance between `S` and the end node, and marks that node `End`. Invalid selections produce an explanation in a dialog.

The schematic scales and stays centered when you resize the window. Changing the grid size resets the switch selections and capacitor values. For a quick check, choose a 2 × 2 node grid and turn on the top horizontal switch and the right vertical switch. With both capacitors at 1 pF, **Run** should show **0.5 pF**: the two capacitors are in series.

## How the model works

An `m × n` grid has `m` rows and `n` columns of **nodes**, with one switchable capacitor between each pair of horizontally or vertically adjacent nodes. A selected configuration is a union of one or more complete paths from `(0, 0)` to the same destination. The paths move right or down; no selected capacitor may dangle outside them. The single destination is a hardware rule, not only a solver convenience: every path to `(r, c)` has exactly `r + c` edges, so all branches of a configuration keep the same electrical length (see [Choose the return architecture](#choose-the-return-architecture)).

The switch input is a `(2m - 1) × (2n - 1)` matrix of `0` and `1`. Using zero-based indices, horizontal capacitors occupy even-row/odd-column positions and vertical capacitors occupy odd-row/even-column positions. All other positions must be `0`. The GUI builds this matrix for you.

The capacitance solver fixes the source at 1 V and the destination at 0 V. It solves charge balance at each internal node, then calculates the charge drawn from the source. That charge divided by 1 V is the equivalent capacitance, in the same units as the input capacitor values. The GUI uses pF.

## Choose the return architecture

The mesh alone does not define the array's second terminal, and the choice decides whether a switch state behaves like one predictable capacitor at all. The design rule used here is **equal electrical length**: inside one configuration, every conducting branch from `(0, 0)` to the return must have the same number of series elements and the same return path.

The rule is not about propagation delay. At 51.7 MHz the guided wavelength in FR-4 is about 2.8 m, so even a 5 cm board subtends only about 6°. What moves is the *value*. Each capacitor sits in series with roughly 1–2 nH of package and trace inductance, and 450 pF at 51.7 MHz is only 6.8 Ω, so `ω²LC ≈ 0.1` turns `C` into `C / (1 − ω²LC) ≈ 1.1 C`. The common part of that correction is harmless because every state is measured anyway. What is not common is how much inductance a particular branch and its return happen to add: 1–2 nH between a short and a long branch is 3–5 % of the effective value, which is 12–20× the 0.25 % step of a 200 pF design with 0.5 pF spacing. A configuration that puts a two-edge branch in parallel with a four-edge branch is therefore no longer one clean scaled capacitance: its value drifts with the layout, the branches share current unevenly, and the PIN losses differ between them.

In a right/down grid the rule is free inside one configuration. Every monotone path from `(0, 0)` to `(r, c)` has exactly `r + c` edges, so a union of paths to a single destination automatically has equal-length branches. That is why the model requires one destination, and why the PCB must keep every cell at the same pitch: equal edge count only means equal length if the cells are identical.

[`return_architecture.py`](return_architecture.py) implements the two ways of closing the far edge, and [`draw_return_architecture.py`](draw_return_architecture.py) draws them for a 3 × 4 grid into [`figures/return_architecture.png`](figures/return_architecture.png).

- **One-hot end mux (`mux`)** — every node on the last row or last column owns a switch to the ground plane, and a decoder closes exactly one. The mesh therefore always has one sink, the "union of paths to one end node" rule becomes the hardware constraint rather than a modelling convenience, and the return is a single local connection. A 3 × 4 grid uses 17 mesh switches and 6 end switches. **This is the design that is kept.**
- **Common rail (`rail`)** — all far-edge nodes are joined by one rail and a single master switch returns the rail to ground. The five capacitors whose two ends both sit on the rail are short-circuited and are not fitted, which leaves 12 mesh switches and one master switch. Paths may land anywhere on the rail, so a configuration can put paths of different lengths in parallel and return through different lengths of rail. **This violates the equal-length rule and is implemented as a comparison only.**

Counts are structural except the "distinct levels" column, which uses the capacitor values of the 3 × 4 study in `tmp/simulation_3x4_initial.json` and the 3 × 3 study in `tmp/simulation_anchored.json`.

| Architecture | Mesh + end + master | Total | Equal length | Configurations, 3 × 4 / 3 × 3 | Distinct levels, 3 × 4 / 3 × 3 |
| --- | --- | --- | --- | --- | --- |
| `mux`, far edge only | 17 + 6 + 0 | 23 | yes | 270 / 55 | 270 / 55 |
| `mux`, every end node | 17 + 11 + 0 | 28 | yes | 283 / 60 | 283 / 60 |
| `rail` + master switch | 12 + 0 + 1 | 13 | **no** | 1001 / 94 | 442 / 58 |

A *configuration* is a switch pattern in which every closed capacitor carries current. A *level* is a distinct equivalent capacitance; with the near-uniform 3 × 4 values many configurations coincide, which is why the rail has 1001 configurations but 442 levels. The one-hot mux reaches every configuration with a distinct value.

```powershell
python capacitor_array_sim/return_architecture.py --rows 3 --columns 4
python capacitor_array_sim/return_architecture.py --rows 3 --columns 4 --capacitors tmp/simulation_3x4_initial.json --output tmp/return_architecture_3x4.json
python capacitor_array_sim/draw_return_architecture.py
```

`--cap-pf` sets a uniform capacitor value; `--capacitors` reads the `slot_order` and `capacitors_pf` fields of a study JSON such as the ones written by the optimizer. `--band-low` and `--band-high` set the target band (default 150–250 pF).

Points that the table does not show:

- The rail is cheaper and reaches a larger state space — 10 fewer switches, about 10 fewer bias lines, and 442 levels against 270 — precisely *because* it puts branches of different lengths in parallel. That is the property the equal-length rule forbids, so the extra levels are not usable under the current design rule. The rail stays in the module to keep the trade-off measurable.
- The far-edge mux drops 13 of the 283 configurations and 5 end switches compared with an end switch on every node, and the largest in-band gap stays at 4.01 pF, so there is no reason to switch every node.
- An unselected end switch is not an ideal open. `--c-off` models its shunt and the series off capacitance of every mesh switch; see [Open-switch capacitance](#open-switch-capacitance).
- The sink moves between states even in the mux, so the absolute capacitance of a state is not exactly predictable from the ideal model. Every state is measured, which covers that; a model-guided search would need the parasitic model first.
- The mesh is undirected. A rail comparison state may route current back up or left through a capacitor, so the rail solver ignores capacitors on an open-ended branch instead of rejecting the state. The mux states keep the stricter path-union rule because there the paths are what defines the state.
- The drawing script is the only file here that needs matplotlib; the module and its tests use the standard library.

## Open-switch capacitance

An open PIN switch is not an open circuit. `--c-off` puts `C_off` in series with the capacitor of every open mesh switch, and shunts every end switch that is not selected to the ground plane through `C_off`. The set of switch states does not change; only the capacitance of each state moves.

```powershell
python capacitor_array_sim/return_architecture.py --rows 3 --columns 4 --capacitors tmp/simulation_3x4_initial.json --c-off 0.7
```

For a 3 × 4 grid with the current capacitor values and `C_off = 0.7 pF` (MA4P7470-class at high reverse bias):

| Variant | End switches | States | In band | Mean shift | Max shift | Max relative | Max shift / median step |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `mux`, far edge | 6 | 270 | 191 → 194 | +0.70 pF | +1.17 pF | 0.92 % | 3.1 |
| `mux`, every end | 11 | 283 | 199 → 203 | +1.98 pF | +3.16 pF | 2.50 % | 8.3 |
| `rail` (comparison) | 0 | 1001 | 384 → 386 | +0.81 pF | +3.13 pF | 2.03 % | 6.0 |

- Every state moves up: adding capacitance to a passive network can only raise the driving-point value.
- The far-edge design leaves 5 end switches open at any time, the every-end design leaves 10. That is 3.5 pF against 7 pF of shunt spread over the mesh, which is why the every-end shift is roughly 2.7× larger. It is a second reason, besides the 5 saved switches, to put end switches on the far edge only.
- The spacing survives. On the far-edge design the median gap moves 0.38 → 0.37 pF and the largest gap 26.35 → 26.31 pF, so `C_off` behaves as a near-constant offset that can be calibrated out. The absolute table is still wrong by up to 3 median steps, which is why every state is measured rather than predicted.
- On the rail, the 442 levels were partly exact coincidences of the near-uniform capacitor values. With `C_off` all 1001 configurations separate, and hundreds of them land within hundredths of a pF of each other (median gap 0.52 → 0.11 pF). The apparent density of the rail was an artefact of ideal values, not a property that survives a real build.

## Optimize the 3 × 3 array

[`optimize_3x3.py`](optimize_3x3.py) searches for twelve capacitor values that make the **60 valid configurations** as evenly spaced as possible. Each configuration may end at a different terminal node. The search starts with 12, 11, …, 1 pF assigned left to right and top to bottom across the capacitor positions:

| Grid position | Starting values (pF) |
| --- | --- |
| Top horizontal | `c_12 = 12`, `c_11 = 11` |
| Upper vertical | `c_10 = 10`, `c_9 = 9`, `c_8 = 8` |
| Middle horizontal | `c_7 = 7`, `c_6 = 6` |
| Lower vertical | `c_5 = 5`, `c_4 = 4`, `c_3 = 3` |
| Bottom horizontal | `c_2 = 2`, `c_1 = 1` |

The names identify **positions** during optimization: `c_12` is initially 12 pF but may end at another value. The order is a starting guess, not a constraint. All twelve values can change independently.

The optimizer needs Python 3.10 or newer and SciPy. From the repository root:

```powershell
python -m pip install scipy
python capacitor_array_sim/optimize_3x3.py --output tmp/optimized_3x3.json
```

For every candidate, the script uses the existing network solver to calculate and sort all 60 equivalent capacitances. It scores the standard deviation of the 59 adjacent gaps **relative to their mean**, plus a small penalty for the largest gap. A bounded Powell search starts at the descending layout and repeats from seeded perturbations. By default, each capacitor may vary from **0.5 to 15 pF**, while the output span must remain at least as wide as the starting layout's span (about **11.444 pF**). These bounds are exploratory, not a selected parts list.

The command prints the starting and best range, gap statistics, and the twelve proposed values. `--output` optionally saves those results and the sorted 60-state list as JSON, including each state's terminal node and active capacitors. Use `--min-cap-pf`, `--max-cap-pf`, `--min-span-pf`, `--worst-gap-weight`, `--restarts`, `--maxfev`, and `--seed` to change the search. The component bounds must include the 1–12 pF starting values. Results are approximate local-search solutions; they do not establish a global optimum or account for capacitor tolerances and RF parasitics.

## Fall-term demo at 15–30 kHz

The Winter-term target is 51.705 MHz, where the array has to resolve 0.5 pF steps inside 200 pF. The Fall-term deliverable is only to show that the array **produces different capacitances and can be tuned**, and the measurement band for that is 15–30 kHz. [`demo_3x3_lowfreq.py`](demo_3x3_lowfreq.py) re-scales the same 60-state, all-end design onto an audio-frequency LC tank.

### Why the capacitor values change, and why the kit is enough

Resonance only cares about the product `L · C_eq`, so a design is fixed by the **ratios** of the twelve branch capacitors plus one overall scale. Dropping from 51.705 MHz to 15 kHz at a fixed inductor would need 1.19 × 10⁷ times more capacitance — which is why 200 pF is hopeless and 22 nF is not. Splitting the change between the two elements gives an ordinary choke instead of an absurd one: 110× more capacitance (200 pF → 22 nF) and 1.1 × 10⁵ more inductance (a few hundred nanohenries → 4.7 mH). This section treats the inductor as a **stand-in**; the real loop is 284 nH and is analysed in [Fall demo on the real surface coil](#fall-demo-on-the-real-surface-coil).

The kit's 100 nF ceiling is therefore not a limit. The capacitance window that a given choke needs is:

| Inductance | Capacitance window for 15–30 kHz | Uniform branch value that fills it |
| --- | --- | --- |
| 0.47 mH | 60 – 240 nF | 240 nF (needs two 100 nF) |
| 1 mH | 28 – 113 nF | 113 nF |
| 2.2 mH | 12.8 – 51 nF | 51 nF |
| **4.7 mH** | **6.0 – 24 nF** | **24 nF** |
| 10 mH | 2.8 – 11.3 nF | 11.3 nF |
| 22 mH | 1.3 – 5.1 nF | 5.1 nF |
| 47 mH | 0.6 – 2.4 nF | 2.4 nF |

Every row is inside the 0.1 nF–100 nF kit (twice the largest part is still reachable). The study defaults to **4.7 mH**, which is a standard choke value and keeps the branches in the tens of nanofarads.

### Why the factor of four matters

With every branch equal to `C`, a one-edge path from the source gives `C_eq = C` and a four-edge path gives `C_eq = C/4`: the 60 states span **exactly 4×**, and 15 kHz → 30 kHz is **exactly 4×** too. The topology's natural span and the target band have the same width, so the design problem is not "how wide a range" but "how evenly 60 states fill that range".

That gives two builds out of one kit.

**Uniform build.** Twelve 22 nF parts, one part number. The 60 states collapse to **12 distinct resonances** from 15.65 to 31.30 kHz. This is the cheapest possible proof of tunability and needs no matching at all.

**Tuned build.** Branch values optimised so all **60 states are distinct and inside 15–30 kHz**:

| Quantity | Value |
| --- | --- |
| States in band | 60 / 60 |
| Frequency sweep | 15.03 – 30.00 kHz |
| Distinct capacitance levels | 60 / 60 |
| Median step | 0.18 kHz |
| Largest step | 1.02 kHz |
| Capacitors | 24, from 14 kit values, at most 2 in parallel |
| Largest branch | 168 nF (68 nF + 100 nF) |

The kit ships 30 of each value, and the design uses at most 4, so no value has to be bought separately.

Both builds are written next to the optimisation: `lowfreq_capacitors.csv`, `lowfreq_bom.csv`, `lowfreq_lookup.csv` (the 20 switch bits per state), `lowfreq_uniform.csv` (the 12 levels of the one-part build), `lowfreq_design.json` and `lowfreq_states.png`.

### Tolerances

The kit parts are unmarked-dielectric, ±10 % or worse, and the measured values will differ from nominal. A Monte Carlo over 400 draws keeps the design usable:

| Branch tolerance | States in band (mean) | Worst case | Full sweep |
| --- | --- | --- | --- |
| ±1 % | 59.2 | 58 | 14.9 – 30.3 kHz |
| ±5 % | 58.6 | 55 | 14.0 – 31.2 kHz |
| ±10 % | 58.0 | 54 | 13.5 – 32.7 kHz |
| ±20 % | 56.6 | 46 | 12.7 – 38.0 kHz |

The levels stay distinct because a common scaling moves every state together; only the absolute band shifts. The Fall demo is therefore safe, unlike the 51.705 MHz build where every state has to be measured.

### Measuring it

`L = 4.7 mH` with 22 nF gives `Q = √(L/C) / R`. A choke with 15 Ω of series resistance gives `Q ≈ 31`, so the −3 dB width is about 0.6 kHz at 20 kHz. The median 0.18 kHz step is finer than that linewidth, so neighbouring states blur into each other; the 1 kHz gaps are resolved. Drive the tank from a signal generator through a 1 kΩ resistor and watch the voltage across the inductor, or use a DDS module and a peak detector. A 48 kHz sound card only reaches 24 kHz, so use a bench generator (or `--band-high 20`) if the measurement chain is a sound card.

## Fall demo on the real surface coil

The 15–30 kHz study above models the array against a **stand-in inductor**. The real Fall demo has to use the actual probe: a single-turn ³¹P surface loop with six series breaks `CS1…CS6` and a parallel matching capacitor `Cp` across the coax feed (parallel-series circuit, two resonances). [`demo_surface_coil.py`](demo_surface_coil.py) puts the array into that circuit.

### The loop is 284 nH, and the Winter tuning proves it

The Winter coil is tuned with 200 pF at every break, so the series capacitance is `200/6 = 33.33 pF`. Resonating that at 51.705 MHz needs

```
L = 1 / (2 pi f)^2 C = 284 nH
```

which is exactly what a 14 cm single-turn loop of 6 mm copper measures. The script reproduces 51.705 MHz from those numbers, so the inductance is derived rather than guessed.

### What the kit's largest capacitor gives

With every array branch at **100 nF** (the kit maximum), all six loop breaks shorted so the array is the whole tuning capacitance:

| Branch value | C_eq (60 states) | Series resonance | Anti-resonance with Cp = 100 nF | Q, 0.3 Ω in the loop |
| --- | --- | --- | --- | --- |
| 100 nF (one part) | 25 – 100 nF | **944 kHz – 1.888 MHz** | 1.34 – 2.11 MHz | 5.6 – 11.2 |
| 200 nF (two in parallel) | 50 – 200 nF | **668 kHz – 1.335 MHz** | 1.16 – 1.64 MHz | 4.0 – 7.9 |

The 60 states still collapse to 12 distinct levels, but the array is clearly tunable: a factor of two in frequency for one part per branch.

### 15–30 kHz is unreachable on this coil

`f = 1/(2 pi sqrt(LC))` with `L = 284 nH` and at most 200 nF gives a floor of **668 kHz**, 22× above 30 kHz. To sit at 15–30 kHz the tank needs:

| Frequency | With 100 nF | With 200 nF |
| --- | --- | --- |
| 15 kHz | 1.126 mH (3961 × this coil, 63 turns) | 0.563 mH (1980 ×, 45 turns) |
| 30 kHz | 0.281 mH (990 ×, 31 turns) | 0.141 mH (495 ×, 22 turns) |

So the choice is between a **22–63 turn loop of the same diameter** (`L ∝ N²`), an added 0.14–0.56 mH inductor, or moving the demo to ~1–2 MHz where this loop naturally sits. The third option costs nothing: the VNA already covers it.

### The short path: the other kit variant and a few more turns

The array always spans a factor of four in capacitance, which is a factor of two in frequency, so a coil that puts its **largest** level at 15 kHz sweeps exactly 15–30 kHz. Inverting that fixes the inductance for any kit:

| Kit | Largest branch | Loop needed | Turns at this diameter |
| --- | --- | --- | --- |
| 0.1 µF–10 µF, two parts | 20 µF | **5.6 µH** | **4.5** |
| 0.1 µF–10 µF, one part | 10 µF | **11.3 µH** | **6.3** |
| 0.1 nF–100 nF, two parts | 200 nF | 0.563 mH | 44.5 |
| 0.1 nF–100 nF, one part | 100 nF | 1.126 mH | 62.9 |

The 0.1 µF–10 µF variant is the other size on the same listing ($19.99 for 600 pieces instead of $21.99 for 720). Pairing it with a **4–6 turn loop of the same 14 cm diameter** lands the whole 60-state span on 15–30 kHz, which is far easier than winding 45 turns. The 100 nF kit is the one that needs the impractical coil.

Two further traps at these frequencies:

- **`Cp` must be raised with the array.** Keeping the 200 pF matching capacitor parks the anti-resonance at 21 MHz and the array moves it by only 63 kHz, because `Cs || Cp ≈ Cp` when `Cp` is far smaller than a nanofarad array. The VNA would show no change at all.
- **`Q` collapses.** `Q = omega L / R`, and at 1 MHz `omega L` is only 1.7–3.4 Ω while relay contact resistance is already ~0.25 Ω. Expect `Q ≈ 6–11`, so the dip is broad. At 15 kHz `omega L` is 0.027 Ω, giving `Q ≈ 0.09` — the loop is not a resonator at all there.

### Demo recipe that works

1. Short all six `CS` breaks; the array becomes the single series tuning capacitance across the feed.
2. Every branch = one 100 nF part (or two for the 668 kHz – 1.34 MHz variant).
3. Match with a shunt capacitor sized for 50 Ω: `C = 1/(2 pi f · 50) ≈ 2.2 nF` at 1.5 MHz, not 100 nF.
4. Sweep 0.5–3 MHz on the VNA and log the dip for each of the 60 states.

Outputs: `surface_coil_states.csv` (60 states with both resonances), `surface_coil_design.json`, `surface_coil_band.png`.

## Run the array with the 10 / 47 / 100 nF set

[`demo_3x3_values.py`](demo_3x3_values.py) drops the matched-value search and uses only what the build actually has: three part numbers (10 nF, 47 nF, 100 nF) with at most three in parallel, which reaches 19 branch values. The twelve totals from the design spreadsheet — 300, 247, 210, 200, 194, 157, 147, 120, 110, 100, 104, 94 nF — go on the twelve branches, one each.

On the real 284 nH loop that separates **all 60 states** (no two share a resonance) across **545 kHz – 1.63 MHz**, with a 9.4 kHz median step and a 189 kHz largest step. Putting 100 nF on every branch instead gives the same kind of span (944 kHz – 1.89 MHz) but collapses the 60 states onto 12 resonances. Outputs: `values_lookup.csv`, `values_branches.csv`, `values_3x3_states.png`.

[`build_equivalent_capacitance.py`](build_equivalent_capacitance.py) turns that assignment into the printed table: `equivalent_capacitance.xlsx` has every state's equivalent capacitance, its resonance, the closed branches, the grounded end node and the 20-bit word, on four sheets (`Capacitance` sorted by value, `By state` sorted by index, `By end node`, `Branches`). The same data is in `equivalent_capacitance.csv`.

[`draw_capacitor_map.py`](draw_capacitor_map.py) draws `capacitor_map.png`, which shows where each of `C1…C12` physically sits. The numbers follow the `build_graph(3, 3)` edge order — for each column the vertical edge and then the horizontal edge to its right, top row first — so any drawing made in reading order (horizontals of a row, then that row's verticals) will put eight of the twelve values on the wrong branch.

## Firmware: step through the 60 states on the Mega

`firmware/relay_sequencer/relay_sequencer.ino` drives the array from an Arduino Mega 2560. Twelve mesh relays sit on D22–D33 (`C1…C12`) and the eight end relays on D34–D41 (`E1…E8`); bits 0–11 of the word drive `C1…C12` and bits 12–19 drive `E1…E8`, the same encoding as the CSV. D42–D53 stay free.

The sketch holds each state for `STATE_HOLD_MS` (10 s) and walks the table in `equivalent_capacitance.csv` order — rank 1 is 300 nF / 545 kHz, rank 60 is 33.4 nF / 1634 kHz. Every change prints the rank, `C_eq`, the resonance, the word and the closed branches at 115200 baud, so a VNA sweep can be matched to a state by timestamp.

Typing a rank (`1`…`60`) followed by Enter jumps straight to that state and holds it there, which is the mode to use while taking a measurement; `resume` restarts the timer. Input ends at the newline or, if the monitor is set to "no line ending", after a 1.5 s gap, and the commands are matched as whole words: `step`, `next`, `pause`, `resume`, `restart`, `status`, plus the one-letter shortcuts and `?`.

### Step output for the RC measurement

`D53` drives the RC network through an external **100 kΩ** resistor, in two mutually exclusive modes:

| command | what happens |
| --- | --- |
| `step` | one edge, then held until the next `step` — for a single-shot capture |
| `s` | continuous 2 Hz square wave — for trigger-and-average on a scope |

Both print the expected time constant of the current state. With `C_eq` from 33 nF to 300 nF the time constant is **3.3 ms to 30 ms**, so the 250 ms half period settles every state to within 0.02 %.

```
s
square ON: 2 Hz, R = 100 kOhm, tau = (t90 - t10) / 2.197
  rank 17 expected tau = 8.88 ms   (x0.99 with a 10 MOhm probe)

step
step: D53 -> HIGH  (0 -> 5 V edge, holds)
  rank 17 expected tau = 8.88 ms   (x0.99 with a 10 MOhm probe)
```

Measure `t10` and `t90` on the oscilloscope and take `C_eq = tau / 99.0 kΩ`. The 100 kΩ sits in parallel with a 10× probe's 10 MΩ, so the effective resistance is 99.0 kΩ — a 1 % correction. A 1× probe would load it to 90.9 kΩ and cost 9 %, so use a 10× probe. For `step` the scope needs single-shot or normal trigger on the rising edge; for `s` it can trigger and average continuously. D53 is the SPI SS pin; that only matters if SPI is ever used, and D47–D49 remain free.

[`build_relay_sketch.py`](build_relay_sketch.py) regenerates the table from the CSV, so the firmware can never drift from the report. It compiles clean for `arduino:avr:mega`: 5,328 bytes of flash and 214 bytes of RAM.

Two things to check on the bench:

- `RELAY_ACTIVE_LOW` at the top of the sketch. It defaults to `true`, which suits the low-level-trigger opto modules; flip it to `false` for high-level-trigger boards. Getting it wrong inverts every relay.
- The relay coil supply. Twenty closed coils draw roughly 1 A at 5 V, far more than the Mega's 5 V pin can give, so feed the modules from a separate 5 V supply and tie the grounds together.

## Run the counting examples

From the repository root:

```powershell
python capacitor_array_sim/calc_unique_paths.py
python capacitor_array_sim/brute_force_unique_paths.py
```

These scripts run their built-in example grid sizes. To count another size, call `unique_paths(m, n)` or `count_unique_capacitor_sets(rows, columns)` from the corresponding file. The brute-force method grows exponentially with the number of complete paths, so use it for small grids.
