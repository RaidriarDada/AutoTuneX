#include <Arduino.h>

// ---------------------------------------------------------------- pin map --
const uint8_t MESH_PINS[12] = { 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33 };
const uint8_t END_PINS[8]   = { 34, 35, 36, 37, 38, 39, 40, 41 };

const uint32_t END_MASK = 0xFFUL << 12;

// Set false if relay module turns on with a HIGH input.
const bool RELAY_ACTIVE_LOW = true;

const uint32_t STATE_HOLD_MS = 10000UL;   // how long each state stays on
const uint16_t SETTLE_MS     = 60;        // relay settling before the log line
const uint32_t BAUD          = 115200;

struct Step {
  uint32_t word;
  uint16_t c_nf10;
  uint16_t f_khz10;
};

const uint8_t STEP_COUNT = 60;
const Step STEPS[STEP_COUNT] PROGMEM = {
  { 0x04001u,  3000,  5450 },  //  1  300.000 nF    545.0 kHz  (1,0)  switches  2
  { 0x01002u,  2470,  6007 },  //  2  247.000 nF    600.7 kHz  (0,1)  switches  2
  { 0x08047u,  2122,  6481 },  //  3  212.159 nF    648.1 kHz  (1,1)  switches  5
  { 0x1015Fu,  1271,  8372 },  //  4  127.126 nF    837.2 kHz  (1,2)  switches  8
  { 0x1015Bu,  1224,  8532 },  //  5  122.417 nF    853.2 kHz  (1,2)  switches  7
  { 0x404E7u,  1185,  8671 },  //  6  118.513 nF    867.1 kHz  (2,1)  switches  8
  { 0x08006u,  1135,  8861 },  //  7  113.501 nF    886.1 kHz  (1,1)  switches  3
  { 0x0200Au,  1105,  8980 },  //  8  110.515 nF    898.0 kHz  (0,2)  switches  3
  { 0x404A7u,  1101,  8997 },  //  9  110.095 nF    899.7 kHz  (2,1)  switches  7
  { 0x20021u,  1031,  9299 },  // 10  103.063 nF    929.9 kHz  (2,0)  switches  3
  { 0x1011Eu,  1009,  9396 },  // 11  100.928 nF    939.6 kHz  (1,2)  switches  6
  { 0x08041u,   987,  9504 },  // 12   98.658 nF    950.4 kHz  (1,1)  switches  3
  { 0x80FFFu,   962,  9623 },  // 13   96.223 nF    962.3 kHz  (2,2)  switches 13
  { 0x80FFBu,   908,  9908 },  // 14   90.771 nF    990.8 kHz  (2,2)  switches 12
  { 0x404E1u,   900,  9949 },  // 15   90.027 nF    994.9 kHz  (2,1)  switches  6
  { 0x80FBFu,   891, 10002 },  // 16   89.073 nF   1000.2 kHz  (2,2)  switches 12
  { 0x80EFFu,   888, 10019 },  // 17   88.772 nF   1001.9 kHz  (2,2)  switches 12
  { 0x80EFBu,   873, 10103 },  // 18   87.302 nF   1010.3 kHz  (2,2)  switches 11
  { 0x80F7Fu,   860, 10181 },  // 19   85.979 nF   1018.1 kHz  (2,2)  switches 12
  { 0x80BDFu,   847, 10255 },  // 20   84.737 nF   1025.5 kHz  (2,2)  switches 11
  { 0x80EBFu,   845, 10271 },  // 21   84.477 nF   1027.1 kHz  (2,2)  switches 11
  { 0x80F7Bu,   838, 10309 },  // 22   83.846 nF   1030.9 kHz  (2,2)  switches 11
  { 0x80F3Fu,   836, 10324 },  // 23   83.613 nF   1032.4 kHz  (2,2)  switches 11
  { 0x80FE7u,   818, 10436 },  // 24   81.826 nF   1043.6 kHz  (2,2)  switches 11
  { 0x80BDBu,   783, 10667 },  // 25   78.312 nF   1066.7 kHz  (2,2)  switches 10
  { 0x80ADFu,   779, 10696 },  // 26   77.893 nF   1069.6 kHz  (2,2)  switches 10
  { 0x400C7u,   766, 10783 },  // 27   76.647 nF   1078.3 kHz  (2,1)  switches  6
  { 0x80ADBu,   757, 10852 },  // 28   75.672 nF   1085.2 kHz  (2,2)  switches  9
  { 0x80E3Bu,   747, 10922 },  // 29   74.699 nF   1092.2 kHz  (2,2)  switches  9
  { 0x80FA7u,   743, 10950 },  // 30   74.326 nF   1095.0 kHz  (2,2)  switches 10
  { 0x10147u,   724, 11091 },  // 31   72.441 nF   1109.1 kHz  (1,2)  switches  6
  { 0x80F67u,   719, 11135 },  // 32   71.870 nF   1113.5 kHz  (2,2)  switches 10
  { 0x1001Au,   704, 11250 },  // 33   70.407 nF   1125.0 kHz  (1,2)  switches  4
  { 0x80BC7u,   703, 11261 },  // 34   70.279 nF   1126.1 kHz  (2,2)  switches  9
  { 0x80B9Eu,   696, 11317 },  // 35   69.584 nF   1131.7 kHz  (2,2)  switches  9
  { 0x80F27u,   692, 11346 },  // 36   69.222 nF   1134.6 kHz  (2,2)  switches  9
  { 0x80A9Eu,   669, 11541 },  // 37   66.900 nF   1154.1 kHz  (2,2)  switches  8
  { 0x80FE1u,   644, 11766 },  // 38   64.373 nF   1176.6 kHz  (2,2)  switches  9
  { 0x80F61u,   608, 12111 },  // 39   60.753 nF   1211.1 kHz  (2,2)  switches  8
  { 0x40086u,   583, 12360 },  // 40   58.330 nF   1236.0 kHz  (2,1)  switches  4
  { 0x8035Fu,   560, 12618 },  // 41   55.972 nF   1261.8 kHz  (2,2)  switches  9
  { 0x10106u,   559, 12630 },  // 42   55.862 nF   1263.0 kHz  (1,2)  switches  4
  { 0x8035Bu,   550, 12724 },  // 43   55.039 nF   1272.4 kHz  (2,2)  switches  8
  { 0x80B86u,   546, 12779 },  // 44   54.567 nF   1277.9 kHz  (2,2)  switches  7
  { 0x400C1u,   541, 12829 },  // 45   54.144 nF   1282.9 kHz  (2,1)  switches  4
  { 0x80CE7u,   524, 13038 },  // 46   52.421 nF   1303.8 kHz  (2,2)  switches  9
  { 0x10141u,   520, 13090 },  // 47   52.010 nF   1309.0 kHz  (1,2)  switches  4
  { 0x40421u,   518, 13121 },  // 48   51.765 nF   1312.1 kHz  (2,1)  switches  4
  { 0x80BC1u,   509, 13233 },  // 49   50.886 nF   1323.3 kHz  (2,2)  switches  7
  { 0x80CA7u,   507, 13257 },  // 50   50.706 nF   1325.7 kHz  (2,2)  switches  8
  { 0x8031Eu,   502, 13319 },  // 51   50.231 nF   1331.9 kHz  (2,2)  switches  7
  { 0x80CE1u,   460, 13921 },  // 52   45.985 nF   1392.1 kHz  (2,2)  switches  7
  { 0x808C7u,   422, 14528 },  // 53   42.221 nF   1452.8 kHz  (2,2)  switches  7
  { 0x80347u,   420, 14565 },  // 54   42.009 nF   1456.5 kHz  (2,2)  switches  7
  { 0x8021Au,   413, 14686 },  // 55   41.317 nF   1468.6 kHz  (2,2)  switches  5
  { 0x80886u,   360, 15735 },  // 56   35.994 nF   1573.5 kHz  (2,2)  switches  5
  { 0x80306u,   358, 15768 },  // 57   35.840 nF   1576.8 kHz  (2,2)  switches  5
  { 0x808C1u,   344, 16106 },  // 58   34.355 nF   1610.6 kHz  (2,2)  switches  5
  { 0x80341u,   342, 16139 },  // 59   34.215 nF   1613.9 kHz  (2,2)  switches  5
  { 0x80C21u,   334, 16339 },  // 60   33.382 nF   1633.9 kHz  (2,2)  switches  5
};

// step func gen
const uint8_t  STEP_PIN      = 53;
const uint32_t STEP_R_OHMS   = 100000UL; // External resistor val
const uint16_t STEP_HALF_MS  = 250;        // 2 Hz, 50 % duty

bool     squareRunning = false;
bool     pinLevel      = false;
uint32_t lastEdge      = 0;

// config
uint8_t  currentStep = 0;
uint32_t lastChange  = 0;
bool     paused      = false;

char     inputBuffer[12];
uint8_t  inputLength = 0;
uint32_t lastInput   = 0;
const uint16_t INPUT_TIMEOUT_MS = 1500;

// helpers
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

// step
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

// ======================================loop========================
void loop() {
  handleSerial();
  serviceStep();

  if (!paused && (millis() - lastChange) >= STATE_HOLD_MS) {
    advance();
  }
}

// state
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

    if (input == ' ' || input == '\t') continue;

    if (input == '?') {
      dispatchInput();
      printStatus();
      continue;
    }

    dispatchInput();   // newline, carriage return or anything else
  }

  if (inputLength > 0 && (millis() - lastInput) > INPUT_TIMEOUT_MS) {
    dispatchInput();
  }
}
