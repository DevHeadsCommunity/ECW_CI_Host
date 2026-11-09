// SPDX-License-Identifier: MIT
// Arduino UNO R4 WiFi: keep the built-in LED on and emit numbered evidence.
// Serial output verifies the running firmware and its requested GPIO state.
// A camera or external measurement is needed to verify physical light output.

#include <Arduino.h>

static unsigned long sample = 0;
static unsigned long last_sample_ms = 0;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);
  Serial.begin(115200);
  // Do not wait for a USB terminal: the remote capture starts after flashing.
}

void loop() {
  const unsigned long now = millis();
  if (now - last_sample_ms >= 1000) {
    last_sample_ms = now;
    Serial.print("ECW_CI_HOST_SAMPLE ");
    Serial.print(++sample);
    Serial.println(digitalRead(LED_BUILTIN) == HIGH ? " LED=ON" : " LED=OFF");
  }
}
