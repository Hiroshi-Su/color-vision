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
   - 動作確認のうち [⑤ 任意の色を送ってテストする](#-任意の色を送ってテストする) はデバッグ時に便利
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

> **パスについて:** 以下ではリポジトリを `~/app/color-vision`（＝ `/home/<ユーザー名>/app/color-vision`）に clone した前提で書く。これは実機での配置例なので、別の場所に置いた場合は各コマンドの `~/app/color-vision` を自分のパスに読み替える（`cd analyzer && pwd` で確認できる）。systemd と sudoers だけは `~` が使えず絶対パスが必要なので、後述の該当箇所で実パスに合わせて書き換える。

重いライブラリ（OpenCV・picamera2）は **apt版**を使う。pip版はPiでのビルドが重く、picamera2はpipでの導入が事実上困難。

```bash
sudo apt update
sudo apt install -y python3-opencv python3-numpy python3-sklearn

# CSIカメラを使う場合のみ（USBウェブカメラなら不要）
sudo apt install -y python3-picamera2
```

### venvを使う場合（推奨）

**`--system-site-packages` を必ず付ける。** これがないとaptで入れたOpenCV・picamera2がvenvから見えない。

```bash
cd ~/app/color-vision/analyzer
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements-pi.txt websockets python-dotenv
```

実行時は **venvのpythonを絶対パスで指定する。**

```bash
sudo -E ./venv/bin/python capture_pi.py --test
```

`sudo -E python3 ...` と書くと、sudoが `secure_path` でPATHを上書きするため**venvが無効になりシステムのPythonが使われる**（`ModuleNotFoundError: rpi_ws281x` の典型的な原因）。`activate` しているかどうかに関係なく起こるので注意。

`send_test_color.py` はroot不要なので、activateした状態でそのまま実行できる。

### venvを使わない場合

```bash
cd ~/app/color-vision/analyzer
sudo pip3 install -r requirements-pi.txt websockets python-dotenv --break-system-packages
```

以降のコマンドは `sudo -E python3 capture_pi.py` でよい。

---

## 5. 設定（.env）

```bash
cd ~/app/color-vision/analyzer
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
cd ~/app/color-vision/analyzer
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

### ⑤ 任意の色を送ってテストする

カメラや解析を通さず直接色を指定できるツール。**「配線が悪いのか / ハブ接続が悪いのか / 解析が悪いのか」の切り分け**に使う。

```bash
python3 send_test_color.py red              # 色名
python3 send_test_color.py "#ff00ff"        # HEX
python3 send_test_color.py 255,0,255        # RGB
python3 send_test_color.py red:70 blue:30   # 帯グラフ（占有率指定）
python3 send_test_color.py --cycle          # 赤→緑→青→白→消灯を巡回
python3 send_test_color.py --off            # 消灯
python3 send_test_color.py red --source osaka   # 拠点フィルタの確認
python3 send_test_color.py --matrix red     # matrixモードで送る
python3 send_test_color.py --local red      # ローカルのanalyzerに直接送る
```

接続先は `.env` の `COLORHUB_WS_URL`（`--url` で上書き可）。`sudo` は不要。
`wscat` はNode製でPiでは使えないため、その代わりに使う。

受信側が拠点名でフィルタしている場合（ESP32の `LISTEN_SOURCE` / Piの `LED_SOURCE`）は、`--source` をその拠点名に合わせないと光らないので注意。

---

## 6.5 ヴィジュアルも同時に表示する（構成C）

`capture_pi.py` がカメラ・解析・LEDを担当したまま、**ブラウザには描画だけをさせる**構成。
ブラウザからカメラ取得・JPEG圧縮・送信の処理が消えるため、Pi 4でLEDと映像を同時に動かせる。

```
capture_pi.py（カメラ→K-means→LED＋ColorHubへ送信）
                            ↓
          ブラウザ /view（ColorHubから受信 → シェーダー描画のみ）
```

**デスクトップ版のOSが必要**（Lite版にはブラウザがない）。

### Pi側の設定

`.env` に配信先と拠点名を設定する。

```bash
COLORHUB_WS_URL=wss://color-vision-worker.color-vision.workers.dev/ws
LOCATION=tokyo
```

### ブラウザで開くURL

接続先の ColorHub は既定で `NUXT_PUBLIC_COLORHUB_WS_URL`（未設定なら本番のColorHub）。**表示の切り替えはページURLのクエリ（`?key=value`、複数は `&` で連結）で行う**。設定ファイルではなくアドレスバーに直接打ち込む。

| クエリ | 効果 | 例 |
|---|---|---|
| （なし） | 全拠点の色を受信して表示 | `/view` |
| `?source=<拠点名>` | その拠点の色だけ表示（他は無視）。送信側の `LOCATION` と一致させる | `/view?source=kanazawa` |
| `?ui=0` | 左上のステータス表示を隠す（展示・全画面用） | `/view?ui=0` |
| `?smooth=1` | matrixのマス間をなめらかに補間（既定はLED忠実のくっきり表示） | `/view?smooth=1` |
| `?url=wss://...` | 接続先ColorHubを上書き（通常は不要） | `/view?url=wss://...` |

複数まとめる例（金沢の色を・UIなし・なめらか表示で全画面）:

```
https://<Pagesのドメイン>/view?source=kanazawa&ui=0&smooth=1
```

画面左上に `RECEIVING` と受信件数が出る。色が来ない場合はその下に原因のヒントが表示される。

**注意点**

- **HTTPSページからは `wss://` でないと接続できない**（ブラウザのmixed content制限）。ColorHubは `wss://` なので問題ない
- `/view` は保存処理（KV/D1）を行わない。保存は撮影側の責務にしてあるため、重複書き込みが起きない
- `/view` は **palette / matrix 両対応**。届いたモードで自動的に表示を切り替える（palette=シェーダー、matrix=グリッド）。matrixの見た目は既定でくっきり、`?smooth=1` で補間表示
- 開発中は **Macのブラウザで開く**のが最も軽い（Piの負荷ゼロ）。同じURLでどのマシンからでも同じ色が見える

### Pagesへのデプロイ（Macで実行）

```bash
cd frontend
npm run build
npx wrangler pages deploy .output/public
```

Piでビルドする必要はない（Node.jsもnode_modulesも不要）。

---

## 7. 自動起動（systemd）

`rpi_ws281x` がDMAアクセスのためrootを必要とするため、毎回 `sudo` を打つことになる。**systemdに登録すればその手間がなくなり、電源ONで自動起動する。**

リポジトリに用意済みのユニットファイルを使う。

```bash
cd ~/app/color-vision
sudo cp deploy/colorvision.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now colorvision
```

```bash
sudo systemctl status colorvision      # 起動確認
journalctl -u colorvision -f           # ログをリアルタイム表示
sudo systemctl restart colorvision     # .env を変えたら再起動
sudo systemctl stop colorvision        # 手動実行したいとき（GPIOの競合を避ける）
```

`Restart=always` によりクラッシュやWiFi断でも自動復帰する。

**パスが違う場合**は `deploy/colorvision.service` の `WorkingDirectory` と `ExecStart` を書き換える（`pwd` で確認）。

### 開発中にsudoのパスワード入力を省く

systemdを使わず手動で何度も起動し直す場合は、このコマンドだけパスワード不要にできる。

```bash
sudo visudo -f /etc/sudoers.d/colorvision
```

```
admin-user ALL=(root) NOPASSWD: /home/admin-user/app/color-vision/analyzer/venv/bin/python
```

`admin-user` は自分のログインユーザー名に、パスは venv の python の実パスに置き換える（`whoami` と `echo $PWD/venv/bin/python` で確認）。

**注意:** systemdで動かしている間に手動起動すると、同じGPIOを2つのプロセスが叩いて競合する。手動で試すときは先に `sudo systemctl stop colorvision` すること。

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
| venvなのに `ModuleNotFoundError` | sudoがPATHを上書きしvenvが無効 | `sudo -E ./venv/bin/python ...` と絶対パスで指定 |
| venvから `cv2` / `picamera2` が見えない | `--system-site-packages` なしでvenv作成 | venvを作り直す（`python3 -m venv --system-site-packages venv`） |
| 時間帯制御がずれる | タイムゾーンがUTC | `sudo timedatectl set-timezone Asia/Tokyo` |
| 動作が重い・fpsが出ない | 解析負荷 | `CAPTURE_FPS` を下げる（5程度）。Pi 3では特に有効 |
