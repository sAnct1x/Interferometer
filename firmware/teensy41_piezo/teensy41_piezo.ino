// Phase 1b: bit-bang SPI to DAC8562 (breadboard-safe). No HV amp, no piezo.
//
// Wiring (Teensy 4.1 3.3 V logic, not 5 V tolerant):
//   GND  -> DAC GND
//   3.3V -> DAC VCC / AVDD
//   11   -> DIN
//   13   -> SCLK
//   10   -> SYNC
//   LDAC -> DAC GND (jumper on the module)
//   CLR  -> DAC VCC (jumper on the module)
//
// On boot: both outputs 0 V (safe park, no HV amp / no stacks).
// TEST = 1.000 V / 2.000 V bring-up. Mid-bias later is 1.25 V / 1.25 V
// (37.5 V after the amp). See docs/BENCH_CONSTANTS.md.

#include <stdlib.h>

const char *kFwVersion = "0.4.0";

const uint8_t kPinSync = 10;
const uint8_t kPinDin = 11;
const uint8_t kPinSclk = 13;

const int kVfsMv = 2500;
const int kTestA_mV = 1000;
const int kTestB_mV = 2000;

static int g_mv[2] = {0, 0};
static bool g_clamped = false;

// DAC8562: 24-bit frame, sample DIN on falling SCLK, SCLK idle low.
static void dacWrite(uint8_t cmd, uint16_t data) {
  uint32_t frame = ((uint32_t)cmd << 16) | data;

  digitalWrite(kPinSclk, LOW);
  digitalWrite(kPinSync, LOW);
  delayMicroseconds(2);

  for (int i = 23; i >= 0; --i) {
    digitalWrite(kPinDin, (frame >> i) & 1);
    delayMicroseconds(2);
    digitalWrite(kPinSclk, HIGH);
    delayMicroseconds(2);
    digitalWrite(kPinSclk, LOW);
    delayMicroseconds(2);
  }

  delayMicroseconds(2);
  digitalWrite(kPinSync, HIGH);
  digitalWrite(kPinDin, LOW);
  delayMicroseconds(10);
}

static uint16_t mvToCode(int mv) {
  if (mv < 0) {
    mv = 0;
  }
  if (mv > kVfsMv) {
    mv = kVfsMv;
  }
  return (uint16_t)((uint32_t)mv * 65535UL / (uint32_t)kVfsMv);
}

static int setChannel(int axis, int mv) {
  g_clamped = (mv < 0 || mv > kVfsMv);
  if (mv < 0) {
    mv = 0;
  }
  if (mv > kVfsMv) {
    mv = kVfsMv;
  }
  g_mv[axis] = mv;
  uint8_t cmd = (axis == 0) ? 0x18 : 0x19;
  dacWrite(cmd, mvToCode(mv));
  return mv;
}

static void dacInit() {
  pinMode(kPinSync, OUTPUT);
  pinMode(kPinDin, OUTPUT);
  pinMode(kPinSclk, OUTPUT);
  digitalWrite(kPinSync, HIGH);
  digitalWrite(kPinDin, LOW);
  digitalWrite(kPinSclk, LOW);

  delay(5);
  dacWrite(0x28, 0x0001);  // software reset
  delay(5);
  dacWrite(0x20, 0x0003);  // power up A and B
  delayMicroseconds(50);
  dacWrite(0x38, 0x0001);  // enable internal 2.5 V ref
  delayMicroseconds(50);
  dacWrite(0x02, 0x0003);  // gain = 1 on both
  delayMicroseconds(50);
  setChannel(0, 0);
  setChannel(1, 0);
}

void setup() {
  dacInit();
  Serial.begin(115200);
  while (!Serial && millis() < 3000) {
  }
  Serial.print("READY ");
  Serial.println(kFwVersion);
}

void loop() {
  if (!Serial.available()) {
    return;
  }

  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) {
    return;
  }

  if (line.equalsIgnoreCase("PING")) {
    Serial.print("PONG ");
    Serial.println(kFwVersion);
    return;
  }

  if (line.equalsIgnoreCase("GET")) {
    Serial.print("STATUS ");
    Serial.print(g_mv[0]);
    Serial.print(' ');
    Serial.print(g_mv[1]);
    Serial.print(' ');
    Serial.println(g_clamped ? 1 : 0);
    return;
  }

  if (line.equalsIgnoreCase("TEST") || line.equalsIgnoreCase("INIT")) {
    dacWrite(0x20, 0x0003);
    dacWrite(0x38, 0x0001);
    dacWrite(0x02, 0x0003);
    setChannel(0, kTestA_mV);
    setChannel(1, kTestB_mV);
    Serial.println("OK TEST 1000 2000");
    return;
  }

  if (line.equalsIgnoreCase("STOP")) {
    setChannel(0, 0);
    setChannel(1, 0);
    Serial.println("OK STOP");
    return;
  }

  if (line.equalsIgnoreCase("CLR")) {
    setChannel(0, 0);
    setChannel(1, 0);
    Serial.println("OK CLR");
    return;
  }

  if (line.startsWith("SET ") || line.startsWith("set ")) {
    const char *p = line.c_str() + 4;
    char *end = nullptr;
    long axis = strtol(p, &end, 10);
    long mv = strtol(end, nullptr, 10);
    if (axis != 0 && axis != 1) {
      Serial.println("ERR axis");
      return;
    }
    int applied = setChannel((int)axis, (int)mv);
    Serial.print("OK ");
    Serial.print(axis);
    Serial.print(' ');
    Serial.println(applied);
    return;
  }

  Serial.println("ERR unknown");
}
