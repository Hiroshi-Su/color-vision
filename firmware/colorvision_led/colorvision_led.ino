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
// Tunnelモードで検証する場合はここを相手拠点（またはローカルPi）のURLに変える
// 例: WS_HOST = "xxxx.trycloudflare.com" / WS_PATH = "/"
const char* WS_HOST = "color-vision-worker.color-vision.workers.dev";
const uint16_t WS_PORT = 443;   // wss://
const char* WS_PATH = "/ws";

// --- 表示する拠点の選択 ---
// analyzer側で LOCATION（送信元タグ）を設定している場合、
// ここに指定した拠点のデータだけを表示する。
// 例: 東京のESP32に "kanazawa" を指定 → 金沢の色だけで光る（クロス表示）
// "" （空文字）なら全拠点のデータを受け入れる（フィルタなし）
const char* LISTEN_SOURCE = "";

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

// --- マトリクス(matrixモード)配線設定 ---
// 実物のLEDグリッドに合わせてここだけ書き換える。
// ※ NUM_LEDS は MATRIX_WIDTH * MATRIX_HEIGHT 以上にしておくこと
//   （例: 16x16 パネルなら NUM_LEDS を 256 に）
#define MATRIX_WIDTH        144   // 横のLED個数
#define MATRIX_HEIGHT       1     // 縦のLED個数
#define MATRIX_SERPENTINE   true  // true=1行(列)ごとに向きを反転する蛇行配線 / false=毎行同じ向き
#define MATRIX_VERTICAL     false // false=横走り(行ごとに並ぶ) / true=縦走り(列ごとに並ぶ)
// DI(データ入力)を最初につなぐ物理的な角: 0=左上 1=右上 2=左下 3=右下
#define MATRIX_START_CORNER 2     // 左下スタート

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
// マトリクス座標変換: 画面上の論理座標(x=左から, y=上から) を
// 物理的なLEDインデックスに変換する。
//
// 蛇行(サーペンタイン)配線・走行方向・スタート角をパラメータ化しているので、
// 実物のレイアウトが決まったら上部の MATRIX_* を書き換えるだけで対応できる。
// analyzer は「画面そのままの向き(左上原点・行優先)」で送ってくるため、
// 画面の向きの補正はすべてここで吸収する。
// ----------------------------------------------------------------
int xyToIndex(int x, int y) {
  const bool startLeft = (MATRIX_START_CORNER == 0 || MATRIX_START_CORNER == 2);
  const bool startTop  = (MATRIX_START_CORNER == 0 || MATRIX_START_CORNER == 1);

  if (!MATRIX_VERTICAL) {
    // 横走り: 行が積み上がっていく
    int ry = startTop ? y : (MATRIX_HEIGHT - 1 - y);   // スタート辺から数えた行番号
    bool ltr = startLeft;                              // その行が左→右か
    if (MATRIX_SERPENTINE && (ry & 1)) ltr = !ltr;     // 奇数行は反転
    int col = ltr ? x : (MATRIX_WIDTH - 1 - x);
    return ry * MATRIX_WIDTH + col;
  } else {
    // 縦走り: 列が横に並んでいく
    int cx = startLeft ? x : (MATRIX_WIDTH - 1 - x);   // スタート辺から数えた列番号
    bool ttb = startTop;                               // その列が上→下か
    if (MATRIX_SERPENTINE && (cx & 1)) ttb = !ttb;     // 奇数列は反転
    int row = ttb ? y : (MATRIX_HEIGHT - 1 - y);
    return cx * MATRIX_HEIGHT + row;
  }
}

// ----------------------------------------------------------------
// マトリクス描画: pixels[] (左上原点・行優先の [r,g,b] 配列) を
// 配線に合わせてLEDへ割り当てる
// ----------------------------------------------------------------
void setMatrixTarget(JsonArray pixels) {
  if (pixels.size() == 0) return;

  int n = pixels.size();
  for (int i = 0; i < n; i++) {
    int x = i % MATRIX_WIDTH;
    int y = i / MATRIX_WIDTH;
    if (y >= MATRIX_HEIGHT) break;

    JsonArray rgb = pixels[i];
    if (rgb.size() < 3) continue;
    CRGB col(rgb[0].as<uint8_t>(), rgb[1].as<uint8_t>(), rgb[2].as<uint8_t>());

    int idx = xyToIndex(x, y);
    if (idx >= 0 && idx < NUM_LEDS) target[idx] = col;
  }
}

// ----------------------------------------------------------------
// 受信JSONのディスパッチ（LED_RD.md セクション7のモード設計に対応）
// palette（5色帯）と matrix（低解像度映像）に対応。reactive は将来ここに追加する
// ----------------------------------------------------------------
void handleMessage(uint8_t* payload, size_t length) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    Serial.printf("[json] parse error: %s\n", err.c_str());
    return;
  }

  // 拠点フィルタ: LISTEN_SOURCE 指定時は該当拠点のデータ以外を無視する
  if (LISTEN_SOURCE[0] != '\0') {
    const char* src = doc["source"] | "";
    if (strcmp(src, LISTEN_SOURCE) != 0) return;
  }

  const char* mode = doc["mode"] | "palette";

  if (strcmp(mode, "palette") == 0) {
    setPaletteTarget(doc["colors"].as<JsonArray>());
  } else if (strcmp(mode, "matrix") == 0) {
    setMatrixTarget(doc["pixels"].as<JsonArray>());
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
