# マルチ拠点構成 — 設計・環境仕様

> 東京・金沢の2拠点でカメラ映像から色を抽出し、互いの色をLEDで光らせ合う構成の検討まとめ。
> ハードウェアのセットアップは `doc/LED_ESP32_SETUP.md`、色マッピングは `doc/COLOR_MAPPING.md` を参照。

---

## 目次

1. [全体アーキテクチャ](#1-全体アーキテクチャ)
2. [Cloudflare Tunnel vs Durable Objects](#2-cloudflare-tunnel-vs-durable-objects)
3. [クロス表示（東京⇄金沢）の実現方法](#3-クロス表示東京金沢の実現方法)
4. [拠点デバイス構成の選択肢](#4-拠点デバイス構成の選択肢)
5. [最小構成: ESP32-CAM + クラウド解析](#5-最小構成-esp32-cam--クラウド解析)
6. [解析サーバーのデプロイ先](#6-解析サーバーのデプロイ先)
7. [電源・無人運用](#7-電源無人運用)
8. [必要な改修リスト](#8-必要な改修リスト)

---

## 1. 全体アーキテクチャ

全クライアントが Cloudflare Durable Object（`worker/src/colorHub.ts` の ColorHub）に接続するスター型。ColorHub は「送信者以外の全員にブロードキャスト」する中継ハブ。

```
【東京】                                        【金沢】
カメラ → 解析（Python K-means）                  カメラ → 解析
   │                                              │
   └──── palette JSON ──→ ColorHub ←── palette JSON ────┘
                        （Durable Object）
   ┌──────────────────────┴──────────────────────┐
   ↓                                              ↓
東京のLED（金沢の色を表示）              金沢のLED（東京の色を表示）
```

役割分担の原則: **色を「決める」のは解析側（Python）、LED側（ESP32/Pi）は「言われた通りに描く」だけ。**

---

## 2. Cloudflare Tunnel vs Durable Objects

### 根本的な違い

- **Tunnel = 土管**: Pi 内のサーバーを外部公開するだけの通信路。サーバー本体は Pi。
- **Durable Objects = 集会所**: クラウド常駐の「プログラム＋状態」。全員がそこに接続しに行く。

### 比較表

| 観点 | Tunnel | Durable Objects |
|---|---|---|
| 本体の所在 | Pi（落ちたら全滅） | クラウド（常時稼働） |
| 接続形態 | 相手のURLに直接（メッシュ） | 1つのURLに集約（スター型） |
| ブロードキャスト | Python側に自分で実装 | ColorHub が実装済み |
| ロジック追加（認証・間引き・最終色の再送） | 全部 Pi 側に書く | DO 側に書ける |
| 拠点・デバイス追加 | 各自が各URLを知る必要 | URL 1つ教えるだけ |
| Pi側の設定 | cloudflared 導入 + config + systemd | WS接続先URLのみ |
| 費用 | 無料 | 従来 $5/月（SQLiteバックエンドDOは無料プラン可） |

### DO が必要になる条件

「相互だから」ではなく **「中心にできる1台が存在しないから」**。

1. 対等な送信者が複数いる（東京も金沢も色を送る側）
2. どの Pi が落ちても他が巻き添えにならないことが必要
3. 接続デバイス数が増える（ESP32追加・拠点追加が URL 1つで済む）
4. 中間に状態やロジックが欲しい（最終色を新規接続に即送る等）

逆に「東京 Pi 1台が唯一の色ソースで他は受け取るだけ」なら Tunnel で十分。
本プロジェクトの構想（2拠点が互いに送り合う）は条件 1・2 に該当するため **DO を採用**。すでに ColorHub が実装済みであり、Tunnel に書き直すメリットはほぼない。

---

## 3. クロス表示（東京⇄金沢）の実現方法

現状の ColorHub は「送信者以外の全員に転送」なので、2拠点なら自然と相手のデータだけを受け取る。ただし ESP32 もハブに直接つながるため、**送信元タグがないと両拠点のデータが混ざる**。

### 解決: source タグ + 受信側フィルタ

**① Python側（`analyzer/hub.py`）— source を付けて送信**

```python
# 環境変数 LOCATION=tokyo / kanazawa を各拠点に設定
{"mode": "palette", "source": "tokyo", "colors": [...]}
```

**② ESP32側（`firmware/colorvision_led/colorvision_led.ino`）— 対象拠点だけ拾う**

```cpp
const char* LISTEN_SOURCE = "kanazawa";  // 東京のESP32は金沢を聴く

void handleMessage(...) {
  const char* src = doc["source"] | "";
  if (strcmp(src, LISTEN_SOURCE) != 0) return;  // 対象外は無視
  setPaletteTarget(doc["colors"].as<JsonArray>());
}
```

ColorHub 自体は**変更不要**（全員に配って受信側が選ぶ方式）。
デバイスが増えたら、接続時に購読先を名乗らせて DO 側でルーティングする方式に発展可能。

---

## 4. 拠点デバイス構成の選択肢

拠点の要件で決まる。決定打は**ヴィジュアライズ投影の有無**（ESP32 には映像出力がない）。

| 拠点でやりたいこと | ESP32のみ | ESP32-CAM | Pi（またはPC） |
|---|---|---|---|
| LEDを光らせる | ○ | ○ | ○（GPIO直結） |
| カメラで映像取得 | × | ○ | ○ |
| K-means解析 | × | ×（別マシン必須） | ○ |
| Nuxtのヴィジュアル投影 | × | × | ○（HDMI出力） |

### パターンA: Pi に集約（投影あり拠点）

```
Pi ─ カメラ（USB or Piカメラ）
   ─ HDMI → プロジェクター（Nuxtヴィジュアル）
   ─ GPIO18 → WS2812B LED（rpi_ws281xライブラリ）
   ─ WiFi → ColorHub
```

- ESP32 は不要になる（Pi の GPIO で直接 LED 駆動）
- Pi 直結の注意点: オンボードオーディオ無効化（`dtparam=audio=off`）、root権限（DMA）、信号レベルは3.3Vで ESP32 と同条件（不安定なら 74AHCT125 レベルシフタ）
- **Pi 3 の性能注意**: カメラ + K-means + Chromium/WebGL の全部載せはギリギリ。投影あり拠点は Pi 4/5 推奨、または解析 fps を 10fps 程度に落とす
- ESP32 を残す意味があるのは「LED を Pi から物理的に離したい場合」（WS2812B のデータ線は実用数mが限界）のみ

### パターンB: ESP32 + LED（表示専用拠点）

カメラなし・投影なしで、他拠点の色で光るだけの拠点。電源に挿すだけで動く。現行ファームのまま使える。

### パターンC: ESP32-CAM + クラウド解析（最小構成・PCなし）

次章参照。

---

## 5. 最小構成: ESP32-CAM + クラウド解析

各拠点に置くのは **ESP32-CAM 1枚 + LED + USB電源のみ**。PC も Pi も置かない。

```
【東京】                          【クラウド】                    【金沢】
ESP32-CAM ──JPEG(WS)──→ ┌─────────────────┐ ←──JPEG(WS)── ESP32-CAM
   │                     │ Python analyzer  │                    │
   │                     │ (K-means解析)     │                    │
 GPIO13 → LED            └───────┬─────────┘             GPIO13 → LED
   ↑                             ↓ source付きJSON                ↑
   └────────── ColorHub (Durable Object) ────────────────────────┘
```

### 成立する理由

`analyzer/main.py` は「WebSocket で JPEG バイナリが来たら解析して返す」だけで送信元を区別しない。**ESP32-CAM は「ブラウザ + PC の代役」としてそのまま刺さる**（analyzer のコード変更ほぼ不要）。

### ハードウェア

| 項目 | 内容 |
|---|---|
| ボード | AI-Thinker ESP32-CAM（OV2640 + PSRAM、¥1,000〜1,500） |
| 書き込み | USB端子がないため ESP32-CAM-MB ベース基板とのセット（¥1,500前後）を推奨 |
| 代替 | XIAO ESP32S3 Sense / M5Stack Timer Camera（USB内蔵、¥2,000〜3,000） |
| LED兼用 | SDカード未使用なら GPIO13 が空く → 1枚で撮影と LED 駆動を兼用可 |
| 電源 | 5V/2A 以上（WiFi送信ピーク約380mA + LED分） |
| ピン注意 | GPIO12 は strapping ピンのため使用しない |

### 性能・帯域

- 撮影: 320×240（QVGA）JPEG、実用 10fps 前後
- 帯域: 1枚 10〜15KB × 10fps ≒ **上り約1Mbps/拠点**
- 遅延: カメラ→クラウド→ColorHub→LED で合計 100〜300ms（LEDのフェード演出には支障なし）

### トレードオフ

- Nuxt のヴィジュアル投影は拠点では不可（別の場所のブラウザから全拠点の色をリモート表示は可能）
- OV2640 は低画質だが色抽出用途には十分
- 現地デバッグ手段が減る（シリアルモニタ用PCがない）→ 展示前検証を入念に
- 費用目安: **1拠点 ¥3,000 前後**（ESP32-CAM + LED + 電源）

---

## 6. 解析サーバーのデプロイ先

### 概念整理（Docker / Cloudflare / ホスティングの関係）

| もの | 正体 | 置き場所 |
|---|---|---|
| `worker/`（ColorHub） | JavaScript | Cloudflare Workers（デプロイ済み） |
| `analyzer/` | Python + OpenCV | **コンテナホスティング**（下表） |
| `analyzer/Dockerfile` | 荷造り指示書（場所ではない） | リポジトリ内。ホスティングがこれを読んでビルド |

Cloudflare Workers は JS/WASM 専用のため **Python + OpenCV の analyzer は動かない**。コンテナが動く別サービスに置く。

### ホスティング候補

| サービス | 費用感 | 特徴 |
|---|---|---|
| Railway / Render | 無料枠〜$5/月 | Dockerfile をそのままデプロイ。一番手軽 |
| Fly.io | 無料枠あり | 東京リージョンあり（レイテンシ有利） |
| さくらVPS等 | ¥600〜/月 | 安定・国内 |
| Cloudflare Containers | Workers有料プラン前提 | 全部Cloudflareに統一できるが、常時WSサーバー用途はRailway等の方が枯れている |

負荷は軽い（1フレーム最大10,000ピクセルのK-means）。2拠点×10fps なら最小プランで足りる。

### デプロイ手順（Railway の例）

1. Railway に GitHub リポジトリを接続し、`analyzer/` ディレクトリを指定
2. `Dockerfile` が自動検出され、ビルド → 起動
3. 公開URLが発行される（例: `wss://color-analyzer.up.railway.app`）
4. 環境変数を設定: `COLORHUB_WS_URL=wss://color-vision-worker.color-vision.workers.dev/ws`（+ `LOCATION` 対応後は拠点タグ）
5. ESP32-CAM 側の接続先を手順3のURLにする

---

## 7. 電源・無人運用

### ESP32 の特性

- OSもファイルシステムもない → **電源ON で1秒以内に自動起動**（WiFi接続 → ColorHub接続 → LED点灯まで自動）
- **シャットダウン手順が存在しない**。電源ブチ切りで何も壊れない

### Pi の特性

- 自動起動: systemd に analyzer を登録すれば電源ONで自動起動
- 電源断対策: **OverlayFS（読み取り専用モード）** にすれば SD 書き込みが発生せずブチ切り可（`raspi-config` から設定）

### 無人での点灯スケジュール（2方式）

**方式1: 電源自体を自動化**

| 手段 | 価格 | 特徴 |
|---|---|---|
| タイマーコンセント | ¥1,000前後 | ネット不要。毎日定時ON/OFF |
| スマートプラグ（SwitchBot / Tapo等） | ¥1,500〜2,000 | アプリでスケジュール・遠隔操作 |

Pi は丁寧にやるなら cron で閉館前に `shutdown -h now` → その後プラグOFF（例: 17:55シャットダウン → 18:00プラグOFF）。

**方式2: 電源は切らず消灯だけスケジュール（推奨）**

- デバイスは24時間稼働、ソフトウェアで夜間消灯。電源断ゼロで最も堅牢
- ColorHub 経由で `{"mode": "off"}` を送れば全拠点一斉消灯
- **Cloudflare Workers の Cron トリガー**（毎日18時に消灯、9時に再開）と組み合わせると、クラウドから全拠点の点灯スケジュールを一元管理できる
- 待機消費電力: ESP32 約0.5W / Pi 3 約2〜3W / LED消灯時ほぼゼロ（月数十〜百円程度）

推奨: 方式2 + 保険としてスマートプラグ併用（遠隔強制再起動の手段として）。

### LED電源の注意

現行ファームは `MAX_BRIGHTNESS 20` / `MAX_MILLIAMPS 400` の USB 給電前提。144個フル輝度は理論上8A超のため、**明るく光らせる場合は LED に直接5Vを供給する外部電源（5V/10A程度）が必要**。その際 ESP32/Pi と LED の GND を共通にする。

---

## 8. 必要な改修リスト

| # | 内容 | 対象 | 規模 |
|---|---|---|---|
| 1 | palette JSON に `source` タグ追加（環境変数 `LOCATION`） | `analyzer/hub.py` | 数行 |
| 2 | `LISTEN_SOURCE` フィルタ追加 | `firmware/colorvision_led.ino` | 数行 |
| 3 | analyzer をクラウドにデプロイ | Railway等 | コード変更ほぼ不要 |
| 4 | （パターンC採用時）ESP32-CAM ファームウェア新規作成（撮影 + WS送信 + LED描画統合） | `firmware/` 新規 | 中 |
| 5 | （パターンA採用時）Pi 用 LED 駆動 + ColorHub 受信スクリプト | `analyzer/` 拡張 | 小〜中 |
| 6 | （運用）`{"mode": "off"}` 対応 + Workers Cron トリガー | `firmware` + `worker/` | 小 |
| 7 | WiFi認証情報のハードコード解消（公開リポジトリ化する場合） | `firmware/` | 小 |
