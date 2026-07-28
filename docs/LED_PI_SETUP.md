# Raspberry Pi でカメラ＋LEDを動かす手順

> Pi 1台で「カメラで撮る → 色を抽出する → LEDを光らせる」を完結させる構成のセットアップ。
> ESP32・Arduinoは不要。PythonからGPIOを直接叩いてWS2812Bを駆動する。
>
> ESP32版のセットアップは `docs/LED_ESP32_SETUP.md`、色マッピングの詳細は `docs/COLOR_MAPPING.md` を参照。

---

## 目次

1. [構成と必要なもの](#1-構成と必要なもの)
2. [配線](#2-配線)
3. [OS側の下準備](#3-os側の下準備)
4. [ソフトウェアのインストール](#4-ソフトウェアのインストール)
5. [設定（.env）](#5-設定env)
6. [動作確認](#6-動作確認)
7. [自動起動（systemd）](#7-自動起動systemd)
8. [トラブルシューティング](#8-トラブルシューティング)

---

## 1. 構成と必要なもの

```
Raspberry Pi
├─ カメラ（USBウェブカメラ または CSI接続のPiカメラ）
├─ GPIO18 ──→ WS2812B LED（データ線）
└─ WiFi ──→ ColorHub（他拠点と色を交換）
```

| アイテム | 備考 |
|---|---|
| Raspberry Pi 3 / 4 | **Pi 5は不可**（GPIOチップがRP1に変わり `rpi_ws281x` が動作しない） |
| microSD 16GB以上 | A1/A2 または高耐久タイプ推奨 |
| カメラ | USBウェブカメラが最も簡単。CSIカメラは `picamera2` 経由 |
| WS2812B LEDテープ/リング | 144個想定（`LED_COUNT` で変更可） |
| 電源 | Pi 4はUSB-C 5V/3A。LEDを多数点灯するなら別途5V外部電源 |
| ジャンパー線 | データ線1本＋GND |

Pi 4は発熱するため、常時稼働させるならヒートシンクかファンを付けること。

---

## 2. 配線

| LED側 | Pi側 | 物理ピン |
|---|---|---|
| Data In（緑線） | GPIO18 | 12番 |
| GND（黒線） | GND | 6番など |
| 5V（赤線） | 5V | 2番/4番 ※下記注意 |

**注意点**

- **Piの5Vピンから取れるのは1A程度まで。** LED 20〜30個の低輝度なら可。144個を明るく光らせるなら**5V外部電源をLEDに直結**し、**GNDだけPiと共通にする**
- データ線には **330〜470Ωの抵抗**を直列に入れると信号が安定する（必須ではないが推奨）
- 電源入口に **1000µF程度のコンデンサ**を入れると突入電流を吸収できる
- Piの信号は3.3V、WS2812Bの規格上は3.5V以上が必要。多くの場合そのまま動くが、不安定なら **74AHCT125** などのレベルシフタを挟む
- LEDが多い・テープが長い場合は1〜2mごとに5V/GNDを追加給電（**パワーインジェクション**）する。端の方が暗く赤っぽくなるのを防げる

---

## 3. OS側の下準備

`rpi_ws281x` はPWM/DMAを使うため、オンボードオーディオと競合する。無効化が必須。

```bash
sudo nano /boot/firmware/config.txt
```

以下を追記（既に `dtparam=audio=on` があれば `off` に変更）:

```
dtparam=audio=off
```

再起動:

```bash
sudo reboot
```

CSIカメラを使う場合は接続を確認:

```bash
rpicam-hello --list-cameras   # カメラが見えるか
```

USBカメラの場合:

```bash
ls /dev/video*                # video0 等が出ればOK
```

---

## 4. ソフトウェアのインストール

```bash
# 基本パッケージ（OpenCVはapt版の方がPiでは軽量・安定）
sudo apt update
sudo apt install -y python3-opencv python3-numpy python3-sklearn git

# CSIカメラを使う場合のみ
sudo apt install -y python3-picamera2

# LED制御ライブラリとその他の依存
cd ~/color-vision/analyzer
sudo pip3 install -r requirements-pi.txt --break-system-packages
sudo pip3 install websockets python-dotenv --break-system-packages
```

---

## 5. 設定（.env）

```bash
cd ~/color-vision/analyzer
cp .env.example .env
nano .env
```

最低限、以下を確認する。

```bash
# --- 拠点名（クロス表示に必須）---
LOCATION=tokyo

# --- どの拠点の色を自分のLEDに映すか ---
LED_SOURCE=self          # まずは1台で動作確認
# LED_SOURCE=kanazawa    # 2拠点目ができたらクロス表示に

# --- ColorHub（他拠点と繋ぐとき）---
# COLORHUB_WS_URL=wss://color-vision-worker.color-vision.workers.dev/ws

# --- LED ---
LED_COUNT=144
LED_BRIGHTNESS=20        # USB給電なら20〜40に抑える
LED_MAX_MILLIAMPS=400

# --- カメラ ---
CAMERA_BACKEND=auto      # usb / csi を明示してもよい
CAPTURE_FPS=10           # Pi 3なら5〜10、Pi 4なら10〜15
```

**タイムゾーンの確認を忘れないこと。** `HUB_ACTIVE_HOURS` はPiのローカル時刻で判定するため、UTCのままだと9時間ずれる。

```bash
timedatectl                          # Time zone: Asia/Tokyo になっているか
sudo timedatectl set-timezone Asia/Tokyo
```

---

## 6. 動作確認

### ① LEDの配線チェック

```bash
cd ~/color-vision/analyzer
sudo -E python3 capture_pi.py --test
```

赤 → 緑 → 青 の順に全点灯する。**「RED」と表示されている間に赤以外が出たら** `.env` の `LED_COLOR_ORDER` を変更する（`GRB` ↔ `RGB` ↔ `BRG`）。

推定消費電流も表示されるので、電源の余裕を確認できる。

### ② 本番起動

```bash
sudo -E python3 capture_pi.py
```

`LED_SOURCE=self` なら、カメラに写ったものの色がそのまま自分のLEDに出る。カメラの前に赤い物を置いてLEDが赤くなればパイプライン開通。

`sudo -E` の `-E` は環境変数（`.env` 読み込み後の値）を維持するためのオプション。忘れると設定が反映されない。

### ③ 2拠点でのクロス表示

両方のPiで `COLORHUB_WS_URL` を設定し、`LOCATION` と `LED_SOURCE` を入れ違いにする。

| | 東京のPi | 金沢のPi |
|---|---|---|
| `LOCATION` | `tokyo` | `kanazawa` |
| `LED_SOURCE` | `kanazawa` | `tokyo` |

### ④ 表示専用機として使う（カメラなし）

Piを「他拠点の色を映すだけ」のサテライトにする場合。カメラが繋がっていなくても動く。

```bash
CAPTURE_ENABLED=false
COLORHUB_WS_URL=wss://color-vision-worker.color-vision.workers.dev/ws   # 必須
LED_SOURCE=tokyo        # 映したい拠点名。または any（他拠点すべて）
```

`CAPTURE_ENABLED=false` のときは受け取る色がハブしかないため、`COLORHUB_WS_URL` が未設定だとエラーで終了する。また `LED_SOURCE=self` は自分が撮影しないので光らない（警告が出る）。

起動時のログで `Role : display only` と表示されれば表示専用モードで動いている。

---

## 7. 自動起動（systemd）

```bash
sudo nano /etc/systemd/system/colorvision.service
```

```ini
[Unit]
Description=Color Vision (camera + LED)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/pi/color-vision/analyzer
ExecStart=/usr/bin/python3 /home/pi/color-vision/analyzer/capture_pi.py
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now colorvision
sudo systemctl status colorvision      # 起動確認
journalctl -u colorvision -f           # ログをリアルタイム表示
```

これで電源を入れるだけで自動起動する。`Restart=always` によりクラッシュしても自動復帰する。

展示運用では合わせて以下も検討する。

- **OverlayFS（読み取り専用モード）**: `sudo raspi-config` → Performance Options → Overlay File System。SDへの書き込みが発生しなくなり、電源ブチ切りでも壊れない
- **Raspberry Pi Connect**: 遠隔からのログ確認・再起動用（`sudo apt install rpi-connect-lite`）

---

## 8. トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| `Can't open /dev/mem` | root権限がない | `sudo -E` で実行する |
| LEDが全く光らない | オーディオ競合 | `/boot/firmware/config.txt` に `dtparam=audio=off` |
| 色が入れ替わる（赤が緑に） | カラーオーダー違い | `LED_COLOR_ORDER` を `GRB`/`RGB`/`BRG` で試す |
| 最初の数個だけ光る／チラつく | 電源不足・信号品質 | 外部電源＋GND共通化、データ線に330Ω、レベルシフタ |
| 端の方が暗く赤っぽい | 電圧降下 | パワーインジェクション（1〜2mごとに5V/GND追加） |
| `rpi_ws281x` が入らない | Pi 5を使っている | Pi 3/4を使う。Pi 5ならESP32経由に切り替え |
| カメラが見つからない | バックエンド違い | `CAMERA_BACKEND=usb` または `csi` を明示 |
| CSIカメラがcv2で開けない | libcameraスタック | `python3-picamera2` を入れ `CAMERA_BACKEND=csi` |
| 設定が反映されない | 環境変数が渡っていない | `sudo -E` を使う（`-E` が必須） |
| 時間帯制御がずれる | タイムゾーンがUTC | `sudo timedatectl set-timezone Asia/Tokyo` |
| 動作が重い・fpsが出ない | 解析負荷 | `CAPTURE_FPS` を下げる（5程度）。Pi 3では特に有効 |
