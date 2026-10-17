"""Interactive capacitor grid. Run with ``python capacitor_simulator.py``."""

import math
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from calc_equivalent_capacitance import calculate_equivalent_capacitance
from turn_on_capacitor import build_graph, turn_on_capacitor


def simulate_capacitor_grid(rows, columns, switch_array, capacitances):
    """Return (equivalent capacitance in pF, destination) for a grid.

    ``switch_array`` uses the existing interleaved edge layout. The keys of
    ``capacitances`` are (array row, array column) edge positions; omitted
    values use the 1 pF default. A failed validation does not change any
    existing graph, because each run builds its own graph.
    """
    if type(rows) is not int or type(columns) is not int or not (1 <= rows <= 5) or not (1 <= columns <= 5):
        raise ValueError("rows and columns must each be between 1 and 5")
    if rows == columns == 1:
        raise ValueError("A 1 x 1 grid has no capacitors. Choose at least two nodes.")

    graph = build_graph(rows, columns)
    for edge in graph.edges:
        slot = (edge.source.row + edge.target.row,
                edge.source.column + edge.target.column)
        edge.capacitance = capacitances.get(slot, 1.0)

    turn_on_capacitor(graph, switch_array)
    active = [edge for edge in graph.edges if edge.switch]
    sources = {edge.source for edge in active}
    sinks = {edge.target for edge in active} - sources
    if len(sinks) != 1:
        raise ValueError("selected capacitors must lead to one destination node")
    destination_node = sinks.pop()
    destination = (destination_node.row, destination_node.column)
    result = calculate_equivalent_capacitance(graph, destination)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("capacitance values are too extreme to calculate reliably")
    return result, destination


class CapacitorSimulator(tk.Tk):
    """Small Tkinter editor for networks of at most 5 by 5 nodes."""

    NODE_X = 76
    NODE_Y = 64
    COLUMN_SPACING = 145
    ROW_SPACING = 105

    def __init__(self):
        super().__init__()
        self.title("Capacitor Array Simulator")
        self.geometry("900x790")
        self.minsize(800, 700)
        self.configure(bg="#f4f7fb")

        self.rows_var = tk.StringVar(value="3")
        self.columns_var = tk.StringVar(value="3")
        self.result_var = tk.StringVar(value="Set the switches, then click Run.")
        self.details_var = tk.StringVar(value="Capacitance is measured in pF.")
        self.selected_slots = set()
        self.capacitances = {}
        self.destination = None

        main = ttk.Frame(self, padding=20)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="Capacitor array simulator",
                  font=("Segoe UI", 20, "bold")).pack(anchor="w")

        controls = ttk.Frame(main)
        controls.pack(fill="x", pady=(14, 10))
        ttk.Label(controls, text="Node rows").pack(side="left")
        rows_box = ttk.Combobox(controls, width=3, state="readonly",
                                values=(1, 2, 3, 4, 5), textvariable=self.rows_var)
        rows_box.pack(side="left", padx=(8, 20))
        rows_box.bind("<<ComboboxSelected>>", self._change_size)
        ttk.Label(controls, text="Node columns").pack(side="left")
        columns_box = ttk.Combobox(controls, width=3, state="readonly",
                                   values=(1, 2, 3, 4, 5), textvariable=self.columns_var)
        columns_box.pack(side="left", padx=(8, 20))
        columns_box.bind("<<ComboboxSelected>>", self._change_size)
        ttk.Button(controls, text="Run", command=self._run).pack(side="right")

        ttk.Label(main, text="Click a switch to turn it on or off. Click a capacitor to set its value. "
                  "Valid paths start at S and move right or down to the same end node.",
                  wraplength=790).pack(anchor="w", pady=(0, 10))

        canvas_frame = ttk.Frame(main, padding=1, relief="solid")
        canvas_frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg="white", highlightthickness=0)
        vertical_scroll = ttk.Scrollbar(canvas_frame, orient="vertical",
                                        command=self.canvas.yview)
        horizontal_scroll = ttk.Scrollbar(canvas_frame, orient="horizontal",
                                          command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical_scroll.set,
                              xscrollcommand=horizontal_scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical_scroll.grid(row=0, column=1, sticky="ns")
        horizontal_scroll.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        result_frame = ttk.Frame(main)
        result_frame.pack(fill="x", pady=(14, 0))
        ttk.Label(result_frame, textvariable=self.result_var,
                  font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(result_frame, textvariable=self.details_var).pack(anchor="w", pady=(3, 0))

        self._change_size()

    @staticmethod
    def _slot(edge):
        return (edge.source.row + edge.target.row,
                edge.source.column + edge.target.column)

    def _change_size(self, _event=None):
        self.rows = int(self.rows_var.get())
        self.columns = int(self.columns_var.get())
        self.graph = build_graph(self.rows, self.columns)
        self.selected_slots.clear()
        self.capacitances = {self._slot(edge): 1.0 for edge in self.graph.edges}
        self._clear_result()
        self._draw()

    def _clear_result(self):
        self.destination = None
        self.result_var.set("Set the switches, then click Run.")
        self.details_var.set("Capacitance is measured in pF.")

    def _node_position(self, node):
        return (self.NODE_X + node.column * self.COLUMN_SPACING,
                self.NODE_Y + node.row * self.ROW_SPACING)

    def _draw(self):
        canvas = self.canvas
        canvas.delete("all")
        canvas.configure(
            scrollregion=(0, 0,
                          2 * self.NODE_X + (self.columns - 1) * self.COLUMN_SPACING,
                          2 * self.NODE_Y + (self.rows - 1) * self.ROW_SPACING)
        )

        for edge in self.graph.edges:
            slot = self._slot(edge)
            x, y = self._node_position(edge.source)
            if edge.horizontal:
                self._draw_horizontal(slot, x, y)
            else:
                self._draw_vertical(slot, x, y)

        for (row, column), node in self.graph.nodes.items():
            x, y = self._node_position(node)
            is_source = (row, column) == (0, 0)
            is_destination = (row, column) == self.destination
            fill = "#2563eb" if is_source else "#16a34a" if is_destination else "#334155"
            canvas.create_oval(x - 8, y - 8, x + 8, y + 8,
                               fill=fill, outline="white", width=2)
            if is_source or is_destination:
                canvas.create_text(x - 16, y - 20,
                                   text="S" if is_source else "End",
                                   fill=fill, font=("Segoe UI", 9, "bold"))

    def _draw_horizontal(self, slot, x, y):
        canvas = self.canvas
        on = slot in self.selected_slots
        switch_tag = f"switch_{slot[0]}_{slot[1]}"
        cap_tag = f"capacitor_{slot[0]}_{slot[1]}"
        wire = "#475569"

        canvas.create_line(x, y, x + 23, y, fill=wire, width=2)
        canvas.create_line(x + 49, y, x + 91, y, fill=wire, width=2)
        canvas.create_line(x + 101, y, x + self.COLUMN_SPACING, y,
                           fill=wire, width=2)

        canvas.create_rectangle(x + 17, y - 20, x + 56, y + 20,
                                fill="#dcfce7" if on else "#f1f5f9",
                                outline="#16a34a" if on else "#94a3b8",
                                tags=switch_tag)
        canvas.create_line(x + 17, y, x + 23, y, fill=wire, width=2,
                           tags=switch_tag)
        canvas.create_line(x + 49, y, x + 56, y, fill=wire, width=2,
                           tags=switch_tag)
        canvas.create_oval(x + 21, y - 2, x + 25, y + 2, fill=wire, tags=switch_tag)
        canvas.create_oval(x + 47, y - 2, x + 51, y + 2, fill=wire, tags=switch_tag)
        canvas.create_line(x + 23, y, x + 49, y if on else y - 11,
                           fill="#16a34a" if on else wire, width=3,
                           tags=switch_tag)

        canvas.create_rectangle(x + 77, y - 25, x + 116, y + 37,
                                fill="white", outline="#cbd5e1", tags=cap_tag)
        canvas.create_line(x + 77, y, x + 91, y, fill=wire, width=2,
                           tags=cap_tag)
        canvas.create_line(x + 101, y, x + 116, y, fill=wire, width=2,
                           tags=cap_tag)
        canvas.create_line(x + 91, y - 14, x + 91, y + 14,
                           fill=wire, width=3, tags=cap_tag)
        canvas.create_line(x + 101, y - 14, x + 101, y + 14,
                           fill=wire, width=3, tags=cap_tag)
        canvas.create_text(x + 96, y + 27,
                           text=f"{self.capacitances[slot]:g} pF",
                           fill="#0f172a", font=("Segoe UI", 9), tags=cap_tag)

        canvas.tag_bind(switch_tag, "<Button-1>",
                        lambda _event, position=slot: self._toggle(position))
        canvas.tag_bind(cap_tag, "<Button-1>",
                        lambda _event, position=slot: self._edit_capacitance(position))

    def _draw_vertical(self, slot, x, y):
        canvas = self.canvas
        on = slot in self.selected_slots
        switch_tag = f"switch_{slot[0]}_{slot[1]}"
        cap_tag = f"capacitor_{slot[0]}_{slot[1]}"
        wire = "#475569"

        canvas.create_line(x, y, x, y + 25, fill=wire, width=2)
        canvas.create_line(x, y + 45, x, y + 72, fill=wire, width=2)
        canvas.create_line(x, y + 82, x, y + self.ROW_SPACING,
                           fill=wire, width=2)

        canvas.create_rectangle(x - 20, y + 18, x + 20, y + 51,
                                fill="#dcfce7" if on else "#f1f5f9",
                                outline="#16a34a" if on else "#94a3b8",
                                tags=switch_tag)
        canvas.create_line(x, y + 18, x, y + 25, fill=wire, width=2,
                           tags=switch_tag)
        canvas.create_line(x, y + 45, x, y + 51, fill=wire, width=2,
                           tags=switch_tag)
        canvas.create_oval(x - 2, y + 23, x + 2, y + 27, fill=wire, tags=switch_tag)
        canvas.create_oval(x - 2, y + 43, x + 2, y + 47, fill=wire, tags=switch_tag)
        canvas.create_line(x, y + 25, x if on else x + 11, y + 45,
                           fill="#16a34a" if on else wire, width=3,
                           tags=switch_tag)

        canvas.create_rectangle(x - 25, y + 63, x + 68, y + 91,
                                fill="white", outline="#cbd5e1", tags=cap_tag)
        canvas.create_line(x, y + 63, x, y + 72, fill=wire, width=2,
                           tags=cap_tag)
        canvas.create_line(x, y + 82, x, y + 91, fill=wire, width=2,
                           tags=cap_tag)
        canvas.create_line(x - 13, y + 72, x + 13, y + 72,
                           fill=wire, width=3, tags=cap_tag)
        canvas.create_line(x - 13, y + 82, x + 13, y + 82,
                           fill=wire, width=3, tags=cap_tag)
        canvas.create_text(x + 40, y + 77,
                           text=f"{self.capacitances[slot]:g} pF",
                           fill="#0f172a", font=("Segoe UI", 9), tags=cap_tag)

        canvas.tag_bind(switch_tag, "<Button-1>",
                        lambda _event, position=slot: self._toggle(position))
        canvas.tag_bind(cap_tag, "<Button-1>",
                        lambda _event, position=slot: self._edit_capacitance(position))

    def _toggle(self, slot):
        if slot in self.selected_slots:
            self.selected_slots.remove(slot)
        else:
            self.selected_slots.add(slot)
        self._clear_result()
        self._draw()

    def _edit_capacitance(self, slot):
        entry = simpledialog.askstring(
            "Capacitance", "Enter capacitance in pF:",
            initialvalue=f"{self.capacitances[slot]:g}", parent=self)
        if entry is None:
            return
        try:
            value = float(entry.strip())
        except ValueError:
            value = float("nan")
        if not math.isfinite(value) or value <= 0:
            messagebox.showwarning("Invalid capacitance",
                                   "Enter a positive, finite number of pF.",
                                   parent=self)
            return
        self.capacitances[slot] = value
        self._clear_result()
        self._draw()

    def _run(self):
        array = [[0] * (2 * self.columns - 1)
                 for _ in range(2 * self.rows - 1)]
        for row, column in self.selected_slots:
            array[row][column] = 1
        try:
            result, destination = simulate_capacitor_grid(
                self.rows, self.columns, array, self.capacitances)
        except (ValueError, TypeError) as error:
            messagebox.showwarning("Invalid capacitor selection", str(error), parent=self)
            return

        self.destination = destination
        self.result_var.set(f"Equivalent capacitance: {result:.8g} pF")
        self.details_var.set(
            f"From S (row 1, column 1) to row {destination[0] + 1}, "
            f"column {destination[1] + 1}.")
        self._draw()


if __name__ == "__main__":
    CapacitorSimulator().mainloop()
