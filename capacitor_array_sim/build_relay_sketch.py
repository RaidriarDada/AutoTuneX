"""Generate the Arduino sketch that steps the array through its 60 states.

The table is read from ``demo_output/equivalent_capacitance.csv`` so the
firmware can never drift away from the numbers in the report: rank 1 is the
state with the largest equivalent capacitance and the lowest resonance.

Run ``python capacitor_array_sim/build_relay_sketch.py``.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT.parent / "firmware" / "relay_sequencer" / "relay_sequencer.ino"

MESH_PINS = tuple(range(22, 34))
END_PINS = tuple(range(34, 42))

HEADER = '''/*
 * relay_sequencer - steps the 3 x 3 switched-capacitor array through its 60
 * valid switch states, one every STATE_HOLD_MS milliseconds.
 *
 * The state table below is generated from equivalent_capacitance.csv, so rank 1
 * is the state with the largest equivalent capacitance (lowest resonance) and
 * rank 60 the smallest.  Do not hand-edit the table; re-run
 * capacitor_array_sim/build_relay_sketch.py instead.
 *
 * Board      : Arduino Mega 2560 (COM 17)
 * Switches   : 12 mesh relays on D22..D33 (C1..C12) and 8 end relays on
 *              D34..D41 (E1..E8).  Bits 0..11 of the word drive C1..C12 and
 *              bits 12..19 drive E1..E8, exactly as in the CSV.
 * Step out   : D53 drives a 2 Hz square wave through the external 100 kOhm
 *              resistor, for measuring C_eq with the RC method.  D53 is the
 *              SPI SS pin, which is fine while SPI is unused; D47-D49 are free
 *              if that ever becomes a problem.
 *
 * Serial     : 115200 baud.  Every state change prints the rank, the equivalent
 *              capacitance, the resonance and the switch word.
 *              Commands: 1..60 then Enter = jump to that state and hold,
 *                        step = one step edge, held until the next "step",
 *                        s = continuous 2 Hz square wave on/off,
 *                        next, pause, resume, restart, status (and ? alone).
 */

#include <Arduino.h>

// ---------------------------------------------------------------- pin map --
const uint8_t MESH_PINS[12] = { {{MESH_PINS}} };
const uint8_t END_PINS[8]   = { {{END_PINS}} };

// One end switch must be closed at a time; the firmware refuses a word that
// does not have exactly one end bit set.  The UL suffix matters: on AVR an int
// is 16 bits, so 0xFFu << 12 would silently truncate to 0xF000 and mask away
// E5..E8.
const uint32_t END_MASK = 0xFFUL << 12;

// ---------------------------------------------------------------- polarity --
// Set false if your relay module turns on with a HIGH input.
const bool RELAY_ACTIVE_LOW = true;

// ------------------------------------------------------------------ timing --
const uint32_t STATE_HOLD_MS = 10000UL;   // how long each state stays on
const uint16_t SETTLE_MS     = 60;        // relay settling before the log line
const uint32_t BAUD          = 115200;

// -------------------------------------------------------------- the table --
struct Step {
  uint32_t word;      // bit 0..11 = C1..C12, bit 12..19 = E1..E8
  uint16_t c_nf10;    // equivalent capacitance, tenths of nF
  uint16_t f_khz10;   // resonance frequency, tenths of kHz
};

const uint8_t STEP_COUNT = {{COUNT}};
const Step STEPS[STEP_COUNT] PROGMEM = {
{{TABLE}}};

// ---------------------------------------------------------- step generator --
// The RC measurement needs a repeating edge so the scope can trigger and
// average.  With 100 kOhm and 33 nF..300 nF the time constant is 3.3..30 ms,
// so a 2 Hz square wave (250 ms per half period = 8.3 tau worst case) lets
// every state settle to within 0.02 % before the next edge.
const uint8_t  STEP_PIN      = 53;
const uint32_t STEP_R_OHMS   = 100000UL;   // the external series resistor
const uint16_t STEP_HALF_MS  = 250;        // 2 Hz, 50 % duty

bool     squareRunning = false;   // s   : continuous 2 Hz wave
bool     pinLevel      = false;   // step: single edge, held until next step
uint32_t lastEdge      = 0;

// ------------------------------------------------------------------- state --
uint8_t  currentStep = 0;
uint32_t lastChange  = 0;
bool     paused      = false;

// Typed input, so "17" jumps to rank 17 and "step" toggles the square wave.
// Input ends at the newline or, if the monitor is set to "no line ending",
// after a short gap.
char     inputBuffer[12];
uint8_t  inputLength = 0;
uint32_t lastInput   = 0;
const uint16_t INPUT_TIMEOUT_MS = 1500;

// ------------------------------------------------------------------ helpers --
void writeRelay(uint8_t pin, bool on) {
  digitalWrite(pin, (on != RELAY_ACTIVE_LOW) ? HIGH : LOW);
}

void allRelaysOff() {
  for (uint8_t i = 0; i < 12; ++i) writeRelay(MESH_PINS[i], false);
  for (uint8_t i = 0; i < 8; ++i)  writeRelay(END_PINS[i], false);
}

uint8_t countBits(uint32_t value) {
  uint8_t total = 0;
  while (value) { total += value & 1u; value >>= 1; }
  return total;
}

void printTenths(uint16_t value) {
  Serial.print(value / 10);
  Serial.print('.');
  Serial.print(value % 10);
}

// Five hex digits, leading zeros kept, so a word always looks like 0x0C412.
void printHex5(uint32_t value) {
  Serial.print(F("0x"));
  for (int8_t shift = 16; shift >= 0; shift -= 4) {
    Serial.print((value >> shift) & 0xFu, HEX);
  }
}

void printBranches(uint32_t word) {
  for (uint8_t i = 0; i < 12; ++i) {
    if ((word >> i) & 1u) { Serial.print('C'); Serial.print(i + 1); Serial.print(' '); }
  }
  Serial.print('|');
  for (uint8_t i = 0; i < 8; ++i) {
    if ((word >> (12 + i)) & 1u) { Serial.print('E'); Serial.print(i + 1); Serial.print(' '); }
  }
}

// Expected RC time constant of a state, in ms: tau = R * C.
void printTau(uint16_t c_nf10) {
  const uint32_t tau_us = STEP_R_OHMS * (uint32_t)c_nf10 / 10000UL;
  Serial.print(tau_us / 1000);
  Serial.print('.');
  const uint16_t fraction = (uint16_t)((tau_us % 1000) / 10);
  if (fraction < 10) Serial.print('0');
  Serial.print(fraction);
  Serial.print(F(" ms"));
}

// -------------------------------------------------------------------- step --
// D53 drives the RC network through the external 100 kOhm resistor.  Two
// modes, mutually exclusive:
//   s     -> continuous 2 Hz square wave, for scope averaging
//   step  -> one edge at a time, held until the next "step", for single-shot
void serviceStep() {
  if (!squareRunning) return;
  if (millis() - lastEdge >= STEP_HALF_MS) {
    pinLevel = !pinLevel;
    digitalWrite(STEP_PIN, pinLevel ? HIGH : LOW);
    lastEdge = millis();
  }
}

void printExpectedTau() {
  Serial.print(F("  rank "));
  Serial.print(currentStep + 1);
  Serial.print(F(" expected tau = "));
  printTau(pgm_read_word(&STEPS[currentStep].c_nf10));
  Serial.println(F("   (x0.99 with a 10 MOhm probe)"));
}

void toggleSquare() {
  squareRunning = !squareRunning;
  pinLevel      = false;
  digitalWrite(STEP_PIN, LOW);
  lastEdge      = millis();

  if (!squareRunning) {
    Serial.println(F("square OFF, D53 -> LOW"));
    return;
  }

  Serial.print(F("square ON: "));
  Serial.print(1000UL / (2UL * STEP_HALF_MS));
  Serial.print(F(" Hz, R = "));
  Serial.print(STEP_R_OHMS / 1000UL);
  Serial.println(F(" kOhm, tau = (t90 - t10) / 2.197"));
  printExpectedTau();
}

void singleStep() {
  squareRunning = false;          // the manual edge takes over the pin
  pinLevel      = !pinLevel;
  digitalWrite(STEP_PIN, pinLevel ? HIGH : LOW);

  Serial.print(F("step: D53 -> "));
  Serial.print(pinLevel ? F("HIGH") : F("LOW"));
  Serial.println(pinLevel ? F("  (0 -> 5 V edge, holds)") : F("  (5 -> 0 V edge, holds)"));
  printExpectedTau();
}

// ------------------------------------------------------------------- setup --
void setup() {
  // Pins are high impedance after reset, so drive every relay off first.
  for (uint8_t i = 0; i < 12; ++i) pinMode(MESH_PINS[i], OUTPUT);
  for (uint8_t i = 0; i < 8; ++i)  pinMode(END_PINS[i], OUTPUT);
  allRelaysOff();

  pinMode(STEP_PIN, OUTPUT);
  digitalWrite(STEP_PIN, LOW);

  Serial.begin(BAUD);
  while (!Serial) { }

  Serial.println();
  Serial.println(F("relay_sequencer: 3 x 3 switched-capacitor array"));
  Serial.print(F("  "));
  Serial.print(STEP_COUNT);
  Serial.print(F(" states, "));
  Serial.print(STATE_HOLD_MS / 1000);
  Serial.println(F(" s each"));
  Serial.println(F("  C1..C12 -> D22..D33, E1..E8 -> D34..D41"));
  Serial.println(F("  type 1..60 then Enter to jump to that state (holds)"));
  Serial.println(F("  step = single step edge (holds)   s = 2 Hz square wave"));
  Serial.println(F("  next / pause / resume / restart / status"));
  Serial.println();

  showStep(0);
}

// -------------------------------------------------------------------- loop --
void loop() {
  handleSerial();
  serviceStep();

  if (!paused && (millis() - lastChange) >= STATE_HOLD_MS) {
    advance();
  }
}

// ------------------------------------------------------------------- state --
void advance() {
  uint8_t next = (currentStep + 1) % STEP_COUNT;
  if (next == 0) {
    Serial.println(F("--- cycle complete, restarting at rank 1 ---"));
  }
  showStep(next);
}

void showStep(uint8_t index) {
  const uint32_t word = pgm_read_dword(&STEPS[index].word);
  const uint16_t c    = pgm_read_word(&STEPS[index].c_nf10);
  const uint16_t f    = pgm_read_word(&STEPS[index].f_khz10);

  if (((word & END_MASK) >> 12) == 0 || countBits((word & END_MASK) >> 12) != 1) {
    Serial.print(F("!! rank "));
    Serial.print(index + 1);
    Serial.println(F(" does not close exactly one end switch, skipped"));
    currentStep = index;
    lastChange  = millis();
    allRelaysOff();
    return;
  }

  allRelaysOff();          // break before make: never two ends at once
  delay(2);
  for (uint8_t i = 0; i < 12; ++i) {
    writeRelay(MESH_PINS[i], (word >> i) & 1u);
  }
  for (uint8_t i = 0; i < 8; ++i) {
    writeRelay(END_PINS[i], (word >> (12 + i)) & 1u);
  }

  currentStep = index;
  lastChange  = millis();

  delay(SETTLE_MS);

  Serial.print(F("["));
  if (index + 1 < 10) Serial.print(' ');
  Serial.print(index + 1);
  Serial.print(F("/"));
  Serial.print(STEP_COUNT);
  Serial.print(F("]  C_eq = "));
  printTenths(c);
  Serial.print(F(" nF   f = "));
  printTenths(f);
  Serial.print(F(" kHz   word = "));
  printHex5(word);
  Serial.print(F("   "));
  printBranches(word);
  Serial.println();
}

// ------------------------------------------------------------------ serial --
// Input is collected until Enter (or a 1.5 s pause) and then matched against
// whole words, so "step", "next", "pause", "resume", "restart" and "status"
// work, as do the one-letter shortcuts and a bare rank number.
bool sameWord(const char* word) {
  uint8_t i = 0;
  while (word[i] != 0) {
    if (i >= inputLength || inputBuffer[i] != word[i]) return false;
    ++i;
  }
  return i == inputLength;
}

void applyNumber() {
  uint16_t value = 0;
  for (uint8_t i = 0; i < inputLength; ++i) {
    value = value * 10 + (uint8_t)(inputBuffer[i] - '0');
  }
  inputLength = 0;

  if (value < 1 || value > STEP_COUNT) {
    Serial.print(F("no state "));
    Serial.print(value);
    Serial.print(F(", valid range is 1.."));
    Serial.println(STEP_COUNT);
    return;
  }

  paused = true;
  showStep((uint8_t)(value - 1));
  Serial.println(F("  holding on request - send resume to continue"));
}

void printStatus() {
  Serial.print(F("rank "));
  Serial.print(currentStep + 1);
  Serial.print(F("/"));
  Serial.print(STEP_COUNT);
  Serial.print(paused ? F("  holding") : F("  running"));
  Serial.print(F(", "));
  Serial.print((millis() - lastChange) / 1000);
  Serial.print(F(" s into this state, "));
  Serial.print(squareRunning ? F("square on, level ") : F("manual level "));
  Serial.println(pinLevel ? F("HIGH") : F("LOW"));
}

void dispatchInput() {
  if (inputLength == 0) return;
  inputBuffer[inputLength] = 0;

  for (uint8_t i = 0; i < inputLength; ++i) {
    if (inputBuffer[i] >= 'A' && inputBuffer[i] <= 'Z') {
      inputBuffer[i] = (char)(inputBuffer[i] - 'A' + 'a');
    }
  }

  bool digits = true;
  for (uint8_t i = 0; i < inputLength; ++i) {
    if (inputBuffer[i] < '0' || inputBuffer[i] > '9') { digits = false; break; }
  }
  if (digits) {
    applyNumber();
    return;
  }

  if (sameWord("step")) {
    singleStep();
  } else if (sameWord("square") || sameWord("s")) {
    toggleSquare();
  } else if (sameWord("next") || sameWord("n")) {
    advance();
  } else if (sameWord("pause") || sameWord("p")) {
    paused = !paused;
    Serial.println(paused ? F("paused") : F("running"));
    if (!paused) lastChange = millis();
  } else if (sameWord("resume") || sameWord("run")) {
    paused = false;
    lastChange = millis();
    Serial.println(F("running"));
  } else if (sameWord("restart") || sameWord("r")) {
    showStep(0);
  } else if (sameWord("status")) {
    printStatus();
  } else {
    Serial.print(F("unknown command: "));
    Serial.println(inputBuffer);
  }

  inputLength = 0;
}

void handleSerial() {
  while (Serial.available()) {
    const char input = (char)Serial.read();

    if ((input >= '0' && input <= '9') ||
        (input >= 'a' && input <= 'z') ||
        (input >= 'A' && input <= 'Z')) {
      if (inputLength < sizeof(inputBuffer) - 1) {
        inputBuffer[inputLength++] = input;
        inputBuffer[inputLength] = 0;
      }
      lastInput = millis();
      continue;
    }

    if (input == ' ' || input == '\\t') continue;

    if (input == '?') {
      dispatchInput();
      printStatus();
      continue;
    }

    dispatchInput();   // newline, carriage return or anything else
  }

  // Input that never got a newline still fires after a short gap, so the
  // monitor works with "no line ending" as well.
  if (inputLength > 0 && (millis() - lastInput) > INPUT_TIMEOUT_MS) {
    dispatchInput();
  }
}
'''


def main() -> int:
    source = ROOT / "demo_output" / "equivalent_capacitance.csv"
    with source.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    if len(rows) != 60:
        raise SystemExit(f"expected 60 rows, found {len(rows)}")

    lines = []
    for row in rows:
        word = int(row["hex_word"], 16)
        c_nf10 = round(float(row["capacitance_nf"]) * 10)
        f_khz10 = round(float(row["frequency_khz"]) * 10)
        bits = word & 0xFFF
        end_bits = (word >> 12) & 0xFF
        if bin(end_bits).count("1") != 1:
            raise SystemExit(f"rank {row['rank']}: end bits are not one-hot")
        if not 0 < c_nf10 < 65535 or not 0 < f_khz10 < 65535:
            raise SystemExit(f"rank {row['rank']}: value does not fit uint16")
        lines.append(
            f"  {{ 0x{word:05X}u, {c_nf10:5d}, {f_khz10:5d} }},"
            f"  // {int(row['rank']):2d}  {float(row['capacitance_nf']):7.3f} nF"
            f"  {float(row['frequency_khz']):7.1f} kHz  {row['end_node']}"
            f"  switches {bin(bits).count('1') + 1:2d}\n")

    text = (HEADER
            .replace("{{MESH_PINS}}", ", ".join(str(pin) for pin in MESH_PINS))
            .replace("{{END_PINS}}", ", ".join(str(pin) for pin in END_PINS))
            .replace("{{COUNT}}", str(len(rows)))
            .replace("{{TABLE}}", "".join(lines)))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")

    print(f"wrote {OUTPUT}")
    print(f"{len(rows)} states, {len(MESH_PINS)} mesh pins, {len(END_PINS)} end pins")
    print(f"first: {rows[0]['rank']}  {rows[0]['capacitance_nf']} nF  "
          f"{rows[0]['frequency_khz']} kHz  {rows[0]['hex_word']}")
    print(f"last : {rows[-1]['rank']}  {rows[-1]['capacitance_nf']} nF  "
          f"{rows[-1]['frequency_khz']} kHz  {rows[-1]['hex_word']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
