# Matrix モード実装まとめ

カメラ映像を LED の数に合わせた低解像度グリッド（例 16×16）に落とし、各マスの平均色を
LED にマッピングする「matrix モード」の実装・検証・ローカル確認方法をまとめる。

- 対象日: 2026-07-20
- 状態: 実装・ローカル動作確認済み（未コミット）

---

## 1. 概要

従来の **palette モード**（映像から主要5色を抽出し、横一列の帯としてLEDに表示）に加え、
**matrix モード**（映像を W×H の格子に縮小し、1マス=1LED として2次元パネルに表示）を追加した。

```
カメラ → 解析(analyzer) → ColorHub(Cloudflare) → ESP32 → LED
                  ↑ palette / matrix をモードで切替
```

設計方針は **論理グリッド（analyzer/hub）と物理配線（firmware）の分離**：

- analyzer は配線に一切依存せず「画面そのままの向き（左上原点・行優先）」だけを送る
- 蛇行配線・スタート角などの物理的な変換は firmware 側の `xyToIndex()` に集約

---

## 2. 実装箇所

| ファイル | 変更内容 |
|---|---|
| `analyzer/analyzer.py` | `extract_matrix()` と `_center_crop_to_aspect()` を追加 |
| `analyzer/hub.py` | `build_matrix_payload()` を追加 |
| `analyzer/main.py` | matrix分岐、dotenv読込、ブラウザ返信への matrix 同梱 |
| `analyzer/requirements.txt` | `python-dotenv==1.2.2` を追加 |
| `analyzer/.env.example` | matrix系の設定例（`LED_MODE`/`MATRIX_WIDTH`/`MATRIX_HEIGHT`）を追記 |
| `firmware/colorvision_led/colorvision_led.ino` | `xyToIndex()`・`setMatrixTarget()`・matrix分岐・配線マクロ |
| `frontend/app/composables/useWebSocket.ts` | 型に optional な `matrix` フィールドを追加 |
| `frontend/app/pages/matrix.vue` | **新規** ローカルプレビュー画面 `/matrix` |
| `analyzer/matrix_preview.py` | **新規** Python単体のプレビュー用ツール（開発用・任意） |

---

## 3. データフローと各処理

### 3.1 analyzer — `extract_matrix()`

1. JPEGバイト列をデコード（`cv2.imdecode`）
2. **センタークロップ** — グリッド比（例16:16）に合わせて中央を切り出す。
   比率を揃えてから縮小しないと像が引き伸ばされて歪むため。
3. **平均色で縮小** — `cv2.resize(..., INTER_AREA)`。
   INTER_AREA は縮小時にブロック内の色を平均する補間方式で、
   「1マス = そのブロックの平均色」を実現する核心部分。
4. 出力は左上原点・行優先（row-major）の `W×H` グリッド。
   `pixels[i]` は `(row, col) = (i // W, i % W)` のマスの `[r, g, b]`。

```python
led_frame = cv2.resize(img_rgb, (W, H), interpolation=cv2.INTER_AREA)
# W×H×3。各マスがそのブロックの平均色
```

### 3.2 hub — `build_matrix_payload()`

`extract_matrix()` の結果を LED 向け JSON に変換する。

```json
{ "mode": "matrix", "width": 16, "height": 16, "pixels": [[r,g,b], ...] }
```

### 3.3 main — モード切替と配信

- `LED_MODE=matrix` のとき matrix を解析（`hub` の有無と独立）。
  これにより ColorHub 未接続でもブラウザ側でプレビューできる。
- ブラウザへは常に palette 結果を返し、matrix モード時は `matrix` フィールドを同梱
  （既存フロントは未知フィールドを無視するので後方互換）。
- LED（ESP32）へは `hub` 経由で matrix / palette を配信。

### 3.4 firmware — `xyToIndex()`（物理配線の吸収）

analyzer が送る論理座標（左上原点）を、実際の LED インデックスへ変換する。
配線パラメータを上部マクロに集約：

```c
#define MATRIX_WIDTH        16
#define MATRIX_HEIGHT       16
#define MATRIX_SERPENTINE   true   // 蛇行の有無
#define MATRIX_VERTICAL     false  // 横走り / 縦走り
#define MATRIX_START_CORNER 2      // 0=左上 1=右上 2=左下 3=右下
```

実物レイアウトが決まったら、このマクロを書き換えるだけで対応できる。
**蛇行/非蛇行 × 走行方向 × スタート4角 = 全16通り**を複数解像度で全単射検証済み
（各マスが必ず1つのLEDに1対1対応・抜けや重複なし）。

> ⚠️ 16×16 を使う場合は firmware の `NUM_LEDS` を 256 に上げること（現状144）。
> `setMatrixTarget` は `idx < NUM_LEDS` でガードしているため、
> 144のままだとクラッシュはしないがパネル下部が光らない。

---

## 4. 設定（dotenv）

環境変数は `python-dotenv` で `analyzer/.env` から読み込む（Python界隈の定番構成）。

- `.env` は `.gitignore` 済み（コミットされない）／ `.env.example` はテンプレとしてコミット
- `load_dotenv()` は既存の環境変数を上書きしないため、Docker/CI で環境変数を直接注入する運用とも共存
- `.env` が無くてもエラーにならない

```bash
# analyzer/.env の例
LED_MODE=matrix
MATRIX_WIDTH=16
MATRIX_HEIGHT=16
# COLORHUB_WS_URL=wss://color-vision-worker.color-vision.workers.dev/ws
```

> 実機LEDへ流すには `COLORHUB_WS_URL` が必須（未設定だと ESP32 への転送自体が無効）。
> ブラウザプレビューだけなら不要。

**現在の解像度: 16 × 16 = 256 マス（=256個ぶんのLED/ピクセル）**

---

## 5. ローカルでの確認方法

### 5.1 Nuxt `/matrix`（推奨）

```bash
# 1) analyzer を matrix モードで起動
cd analyzer && venv/bin/python main.py

# 2) フロント起動
cd frontend && npm run dev

# 3) ブラウザで開く
http://localhost:3000/matrix
```

- 上段=カメラ映像 / 下段=16×16グリッド（canvas描画）
- 画面上部に診断パネル（WS接続・カメラ状態・受信フレーム数）
- カメラは同時に1プロセスしか使えないため、`/`（Visualizer）タブは閉じること
- 既存の `/`（palette の Three.js 可視化）は無変更でそのまま動作

### 5.2 Python単体 `matrix_preview.py`（任意・開発用）

ブラウザ/ColorHub/ESP32 を経由せず、Python だけで確認する予備ツール。

```bash
cd analyzer
venv/bin/python matrix_preview.py        # .env の解像度を使用
venv/bin/python matrix_preview.py 32 18  # 解像度を上書き
```

- デスクトップにウィンドウが開く（上段カメラ・下段matrix、`q`で終了）
- macOS のカメラ権限（TCC）が必要。ターミナルアプリ（cmux 等）に
  「システム設定 > プライバシー > カメラ」で許可が必要

---

## 6. プレビュー表示の仕組み（cv2.imshow の原理）

`matrix_preview.py` は画面へ直接描いているのではなく、**macOS 標準のウィンドウAPIを
ライブラリ越しに呼んでいる**。この環境の OpenCV は `GUI: COCOA`／`AVFoundation: YES`。

```
matrix_preview.py            Pythonコード（cv2.imshow を呼ぶ）
   │
cv2 (Pythonバインディング)     C++関数への橋渡し
   │
OpenCV highgui (.dylib)       C++本体。COCOAバックエンド
   │
Cocoa / AppKit               ★macOS純正GUI（NSWindow / NSView）
   │
WindowServer (Quartz)        OSのコンポジタ（全窓を合成）
   │
GPU → ディスプレイ
```

- `cv2.imshow` → OpenCV が内部で `NSWindow`/`NSView` を生成（＝普通のMacアプリの窓と同じ）
- 実際の画面合成は OS の WindowServer が担当。アプリがハードを直接触ることはない
- `cv2.waitKey(1)` は「1ms待つ」だけでなく、OSのイベントループを回して再描画・キー入力を処理
- カメラ `cv2.VideoCapture(0)` も macOS 純正の AVFoundation を呼ぶ → だからカメラ権限が要る

ブラウザ版との違い：Nuxt版は **ブラウザ**が Cocoa/AVFoundation を代理で呼ぶ役、
Python版は **OpenCV** がその役をやっているだけ。確認できる内容（③の縮小まで）は同一。

| 段階 | 補間方式 | 目的 |
|---|---|---|
| 縮小（16×16化） | INTER_AREA | ブロック内を平均して各マスの代表色を作る（本質） |
| 拡大（表示用） | INTER_NEAREST | マスをくっきり見せる（表示のため） |

---

## 7. TODO / 次のステップ

- [ ] 実物レイアウト確定後、firmware の `MATRIX_*` マクロと `NUM_LEDS` を調整
- [ ] 実機（ESP32 + LEDパネル）での点灯テスト（`COLORHUB_WS_URL` 設定）
- [ ] `matrix_preview.py` を残すか削除するか判断
- [ ] 一連の変更をコミット
