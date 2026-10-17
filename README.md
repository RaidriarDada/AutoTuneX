# AutoTuneX capstone working package

This package turns the team's proposal into a bench-first design plan for a self-tuning ³¹P RF coil at 3 T. It is a design starting point, not a scanner-ready coil.

| Topic | File |
| --- | --- |
| Hardware architecture, circuit choices, sizing method, PCB and bias design | [hardware/coil_and_tuner.md](hardware/coil_and_tuner.md) |
| Standalone KiCad 4 + 4 PIN capacitor array proof of concept and bias-state test | [hardware/pin_array/README.md](hardware/pin_array/README.md) |
| Standalone KiCad 4 + 4 varactor array and ngspice DC-bias sweep | [hardware/varactor_array/README.md](hardware/varactor_array/README.md) |
| Step-by-step explanation from coil conductor to PIN bias | [hardware/design_walkthrough.md](hardware/design_walkthrough.md) |
| Bench experiments, acceptance gates, and milestones | [plan/verification_plan.md](plan/verification_plan.md) |
| VNA control research and setup | [vna/README.md](vna/README.md) |
| Bench-only state-search algorithm | [control/README.md](control/README.md) |
| MRI integration and safety path | [mri/mri_compatibility.md](mri/mri_compatibility.md) |
| Research references and project document traceability | [research/sources.md](research/sources.md) |

The VNA recorders are [`vna/cmt_s11.py`](vna/cmt_s11.py) for Copper Mountain VNAs over SCPI/TCP and [`vna/nanovna_h4_s11.py`](vna/nanovna_h4_s11.py) for one NanoVNA-H4 sweep over USB serial. Both write complex S11 data, impedance, and a JSON summary. The lab VNA model, coil geometry, scanner interface, allowed RF power, and load range still need to be measured or confirmed before a PCB can be finalized.
