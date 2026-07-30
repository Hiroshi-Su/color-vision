# Raspberry Pi セットアップ記録（2026-07-27）

> Raspberry Pi 4 でカメラ→色抽出→WS2812B LED点灯を開通させるまでの実作業記録。
> 踏んだ落とし穴とその解決も残す。汎用の手順書は `docs/LED_PI_SETUP.md`。

**到達点:** LEDのセルフテスト（赤→緑→青）点灯を確認。USBウェブカメラのフレーム取得も確認。
Arduino / ESP32 は使わず、PythonからGPIOを直接駆動する構成。

---

## 目次

1. [構成と使った機材](#1-構成と使った機材)
2. [Step 1: OSイメージの選択](#step-1-osイメージの選択)
3. [Step 2: Imagerのカスタマイズ設定](#step-2-imagerのカスタマイズ設定)
4. [Step 3: SSH鍵（Deploy key）でリポジトリを取得](#step-3-ssh鍵deploy-keyでリポジトリを取得)
5. [Step 4: OS側の下準備](#step-4-os側の下準備)
6. [Step 5: LEDの配線](#step-5-ledの配線)
7. [Step 6: Python環境の構築](#step-6-python環境の構築)
8. [Step 7: 設定ファイル（.env）](#step-7-設定ファイルenv)
9. [Step 8: 動作確認](#step-8-動作確認)
10. [Step 9: sudoを毎回打たなくする](#step-9-sudoを毎回打たなくする)
11. [踏んだ落とし穴まとめ](#踏んだ落とし穴まとめ)
12. [次のステップ](#次のステップ)

---

## 1. 構成と使った機材

```
Raspberry Pi 4
├─ USBウェブカメラ ──→ OpenCVでフレーム取得
├─ GPIO18 ──→ GPIO拡張ボード ──→ WS2812B LED
└─ WiFi ──→（将来）ColorHub で他拠点と色を交換
```

| アイテム | 今回使ったもの | 備考 |
|---|---|---|
| 本体 | Raspberry Pi 4 | **Pi 5は不可**（GPIOチップがRP1に変わり `rpi_ws281x` が動かない）。Pi 3も可 |
| microSD | 16GB | Lite/desktopどちらでも足りる。A1/A2・高耐久推奨 |
| カメラ | USBウェブカメラ | CSIカメラは未入手のため今回はUSB |
| LED | WS2812B（アドレッサブル） | 144個想定 |
| 配線 | GPIO拡張ボード＋ブレッドボード | ジャンパー直挿しでも可 |

**Arduinoは不要。** ArduinoはESP32へ書き込むためのツールなので、Pi構成では登場しない。

---

## Step 1: OSイメージの選択

Raspberry Pi Imager のOS一覧で、**Lite と Full は「Raspberry Pi OS (other)」の中**にある。上位3つはすべてデスクトップ版。

| 用途 | 選ぶもの |
|---|---|
| LEDのみ（投影なし） | `Raspberry Pi OS (other)` → **Lite (64-bit)**（約2.5GB） |
| 投影もする | 一番上の **Raspberry Pi OS (64-bit)**（Recommended, Chromium入り, 約6GB） |
| 選ばない | **Full**（recommended software入り）は展開後10GB超で16GBだと苦しい |

Pi 4なら64bitを選ぶ。OpenCV/numpyが速い。Legacy(Bookworm)は互換性が必要な場合のみ。

**Pi 3で投影までやるのは厳しい**（1GB RAM＋Chromium/WebGL）。Pi 3は「投影しないサテライト」向き。

---

## Step 2: Imagerのカスタマイズ設定

SSHは**有効化しておく**（Lite構成だと画面がないのでSSHなしでは何もできない）。認証はパスワードでも公開鍵でもよい。

同じ画面で以下も設定しておく。

| 項目 | 値 | 理由 |
|---|---|---|
| **タイムゾーン** | **Asia/Tokyo** | `HUB_ACTIVE_HOURS` はローカル時刻で判定するため。UTCのままだと9時間ずれる |
| ホスト名 | `colorvision-tokyo` 等 | 拠点ごとに変えると2台以上でも混乱しない。`ssh user@<name>.local` で繋げる |
| WiFi SSID/パスワード＋国コード(JP) | — | Lite構成では未設定だと起動後に手詰まり |

確認コマンド:

```bash
timedatectl                                   # Time zone: Asia/Tokyo か
sudo timedatectl set-timezone Asia/Tokyo      # 違っていたら
```

---

## Step 3: SSH鍵（Deploy key）でリポジトリを取得

PAT（Personal Access Token）より **Deploy key** の方がこの用途に適している。1リポジトリに限定された鍵なので、機体を撤収したらその鍵だけ無効化すればよい。有効期限もない。

```bash
# Piで鍵を作る（拠点名を入れるとGitHub側で見分けやすい）
ssh-keygen -t ed25519 -C "colorvision-pi-tokyo"
# パスフレーズは空でEnter（systemd自動起動時に入力できないため）

cat ~/.ssh/id_ed25519.pub
```

出力をGitHubの **リポジトリ Settings → Deploy keys → Add deploy key** に貼る。
**「Allow write access」はチェックしない**（Piはpullするだけ）。

```bash
ssh -T git@github.com     # "successfully authenticated" が出れば疎通OK
git clone git@github.com:Hiroshi-Su/color-vision.git ~/app/color-vision
```

**注意点**

- 1つの公開鍵は**1リポジトリにしかDeploy keyとして登録できない**（GitHubの仕様）。2台目のPiには別の鍵を作る（結果的に機体ごとに無効化できるので望ましい）
- **`sudo git pull` はしない。** rootの `~/.ssh` を見に行って鍵が見つからず失敗する。gitは通常ユーザーで実行する

---

## Step 4: OS側の下準備

`rpi_ws281x` はPWM/DMAを使うため、**オンボードオーディオとの競合を切る必要がある。** これを忘れると「プログラムは正常終了するのにLEDが光らない」という状態になり、最もハマりやすい。

```bash
sudo nano /boot/firmware/config.txt
```

追記（既に `dtparam=audio=on` があれば `off` に変更）:

```
dtparam=audio=off
```

```bash
sudo reboot
grep audio /boot/firmware/config.txt    # 再起動後に確認
```

---

## Step 5: LEDの配線

必要なのは3本だけ。**ピン番号（物理）とGPIO番号は別物**なので注意。GPIO18は物理12番。

| LEDの線 | Piの物理ピン | 機能 |
|---|---|---|
| 赤 | 2番（または4番） | 5V |
| 黒 | 6番 | GND |
| 緑 | **12番** | GPIO18（データ） |
| 青 | — | DOUT。数珠つなぎ用なので未接続 |

```bash
pinout      # Piの実際のピン配置図が出る
```

### GPIO拡張ボードを使う場合

拡張ボードの各ラベルは**その真横の行番号**とつながっている。同じ行の空き穴（G〜J）に挿せば導通する。右列の対応:

| 行 | 右列ラベル | 用途 |
|---|---|---|
| 1 | 5V0 | 電源 |
| 2 | 5V0 | |
| 3 | GND | GND |
| 4 | TXD0 | |
| 5 | RXD0 | |
| **6** | **GPIO18** | **データ線** |
| 7 | GND | |

行番号を数え間違えやすいので、挿した穴から真横に視線を動かしてラベルを直接読むのが確実。
外周の `+` / `-` レールは初期状態では何にも繋がっていない（使うなら5V0/GNDから1本ずつ引く）。

### 配線の注意点

- **DIN側（入力側）に繋ぐこと。** 矢印または `DI` / `DO` の印字を確認。逆だと全く光らない
- **5Vを3.3Vピン（1番・17番）に繋がない。** 暗く不安定になる
- データ線に **330〜470Ωの抵抗**を直列に入れると信号が安定する（必須ではない）
- **Piの5Vピンから取れるのは1A程度まで。** 144個を明るく光らせるなら5V外部電源をLEDに直結し、**GNDだけPiと共通**にする
- 長いテープは1〜2mごとに5V/GNDを追加給電（パワーインジェクション）。端が暗く赤っぽくなるのを防ぐ
- 4ピンJSTコネクタはPiのヘッダーに直接刺せない。①JSTピグテール線を買う ②コネクタを切ってジャンパーに直結 ③テープのはんだパッドに直付け のいずれか

---

## Step 6: Python環境の構築

重いライブラリ（OpenCV）は **apt版**を使う。pip版はPiでのビルドが重い。

```bash
sudo apt update
sudo apt install -y python3-opencv python3-numpy python3-sklearn
# CSIカメラを使う場合のみ（USBウェブカメラなら不要）
# sudo apt install -y python3-picamera2
```

`git` は clone できている時点で既に入っているので改めて入れる必要はない。

### venvは `--system-site-packages` 付きで作る

これがないと **aptで入れたOpenCVがvenvから見えない。**

```bash
cd ~/app/color-vision/analyzer
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements-pi.txt websockets python-dotenv
```

確認:

```bash
./venv/bin/python -c "import cv2, numpy, sklearn, rpi_ws281x; print('ok')"
```

### 実行時は venv の python を絶対パスで指定する

```bash
sudo -E ./venv/bin/python capture_pi.py --test     # ○
sudo -E python3 capture_pi.py --test               # ✗ venvが無効になる
```

`sudo` は `secure_path` でPATHを上書きするため、`activate` していても `sudo -E python3` ではシステムのPythonが使われ `ModuleNotFoundError: rpi_ws281x` になる。

---

## Step 7: 設定ファイル（.env）

```bash
cp .env.example .env
nano .env
```

`.env.example` の内容が丸ごとコピーされるが、**間引く必要はない**（`#` 始まりはコメントとして無視される）。値を数か所変えるだけ。

初回テスト用の推奨値:

```bash
CAMERA_BACKEND=usb        # USBカメラと決まっているので明示（autoだとCSIも試しに行く）
LED_COUNT=144             # 実際のLED個数に合わせる
LED_BRIGHTNESS=10         # 初回は控えめに
LED_MAX_MILLIAMPS=300     # Piの5Vピン給電なら安全側に
LED_SOURCE=self           # 自分のカメラの色を自分のLEDに出す
```

`COLORHUB_WS_URL` と `LOCATION` は**コメントのままでよい**。クラウドを使わず単体で動く。

`LED_COUNT` が実際とずれると帯グラフの割り当てがずれる（多すぎ→後半が光らない／少なすぎ→余りが消灯）。セルフテストの全点灯で光らないLEDがあるかで判断できる。

**`.env` はgit管理外**なので、pullで上書きされる心配はない。拠点ごとに設定が違うのでこれは意図通り。

---

## Step 8: 動作確認

### ① カメラの認識

```bash
ls /dev/video*        # /dev/video0 などが出ればOK

./venv/bin/python -c "
import cv2
c = cv2.VideoCapture(0)
ok, f = c.read()
print('captured' if ok else 'failed', f.shape if ok else '')
c.release()
"
```

`captured (480, 640, 3)` のように出れば成功。

**GStreamerの警告が出るのは正常。** OpenCVが先にGStreamerを試して失敗し、V4L2にフォールバックしているだけ。動作に影響はない（`camera_pi.py` で V4L2 を直接指定するよう修正済み）。

```
[ WARN:0@4.294] global cap_gstreamer.cpp:2839 handleMessage OpenCV | GStreamer warning:
Embedded video playback halted; module v4l2src0 reported: Internal data stream error.
```

### ② LEDのセルフテスト

```bash
sudo -E ./venv/bin/python capture_pi.py --test
```

赤→緑→青の順に1秒ずつ全点灯し、推定消費電流も表示される。

```
[test] RED
       estimated current: 113 mA
[test] GREEN
       estimated current: 113 mA
[test] BLUE
       estimated current: 113 mA
[test] done
```

**重要: `--test` は光らなくてもエラーなく完走する。** 目で見て確認すること。

| 見えた結果 | 原因 | 対処 |
|---|---|---|
| 赤→緑→青が正しく点灯 | — | 次へ |
| 色の順が違う（赤が緑に見える等） | カラーオーダー違い | `LED_COLOR_ORDER` を `RGB` / `BRG` に |
| 全く光らない | audio未無効化 or 配線 | `grep audio /boot/firmware/config.txt`、GPIO18の行、DIN側の向き |
| 一部だけ光る | `LED_COUNT` or 電源不足 | 個数を実数に／外部電源 |

### ③ 本番起動

```bash
sudo -E ./venv/bin/python capture_pi.py
```

```
Role        : capture + display
LED source  : self
LED mode    : palette
Capture     : 320x240 @ 10.0fps
```

カメラの前の色がLEDに出れば **カメラ→K-means解析→LED** 開通。`Ctrl+C` で停止（終了時に自動消灯）。

### ④ 任意の色を送ってテスト（切り分け用）

```bash
python3 send_test_color.py red          # 色名
python3 send_test_color.py --cycle      # 赤→緑→青→白→消灯を巡回
python3 send_test_color.py --off        # 消灯
```

`wscat` はNode製でPiでは使えないため、その代替。**ColorHub経由なのでネットワークとハブ接続が必要**（`capture_pi.py --test` はローカル直接なのでネット不要）。`sudo` は不要。

---

## Step 9: sudoを毎回打たなくする

`rpi_ws281x` はDMAアクセスのためrootが必要で、これは避けられない。ただ毎回打つ必要はなくなる。

### 本命: systemdに登録

```bash
cd ~/app/color-vision
sudo cp deploy/colorvision.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now colorvision
```

```bash
sudo systemctl status colorvision      # 起動確認
journalctl -u colorvision -f           # ログをリアルタイム表示
sudo systemctl restart colorvision     # .env を変えたら
sudo systemctl stop colorvision        # 手動実行前に必ず止める
```

電源ONで自動起動し、クラッシュやWiFi断でも5秒後に自動復帰する。

**注意: systemdで動かしている間に手動起動するとGPIOが競合する。** 手動で試すときは先に `stop` する。

調整段階では `enable`（自動起動）は後回しにして、手動起動で詰める方が楽。

### 開発中: パスワード入力だけ省く

```bash
sudo visudo -f /etc/sudoers.d/colorvision
```

```
admin-user ALL=(root) NOPASSWD: /home/admin-user/app/color-vision/analyzer/venv/bin/python
```

`sudo` は付けるがパスワードは聞かれなくなる。なお同じターミナルなら15分間はキャッシュされる。

---

## 踏んだ落とし穴まとめ

| # | 症状・疑問 | 原因 | 解決 |
|---|---|---|---|
| 1 | Lite/Fullがイメージ一覧に見つからない | `Raspberry Pi OS (other)` の中にある | サブメニューを開く |
| 2 | Node.jsは必要？ | 不要。Vueのビルドはローカルで行いPagesにデプロイ、Piはブラウザで見るだけ | 何もしない |
| 3 | Cloudflare Pagesに先に入れる必要がある？ | 不要。Pi単体（`LED_SOURCE=self`）はクラウドなしで完結 | 何もしない |
| 4 | ArduinoをPiに入れる？ | 不要。ArduinoはESP32書き込み用ツール | PythonでGPIOを直接叩く |
| 5 | `apt install ... git` のgitは何のため？ | 不要だった（cloneできている時点で入っている） | 手順から削除 |
| 6 | venvから `cv2` が見えない | `--system-site-packages` なしでvenv作成 | venvを作り直す |
| 7 | venvなのに `ModuleNotFoundError` | sudoが `secure_path` でPATHを上書き | `sudo -E ./venv/bin/python` と絶対パス指定 |
| 8 | `.env` に全部コピーされた | `.env.example` はテンプレート。`#` はコメント | 間引かず値だけ変える |
| 9 | GStreamer警告が出る | OpenCVがGStreamer→V4L2にフォールバック | 無害。V4L2直接指定に修正済み |
| 10 | `send_test_color.py --test` は？ | `--test` は `capture_pi.py` のオプション | 用途が違う2つのスクリプト |
| 11 | LEDが光らないのにテストが成功する | `dtparam=audio=off` 未設定が最頻出 | config.txtに追記して再起動 |
| 12 | 毎回sudoが必要？ | DMAアクセスのため必須 | systemd登録で打たなくなる |

---

## 次のステップ

1. **明るさ調整** — `LED_BRIGHTNESS` を上げる（Piの5Vピン給電なら40程度まで。それ以上は外部電源）
2. **matrixモードを試す** — `LED_MODE=matrix` で低解像度の「動く映像」表示
3. **クラウド接続** — `.env` の `COLORHUB_WS_URL` と `LOCATION` を有効化
4. **2拠点クロス表示** — 東京と金沢で `LOCATION` / `LED_SOURCE` を入れ違いに設定

| | 東京のPi | 金沢のPi |
|---|---|---|
| `LOCATION` | `tokyo` | `kanazawa` |
| `LED_SOURCE` | `kanazawa` | `tokyo` |

5. **展示運用の堅牢化** — OverlayFS（読み取り専用モード）、Raspberry Pi Connect（遠隔ログ確認）、スマートプラグ or 夜間消灯スケジュール

関連資料: `docs/LED_PI_SETUP.md`（汎用手順書） / `docs/MULTI_SITE_ARCHITECTURE.md`（多拠点設計） / `docs/COLOR_MAPPING.md`（色マッピング仕様）
