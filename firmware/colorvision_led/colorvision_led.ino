/**
 * Color Vision — LED Firmware (ESP32 + WS2812B)
 *
 * ColorHub (Cloudflare Durable Object) にWebSocket接続し、
 * 受信した色パレットをLEDリング/テープに描画する。
 *
 * 必要ライブラリ（Arduino IDEのライブラリマネージャからインストール）:
 *   - FastLED
 *   - ArduinoJson (v7)
 *   - WebSockets (by Markus Sattler / arduinoWebSockets)
 *
 * 配線:
 *   ESP32 5V   → LED 赤線（5V）
 *   ESP32 GND  → LED 黒線（GND）
 *   ESP32 GPI13 → LED 緑線（Data In）
 */

#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <FastLED.h>

// ================================================================
// 設定 — 環境に合わせてここだけ書き換える
// ================================================================

// --- WiFi ---
// 認証情報は secrets.h に記述（secrets.example.h をコピーして作成）
#include "secrets.h"

// --- ColorHub (Cloudflare Worker) ---
const char* WS_HOST = "color-vision-worker.color-vision.workers.dev";
const uint16_t WS_PORT = 443;   // wss://
const char* WS_PATH = "/ws";

// --- LED ---
// LEDの個数はここを変えるだけ。描画はpercentage比率ベースなので
// 60個でも144個でも300個でもコード変更は不要
#define NUM_LEDS 144
#define DATA_PIN 13
#define LED_TYPE WS2812B
#define COLOR_ORDER GRB

// --- 電力・輝度制限 ---
// USB給電(5V/2A)を想定した安全設定。外部電源を使う場合は引き上げ可
#define MAX_BRIGHTNESS 20       // 0〜255（80 ≒ 全力の31%）
#define MAX_MILLIAMPS 400      // FastLEDによる電力キャップ（mA）

// --- 演出 ---
#define FADE_AMOUNT 40          // 色遷移の速さ 0〜255（大きいほど速い）
#define FRAME_INTERVAL_MS 20    // 描画更新間隔（50fps）

// ================================================================

CRGB leds[NUM_LEDS];        // 現在表示中の色
CRGB target[NUM_LEDS];      // 目標色（受信したパレット）
WebSocketsClient webSocket;
unsigned long lastFrame = 0;

// ----------------------------------------------------------------
// パレット描画: colors[] の percentage 比率でLEDを帯状に塗り分ける
// 累積比率で境界を計算するため、丸め誤差で隙間や溢れが出ない
// ----------------------------------------------------------------
void setPaletteTarget(JsonArray colors) {
  if (colors.size() == 0) return;

  int start = 0;
  float cumPct = 0;
  CRGB last = CRGB::Black;

  for (JsonObject c : colors) {
    JsonArray rgb = c["rgb"];
    if (rgb.size() < 3) continue;
    CRGB col(rgb[0].as<uint8_t>(), rgb[1].as<uint8_t>(), rgb[2].as<uint8_t>());
    last = col;

    cumPct += c["percentage"].as<float>();
    int end = (int)(cumPct / 100.0f * NUM_LEDS + 0.5f);
    if (end > NUM_LEDS) end = NUM_LEDS;

    for (int i = start; i < end; i++) target[i] = col;
    start = end;
  }

  // percentage合計が100に満たない分は最後の色で埋める
  for (int i = start; i < NUM_LEDS; i++) target[i] = last;
}

// ----------------------------------------------------------------
// 受信JSONのディスパッチ（LED_RD.md セクション7のモード設計に対応）
// 今はpaletteのみ実装。matrix / reactive は将来ここに追加する
// ----------------------------------------------------------------
void handleMessage(uint8_t* payload, size_t length) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    Serial.printf("[json] parse error: %s\n", err.c_str());
    return;
  }

  const char* mode = doc["mode"] | "palette";

  if (strcmp(mode, "palette") == 0) {
    setPaletteTarget(doc["colors"].as<JsonArray>());
  } else {
    Serial.printf("[json] unknown mode: %s\n", mode);
  }
}

// ----------------------------------------------------------------
// WebSocketイベント
// ----------------------------------------------------------------
void onWebSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.printf("[ws] connected: wss://%s%s\n", WS_HOST, WS_PATH);
      break;
    case WStype_DISCONNECTED:
      Serial.println("[ws] disconnected (auto-reconnect enabled)");
      break;
    case WStype_TEXT:
      handleMessage(payload, length);
      break;
    case WStype_ERROR:
      Serial.println("[ws] error");
      break;
    default:
      break;
  }
}

// ----------------------------------------------------------------
void connectWiFi() {
  Serial.printf("[wifi] connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\n[wifi] connected. IP: %s\n", WiFi.localIP().toString().c_str());
}

void setup() {
  Serial.begin(115200);
  delay(500);

  FastLED.addLeds<LED_TYPE, DATA_PIN, COLOR_ORDER>(leds, NUM_LEDS);
  FastLED.setBrightness(MAX_BRIGHTNESS);
  FastLED.setMaxPowerInVoltsAndMilliamps(5, MAX_MILLIAMPS);
  fill_solid(target, NUM_LEDS, CRGB::Black);

  // 起動時セルフテスト: 赤→緑→青と点灯（配線・COLOR_ORDER確認用）
  // 「赤」と表示されるべき瞬間に別の色が出たら COLOR_ORDER を変更する
  const CRGB testColors[] = { CRGB::Red, CRGB::Green, CRGB::Blue };
  for (auto& c : testColors) {
    fill_solid(leds, NUM_LEDS, c);
    FastLED.show();
    delay(400);
  }
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  FastLED.show();

  // fill_solid(target, NUM_LEDS, CRGB(255, 0, 255));  // デバッグ用: 接続できていれば常時薄紫に光る

  connectWiFi();

  // wss://（TLS）でColorHubに接続
  webSocket.beginSSL(WS_HOST, WS_PORT, WS_PATH);
  webSocket.onEvent(onWebSocketEvent);
  webSocket.setReconnectInterval(3000);
  // 15秒ごとにping、3秒以内にpongがなければ切断扱い（×2回で再接続）
  webSocket.enableHeartbeat(15000, 3000, 2);
}

void loop() {
  // WiFiが落ちたら再接続（会場WiFi対策）
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[wifi] lost. reconnecting...");
    WiFi.reconnect();
    delay(1000);
    return;
  }

  webSocket.loop();

  // 一定間隔で現在色→目標色へ滑らかに遷移させて描画
  unsigned long now = millis();
  if (now - lastFrame >= FRAME_INTERVAL_MS) {
    lastFrame = now;
    for (int i = 0; i < NUM_LEDS; i++) {
      leds[i] = blend(leds[i], target[i], FADE_AMOUNT);
    }
    FastLED.show();
  }
}
