# VNA sweep capture

## NanoVNA-H4: one S11 sweep over USB

[`nanovna_h4_s11.py`](nanovna_h4_s11.py) sends the H4 serial-shell command
`scan START_HZ STOP_HZ POINTS 3`. Output mask `3` asks the instrument for each
frequency and complex CH0/S11 value. The script records exactly one fresh
sweep, checks the returned point count, and writes the same S11 CSV and JSON
summary format as the Copper Mountain recorder below. It does not run a
segmented sweep or control the capacitor array.

1. Connect the coil or test load to **CH0**. Complete an open/short/load
   calibration at the measurement reference plane over the intended frequency
   range. Keep the cable and fixture fixed. The script records whether the H4
   reports `cal'ed`, but that flag alone does not prove calibration quality.
2. Connect the H4's USB serial port and identify its COM port on Windows.
   Close NanoVNA-Saver or any other program using that port.
3. Install and run from the repository root:

   ```powershell
   python -m pip install pyserial
   python -m serial.tools.list_ports
   python -m vna.nanovna_h4_s11 --port COM4 --start-hz 45000000 --stop-hz 60000000 --points 101 --target-hz 51705000 --output data/h4_first_sweep.csv
   ```

The serial command may pause the H4's normal display sweep afterward. Resume
it on the device if desired. The default 101 points work on common H4 firmware;
some versions support 401. The script reads the firmware's `p:` limit when it
is reported and rejects a larger request. `--timeout` defaults to 60 seconds
for the complete serial response. `--baud` defaults to 115200; USB CDC firmware
usually ignores this setting.

The CSV contains frequency, complex S11, magnitude, return loss, and complex
50 Ω impedance. The JSON includes firmware information, the scan command,
calibration status, and the target-frequency result. A minimum in sampled
`|S11|` is a match minimum, not automatically the coil's physical resonance.

This implementation is based on the firmware's documented
[`scan` command and output mask](https://github.com/DiSlord/NanoVNA-D/blob/master/main.c#L1306-L1380).
The first live session should compare one saved trace with the H4 display and
confirm the unit's actual firmware supports this serial-shell command.

## Lab Planar 808/1: S4VNA over a localhost socket

[`s4vna_s11.py`](s4vna_s11.py) reads one complex S11 sweep from the S4VNA
application. It uses the same CSV/JSON output format as the other VNA recorders.
It talks to S4VNA's SCPI Socket Server, not directly to the USB hardware.

### Set up S4VNA on the connected Windows PC

1. Install and start **S4VNA**, power on the 808/1, and connect its USB cable.
   In **System > Misc Setup > Demo Mode**, select **OFF**. The application may
   restart. Confirm its status says **Ready** with the real instrument attached.
2. In **System > Misc Setup > Network Remote Control Settings**, set **Socket
   Port** to `5025` (or note the port you choose), then set **Socket Server** to
   **ON**. Keep S4VNA running while the Python script runs. The script uses
   `127.0.0.1` because S4VNA and Python are on the same PC.
3. Configure channel 1, trace 1 as **S11**, with a frequency sweep containing
   the target frequency. Set power, IF bandwidth, and point count for the bench
   circuit. Perform a one-port open/short/load calibration at the coil-side
   reference plane and enable error correction. Leave system Z0 at **50 ohms**.

From the repository root on that same PC:

```powershell
python -m pip install pyvisa pyvisa-py
python -m vna.s4vna_s11 --host 127.0.0.1 --port 5025 --target-hz 51705000 --output data/s4vna_first_sweep.csv
```

The script checks instrument readiness, 50-ohm Z0, and that the requested trace
is S11. It temporarily selects BUS triggering, waits for a completed sweep,
reads frequencies and corrected complex S11 values, then restores the previous
trigger source and channel initiation mode. It does not change the sweep span,
power, point count, calibration, or trace assignment. `--existing` reads the
current trace without starting a new sweep; put the channel in Hold in S4VNA
first so it cannot update between the two data queries. `--channel` and
`--trace` default to 1; each accepts 1..16. Increase `--timeout-ms` for a slow
sweep.

The JSON records whether error correction was enabled, but that flag alone
does not establish calibration quality. Before using captures for tuning,
compare a saved sweep with the S4VNA display on a known load and confirm Demo
Mode is off. This code has offline tests but has not yet been run with the lab
instrument. The socket path deliberately does not send `FORM:DATA`: current
S4VNA help says it does not apply to the Socket protocol.

Sources: [CMT automation guide](https://coppermountaintech.com/automation-guide-for-cmt-vnas/),
[S4VNA SCPI manual](https://coppermountaintech.com/sx-prog-manual-scpi/),
[S4VNA `FORM:DATA` help](https://coppermountaintech.com/help-s4/formdata.html).

## Copper Mountain TRVNA: existing recorder

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
