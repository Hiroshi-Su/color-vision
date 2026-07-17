/**
 * LED単体テスト（WiFi不使用）
 *
 * 赤→緑→青→白→マゼンタを1秒ずつ、永久に繰り返すだけのスケッチ。
 * ColorVision本体ファームで光らない問題の切り分け用:
 *   - これが安定して光り続ける → 配線・信号レベルはOK。原因はWiFiとの干渉
 *   - これも点いたり消えたりする → 信号レベルまたは接触の問題
 */

#include <FastLED.h>

#define NUM_LEDS 144
#define DATA_PIN 13
#define LED_TYPE WS2812B
#define COLOR_ORDER GRB
#define MAX_BRIGHTNESS 20
#define MAX_MILLIAMPS 400

CRGB leds[NUM_LEDS];

void setup() {
  Serial.begin(115200);
  delay(500);
  FastLED.addLeds<LED_TYPE, DATA_PIN, COLOR_ORDER>(leds, NUM_LEDS);
  FastLED.setBrightness(MAX_BRIGHTNESS);
  FastLED.setMaxPowerInVoltsAndMilliamps(5, MAX_MILLIAMPS);
  Serial.println("[test] LED test start (no WiFi)");
}

void loop() {
  const CRGB colors[] = {
    CRGB::Red, CRGB::Green, CRGB::Blue, CRGB::White, CRGB(255, 0, 255)
  };
  const char* names[] = { "RED", "GREEN", "BLUE", "WHITE", "MAGENTA" };

  for (int i = 0; i < 5; i++) {
    Serial.printf("[test] %s\n", names[i]);
    fill_solid(leds, NUM_LEDS, colors[i]);
    FastLED.show();
    delay(1000);
  }
}
