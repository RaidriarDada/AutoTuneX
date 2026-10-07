# Copper Mountain VNA sweep capture

## Which Python library?

**Use [PyVISA](https://pyvisa.readthedocs.io/en/stable/) with the [PyVISA-py](https://pyvisa.readthedocs.io/projects/pyvisa-py/en/stable/installation.html) backend for this project.** The latter supports TCPIP SOCKET using Python's standard socket library, so a separate vendor VISA installation is not required for this connection. Copper Mountain's [automation guide](https://coppermountaintech.com/automation/) supports SCPI over TCP sockets and provides Python examples. Its [TRVNA programming manual](https://coppermountaintech.com/wp-content/uploads/2020/04/TRVNA_Programming_Manual_SCPI.pdf) directly covers the TR1300/1, TR5048, and TR7530. CMT also supports Windows COM automation via `pywin32` on applicable VNA software, but SCPI is a better common interface while the lab model is unknown. Newer CMT VNA software may have a different command family; confirm `*IDN?` and the manual for the actual unit.

The TR1300/1 covers 300 kHz–1.3 GHz, including nominal ³¹P at 3 T (51.705 MHz), according to [CMT's TR1300/1 specifications](https://coppermountaintech.com/discontinued-tr1300-1-2-port-1-3-ghz-vector-network-analyzer/). The USB VNA runs through its **VNA application**; this script connects to that application's Socket Server, not directly to the USB device. CMT's [Python webinar example](https://coppermountaintech.com/wp-content/uploads/2023/04/Automation-Techniques-for-VNA-Measurement.pdf) uses port 5025, `SENS:FREQ:DATA?`, and `CALC:TRAC1:DATA:SDAT?`. The TR manual confirms that `SDAT` returns corrected complex real/imaginary pairs and recommends `TRIG:SING` followed by `*OPC?` for a fresh sweep.

## Lab setup

1. Identify the VNA model and installed application family (TRVNA, S2VNA, RVNA or new CMT VNA). Run its application and connect the instrument.
2. In the VNA application, enable **Socket Server** under network remote-control settings; note its port (often 5025). If the script runs on the same PC, use `127.0.0.1`; from another PC, use the VNA computer's IP and facility-approved firewall setting.
3. Set a linear frequency sweep that spans the resonance and the desired target, e.g. a first 45–60 MHz scouting sweep. Set a low source power appropriate for the bench circuit, an IF bandwidth and point count suitable for the loaded Q, and trace 1 to S11. These are **example** sweep settings, not a calibrated final recipe.
4. Perform one-port open/short/load calibration at the **coil-side reference plane** after finalizing the test cable and fixture. Keep the cable and phantom position fixed. Recalibrate when the reference plane, cable, sweep, or temperature changes enough to invalidate calibration. Check that VNA error correction is enabled.
5. Install Python dependencies on the computer running the script:

   ```powershell
   python -m pip install pyvisa pyvisa-py
   ```

6. Capture a fresh sweep:

   ```powershell
   python vna/cmt_s11.py --host 127.0.0.1 --port 5025 --target-hz 51705000 --output data/load_a_state_00.csv
   ```

The script preserves the previous trace parameter, transfer format, trigger source and channel initiation mode. It does **not** change the frequency span or point count, which helps preserve calibration. `--existing` reads the current data without triggering; use it only if the trace is already S11 and a completed sweep is displayed. The CSV contains frequency, real/imaginary S11, magnitude, return loss, and complex impedance at 50 Ω. The companion JSON records instrument ID, sweep boundaries, target match, and calibration state query. The `best_match_in_sweep_hz` is the frequency with the smallest sampled `|S11|`; it is **not** automatically the physical resonance frequency.

## What to check during the first live session

- `*IDN?` confirms the actual model/software identity.
- The VNA app's socket port and newline termination match the script. The default timeout is 100 seconds; increase `--timeout-ms` for slow sweeps.
- `FORM:DATA ASC`, `SENS1:FREQ:DATA?`, `CALC1:TRAC1:DATA:SDAT?` and the trigger commands are accepted on this model. CMT's TR manual confirms them for TR1300/1; another family may need a small adapter.
- `SENS1:CORR:IMP?` reports 50 Ω; the script stops if the VNA's configured reference impedance differs.
- The reported data length is twice the frequency length and S11 agrees with the VNA display on an open, load, and known resonator.
- `calibration_enabled` is `1` and the frequency grid lies within the valid calibration. That flag alone does not prove a good calibration.

The script has no physical-hardware test yet. Run all offline tests from the project root with `python -m unittest discover`.
