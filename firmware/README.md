# Color Vision — ESP32 LED Firmware

ColorHub（Cloudflare Durable Object）にWebSocket接続し、Color Visionが抽出した色パレットをWS2812B LEDに描画するファームウェア。

```
Camera → Python解析 → ColorHub (wss://.../ws) → ESP32 → WS2812B (144 LED)
```

## セットアップ手順

### 1. Arduino IDEの準備（Macで一度だけ）

1. [Arduino IDE](https://www.arduino.cc/en/software) をインストール
2. **ESP32ボード定義を追加**
   - `設定` → `追加のボードマネージャのURL` に以下を追加:
     ```
     https://espressif.github.io/arduino-esp32/package_esp32_index.json
     ```
   - `ツール` → `ボード` → `ボードマネージャ` で「**esp32** by Espressif Systems」をインストール
3. **ライブラリをインストール**（`ツール` → `ライブラリを管理`）
   - `FastLED`
   - `ArduinoJson`（v7系）
   - `WebSockets`（by Markus Sattler）

### 2. 配線（実機確認済みの構成）

| ESP32 | LEDリング | 備考 |
|---|---|---|
| 5V | 赤線（5V） | |
| GND | 黒線（GND） | |
| **GPIO13** | 緑線（Data In） | DevKitC V4はブレッドボードで片側しか空かないため、5V/GNDと同じ側の13を使用 |

- テープの**入力（DI）側**のメスJSTコネクタの穴に、オス-オスジャンパーのピンを直挿しできる
- ⚠️ 隣の**GPIO12は使用禁止**（起動設定に関わるstrappingピン）
- 詳細な手順・トラブルシュートは `doc/LED_ESP32_SETUP.md`、色マッピング仕様は `doc/COLOR_MAPPING.md` を参照

### 3. スケッチの設定

`colorvision_led/colorvision_led.ino` の冒頭「設定」セクションを書き換える:

| 定数 | 内容 |
|---|---|
| `WIFI_SSID` / `WIFI_PASS` | 接続するWiFi |
| `WS_HOST` | Workerのドメイン（例: `color-vision-worker.color-vision.workers.dev`） |
| `NUM_LEDS` | LEDの個数（現在144。**個数が変わったらここだけ変更**） |
| `DATA_PIN` | データ線をつないだGPIO（実機構成では**13**） |
| `MAX_BRIGHTNESS` | 輝度上限。USB給電なら80以下推奨 |

描画はpercentage比率ベースなのでLED個数に依存しない。60個でも300個でも `NUM_LEDS` の変更だけで動く。

### 4. 書き込み

1. ESP32をUSBケーブルでMacに接続
2. `ツール` → `ボード` → `ESP32 Dev Module` を選択
3. `ツール` → `Partition Scheme` → **`Huge APP (3MB No OTA/1MB SPIFFS)`** を選択
   - これをしないとTLS込みのビルド（約1.4MB）が入らず `Sketch too big` エラーになる
4. `ツール` → `ポート` で `/dev/cu.usbserial-...` 等を選択
   - ポートが出ない場合はUSBドライバ（CP210x or CH340）のインストールが必要
   - **番号は挿すUSBポートで変わる**（例: -130 → -310）。エラー時は選び直す
5. `→`（書き込み）ボタン
6. シリアルモニタ（115200 baud）で接続ログを確認

### 5. 動作確認

**A. 手動テスト（カメラ不要・一番手軽）**

wscatでColorHubに直接パレットを送る:

```bash
npm i -g wscat
wscat -c wss://color-vision-worker.color-vision.workers.dev/ws
# 接続後、以下を貼り付けて送信 → LEDが赤50%/青50%に光れば成功
{"mode":"palette","dominant":[255,0,0],"colors":[{"rgb":[255,0,0],"percentage":50},{"rgb":[0,0,255],"percentage":50}]}
```

**B. 本番構成（カメラ連動）**

```bash
cd analyzer
COLORHUB_WS_URL=wss://color-vision-worker.color-vision.workers.dev/ws python main.py
```

フロントエンドを開いてカメラを起動すると、視界の色がLEDにリアルタイム反映される。

## 複数台・リモート同時投影

このファームウェアを書き込んだESP32を増やすだけ。全台が同じ `/ws` に接続し、同じ色で同期して光る。拠点ごとに必要なのは「ESP32 + LED + USB電源 + WiFi」のみ（PC不要）。

## トラブルシューティング

| 症状 | 原因・対処 |
|---|---|
| WiFiに繋がらない | キャプティブポータル（同意画面）付きWiFiはESP32が突破できない → テザリング等を使う |
| 接続するがLEDが光らない | データ線がDI（入口）側か確認 / `COLOR_ORDER` を `RGB` に変えてみる |
| 色が化ける・チラつく | 信号線が長い場合は300〜500Ωの抵抗をデータ線に挟む / GNDの共通化を確認 |
| 途中までしか光らない | 電力不足 → `MAX_BRIGHTNESS` を下げるか外部5V電源を使う |
