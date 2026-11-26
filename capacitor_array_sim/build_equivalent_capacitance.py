"""Build the equivalent-capacitance table for the 10 / 47 / 100 nF build.

Writes ``equivalent_capacitance.xlsx`` with four sheets:

* ``Capacitance``  - all 60 states sorted by equivalent capacitance, with the
  closed branches, the grounded end node and the 20-bit switch word;
* ``By state``     - the same rows in state order, for looking a state up;
* ``By end node``  - how the eight destination nodes differ;
* ``Branches``     - what is soldered where.

The loop inductance and the two resonance formulas are repeated here rather
than imported so the script runs on a bare numpy + openpyxl interpreter.

Run ``python capacitor_array_sim/build_equivalent_capacitance.py``.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from demo_3x3_model import DemoModel

PARTS_NF = (10.0, 47.0, 100.0)
ASSIGNMENT_NF = (
    (300.0, (100.0, 100.0, 100.0)),
    (247.0, (100.0, 100.0, 47.0)),
    (210.0, (100.0, 100.0, 10.0)),
    (200.0, (100.0, 100.0)),
    (194.0, (100.0, 47.0, 47.0)),
    (157.0, (100.0, 47.0, 10.0)),
    (147.0, (100.0, 47.0)),
    (120.0, (100.0, 10.0, 10.0)),
    (110.0, (100.0, 10.0)),
    (100.0, (100.0,)),
    (104.0, (47.0, 47.0, 10.0)),
    (94.0, (47.0, 47.0)),
)
END_NAMES = {0: "(0,1)", 1: "(0,2)", 2: "(1,0)", 3: "(1,1)",
             4: "(1,2)", 5: "(2,0)", 6: "(2,1)", 7: "(2,2)"}

HEADER_FILL = PatternFill("solid", fgColor="1E3A8A")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
TITLE_FONT = Font(bold=True, size=14, color="0F172A")
NOTE_FONT = Font(size=9, italic=True, color="475569")
THIN = Side(style="thin", color="CBD5E1")
BORDER = Border(bottom=THIN)
BAND = PatternFill("solid", fgColor="F1F5F9")


def loop_inductance(f_hz=51.705e6, series_pf=200.0, breaks=6):
    return 1.0 / ((2.0 * np.pi * f_hz) ** 2 * (series_pf * 1e-12 / breaks))


def resonance_khz(c_pf, inductance_h):
    return 1.0 / (2.0 * np.pi * np.sqrt(inductance_h * c_pf * 1e-12)) / 1e3


def style_header(sheet, row, columns):
    for column in range(1, columns + 1):
        cell = sheet.cell(row=row, column=column)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center",
                                   wrap_text=True)
        cell.border = TITLE_BORDER


TITLE_BORDER = Border(bottom=Side(style="medium", color="1E3A8A"))


def write_title(sheet, title, note, columns):
    sheet.cell(row=1, column=1, value=title).font = TITLE_FONT
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=columns)
    sheet.cell(row=2, column=1, value=note).font = NOTE_FONT
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=columns)
    sheet.row_dimensions[1].height = 22


def widths(sheet, spec):
    for column, size in spec.items():
        sheet.column_dimensions[column].width = size


def main() -> int:
    base = Path(__file__).with_name("demo_output")
    model = DemoModel()
    inductance = loop_inductance()
    branch_pf = np.array([total for total, _ in ASSIGNMENT_NF]) * 1000.0
    capacitance = model.capacitances(branch_pf, 0.0)

    rows = []
    for index, state in enumerate(model.states):
        mesh = [(state.mesh_mask >> bit) & 1 for bit in range(model.edge_count)]
        end = [0] * 8
        end[state.end[0] * 3 + state.end[1] - 1] = 1
        closed = " + ".join(f"C{bit + 1}" for bit, on in enumerate(mesh) if on)
        end_name = f"E{end.index(1) + 1}"
        word = sum(bit << position for position, bit in enumerate(mesh + end))
        rows.append({
            "state": index,
            "c_pf": float(capacitance[index]),
            "c_nf": float(capacitance[index]) / 1000.0,
            "f_khz": float(resonance_khz(capacitance[index], inductance)),
            "end_index": end.index(1),
            "end": f"({state.end[0]},{state.end[1]})",
            "branches": closed,
            "end_switch": end_name,
            "hex": f"0x{word:05X}",
            "path": state.end[0] + state.end[1],
        })
    # Rank 1 is the largest capacitance, matching the x-axis of the figure.
    rows.sort(key=lambda row: -row["c_pf"])
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank

    workbook = Workbook()

    # ---------------- sheet 1: sorted by capacitance ----------------------
    sheet = workbook.active
    sheet.title = "Capacitance"
    write_title(
        sheet,
        "3 x 3 switched-capacitor array - equivalent capacitance",
        f"12 branches built from 10 / 47 / 100 nF parts (at most 3 in parallel); "
        f"loop L = {inductance * 1e9:.1f} nH; 60 valid switch states",
        9)
    headers = ("Rank", "State", "C_eq (nF)", "C_eq (pF)", "f (kHz)",
               "End node", "Closed branches", "End switch", "20-bit word")
    for column, label in enumerate(headers, 1):
        sheet.cell(row=4, column=column, value=label)
    style_header(sheet, 4, len(headers))
    for offset, row in enumerate(rows):
        line = 5 + offset
        sheet.cell(row=line, column=1, value=row["rank"])
        sheet.cell(row=line, column=2, value=row["state"])
        sheet.cell(row=line, column=3, value=round(row["c_nf"], 3))
        sheet.cell(row=line, column=4, value=round(row["c_pf"], 1))
        sheet.cell(row=line, column=5, value=round(row["f_khz"], 1))
        sheet.cell(row=line, column=6, value=row["end"])
        sheet.cell(row=line, column=7, value=row["branches"])
        sheet.cell(row=line, column=8, value=row["end_switch"])
        sheet.cell(row=line, column=9, value=row["hex"])
        for column in range(1, len(headers) + 1):
            cell = sheet.cell(row=line, column=column)
            cell.border = BORDER
            if offset % 2:
                cell.fill = BAND
        sheet.cell(row=line, column=3).number_format = "0.000"
        sheet.cell(row=line, column=4).number_format = "0.0"
        sheet.cell(row=line, column=5).number_format = "#,##0.0"
    sheet.freeze_panes = "A5"
    widths(sheet, {"A": 7, "B": 8, "C": 11, "D": 11, "E": 11, "F": 11,
                   "G": 34, "H": 11, "I": 13})

    # ---------------- sheet 2: state order --------------------------------
    sheet = workbook.create_sheet("By state")
    write_title(sheet, "Same table in state order",
                "Use this one to look up what a given switch word does", 9)
    for column, label in enumerate(headers, 1):
        sheet.cell(row=4, column=column, value=label)
    style_header(sheet, 4, len(headers))
    for offset, row in enumerate(sorted(rows, key=lambda item: item["state"])):
        line = 5 + offset
        values = (row["rank"], row["state"], round(row["c_nf"], 3),
                  round(row["c_pf"], 1), round(row["f_khz"], 1), row["end"],
                  row["branches"], row["end_switch"], row["hex"])
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row=line, column=column, value=value)
            cell.border = BORDER
            if offset % 2:
                cell.fill = BAND
        sheet.cell(row=line, column=3).number_format = "0.000"
        sheet.cell(row=line, column=4).number_format = "0.0"
        sheet.cell(row=line, column=5).number_format = "#,##0.0"
    sheet.freeze_panes = "A5"
    widths(sheet, {"A": 7, "B": 8, "C": 11, "D": 11, "E": 11, "F": 11,
                   "G": 34, "H": 11, "I": 13})

    # ---------------- sheet 3: by end node --------------------------------
    sheet = workbook.create_sheet("By end node")
    write_title(sheet, "Equivalent capacitance per destination node",
                "Only one end switch is closed at a time; the path length is "
                "the number of branch capacitors between the feed and that node", 7)
    labels = ("End node", "Path length", "States", "C_eq min (nF)",
              "C_eq max (nF)", "f min (kHz)", "f max (kHz)")
    for column, label in enumerate(labels, 1):
        sheet.cell(row=4, column=column, value=label)
    style_header(sheet, 4, len(labels))
    for offset, end_index in enumerate(range(8)):
        group = [row for row in rows if row["end_index"] == end_index]
        line = 5 + offset
        values = (END_NAMES[end_index], group[0]["path"], len(group),
                  round(min(item["c_nf"] for item in group), 3),
                  round(max(item["c_nf"] for item in group), 3),
                  round(min(item["f_khz"] for item in group), 1),
                  round(max(item["f_khz"] for item in group), 1))
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row=line, column=column, value=value)
            cell.border = BORDER
            if offset % 2:
                cell.fill = BAND
        for column in (4, 5):
            sheet.cell(row=line, column=column).number_format = "0.000"
        for column in (6, 7):
            sheet.cell(row=line, column=column).number_format = "#,##0.0"
    widths(sheet, {"A": 12, "B": 12, "C": 9, "D": 14, "E": 14, "F": 14, "G": 14})

    # ---------------- sheet 4: branches -----------------------------------
    sheet = workbook.create_sheet("Branches")
    write_title(sheet, "What is soldered on each branch",
                "Parts are 10 / 47 / 100 nF, at most three in parallel", 6)
    labels = ("Position", "From node", "To node", "Total (nF)", "Parts", "Count")
    for column, label in enumerate(labels, 1):
        sheet.cell(row=4, column=column, value=label)
    style_header(sheet, 4, len(labels))
    for offset, (edge, (total, parts)) in enumerate(zip(model.edges, ASSIGNMENT_NF)):
        line = 5 + offset
        values = (f"C{offset + 1}",
                  f"({edge.source.row},{edge.source.column})",
                  f"({edge.target.row},{edge.target.column})",
                  total, " + ".join(f"{part:g}" for part in parts), len(parts))
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row=line, column=column, value=value)
            cell.border = BORDER
            if offset % 2:
                cell.fill = BAND
        sheet.cell(row=line, column=4).number_format = "0"
    total_parts = sum(len(parts) for _, parts in ASSIGNMENT_NF)
    line = 5 + len(ASSIGNMENT_NF) + 1
    sheet.cell(row=line, column=1, value="Total").font = Font(bold=True)
    sheet.cell(row=line, column=4,
               value=sum(total for total, _ in ASSIGNMENT_NF)).font = Font(bold=True)
    sheet.cell(row=line, column=5, value=f"{total_parts} capacitors").font = Font(bold=True)
    widths(sheet, {"A": 10, "B": 12, "C": 12, "D": 12, "E": 22, "F": 8})

    base.mkdir(parents=True, exist_ok=True)
    output = base / "equivalent_capacitance.xlsx"
    workbook.save(output)

    with (base / "equivalent_capacitance.csv").open(
            "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("rank", "state", "capacitance_nf", "capacitance_pf",
                         "frequency_khz", "end_node", "closed_branches",
                         "end_switch", "hex_word"))
        for row in rows:
            writer.writerow((row["rank"], row["state"], f"{row['c_nf']:.3f}",
                             f"{row['c_pf']:.1f}", f"{row['f_khz']:.1f}",
                             row["end"], row["branches"], row["end_switch"],
                             row["hex"]))

    print(f"L = {inductance * 1e9:.1f} nH")
    print(f"60 states, C_eq {rows[0]['c_nf']:.1f}-{rows[-1]['c_nf']:.1f} nF, "
          f"f {min(r['f_khz'] for r in rows):.1f}-"
          f"{max(r['f_khz'] for r in rows):.1f} kHz")
    print(f"distinct values: {len({round(row['c_pf'], 6) for row in rows})}/60")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
