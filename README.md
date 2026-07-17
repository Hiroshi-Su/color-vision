# 🎨 Color Vision — カメラ色抽出リアルタイム可視化

> カメラ映像からリアルタイムに色を抽出し、Three.js + GLSLシェーダーで可視化するWebアプリケーション

---

## 目次

1. [プロジェクト概要](#1-プロジェクト概要)
2. [技術スタック](#2-技術スタック)
3. [アーキテクチャ](#3-アーキテクチャ)
4. [ディレクトリ構成](#4-ディレクトリ構成)
5. [環境構築手順](#5-環境構築手順)
6. [各レイヤーの役割](#6-各レイヤーの役割)
7. [データフロー](#7-データフロー)
8. [データベース設計](#8-データベース設計)
9. [保存戦略](#9-保存戦略)
10. [API仕様](#10-api仕様)
11. [デプロイ](#11-デプロイ)
12. [今後の拡張アイデア](#12-今後の拡張アイデア)

---

## 1. プロジェクト概要

### 目的

ブラウザのカメラ映像をリアルタイムで解析し、映像内の主要色（最大5色）を抽出。
抽出した色データをGLSLシェーダーに渡してインタラクティブに可視化する。
解析結果はCloudflare D1に時系列で保存し、履歴の振り返りや色変化のタイムライン表示にも活用する。

### 主な機能

- ブラウザカメラからのリアルタイム映像取得
- Python（K-means）による主要5色 + 占有率の抽出
- Three.js + GLSLシェーダーによるリアルタイム可視化
- 色変化の履歴保存・タイムライン表示
- セッション管理（起動〜終了を1セッションとして記録）

---

## 2. 技術スタック

### フロントエンド

| 技術 | 役割 |
|------|------|
| **Nuxt.js 3** | フルスタックVueフレームワーク |
| **Vue 3** | UIコンポーネント |
| **Vite** | ビルドツール（Nuxt標準搭載） |
| **Three.js** | 3D描画・シェーダー |
| **GLSL** | カスタムシェーダー記述 |
| **Tailwind CSS** | スタイリング |
| **VueUse** | カメラ・ユーティリティ |

### バックエンド / ミドルウェア

| 技術 | 役割 |
|------|------|
| **Hono** | Cloudflare Workers上のAPIルーター |
| **Cloudflare Workers** | エッジサーバーレス実行環境 |
| **Cloudflare Pages** | Nuxtのホスティング + CI/CD |
| **Durable Objects** | WebSocket接続の状態管理・中継 |

### データストレージ

| サービス | 用途 |
|------|------|
| **Cloudflare D1** | 色履歴の永続保存（SQLite） |
| **Cloudflare KV** | 直近データのキャッシュ（TTL付き） |

### 解析サーバー

| 技術 | 役割 |
|------|------|
| **Python 3.11+** | メイン解析言語 |
| **OpenCV** | フレームのデコード・前処理 |
| **scikit-learn** | K-meansクラスタリングによる色抽出 |
| **NumPy** | ピクセル配列処理 |
| **websockets** | WebSocketサーバー |
| **FastAPI** | REST APIサーバー（補助） |

### デプロイ先

| レイヤー | サービス |
|------|------|
| フロントエンド | Cloudflare Pages |
| Workers / Hono | Cloudflare Workers |
| Pythonサーバー | Railway / Render / Fly.io |

---

## 3. アーキテクチャ

```
┌──────────────────────────────────────┐
│           ブラウザ                    │
│  カメラ映像 → Canvas → フレーム抽出   │
│  Three.js + GLSLシェーダー（表示）    │
│  Nuxt.js (Cloudflare Pages)          │
└──────────────┬───────────────────────┘
               │ WebSocket (映像フレーム)
┌──────────────▼───────────────────────┐
│        Python 解析サーバー            │
│  OpenCV + K-means → 色データ生成     │
│  (Railway / Render / Fly.io)         │
└──────────────┬───────────────────────┘
               │ WebSocket (色データJSON)
┌──────────────▼───────────────────────┐
│   Hono + Durable Objects             │
│   Cloudflare Workers                 │
│   中継・バリデーション・保存振り分け  │
└──────┬───────────────────┬───────────┘
       │                   │
┌──────▼──────┐     ┌──────▼──────┐
│  D1         │     │  KV         │
│  色履歴保存  │     │ 直近キャッシュ│
│  (永続)     │     │  TTL: 30分  │
└─────────────┘     └─────────────┘
```

---

## 4. ディレクトリ構成

```
color-vision/
│
├── frontend/                   # Nuxt.js アプリケーション
│   ├── components/
│   │   ├── CameraCapture.vue   # カメラ取得・フレーム送信
│   │   ├── ColorVisualizer.vue # Three.js シェーダー描画
│   │   └── ColorHistory.vue    # 履歴タイムライン表示
│   ├── composables/
│   │   ├── useWebSocket.ts     # WebSocket接続管理
│   │   ├── useColorStorage.ts  # 保存タイミング制御
│   │   └── useThreeJS.ts       # Three.js初期化・更新
│   ├── shaders/
│   │   ├── colorViz.vert       # 頂点シェーダー
│   │   └── colorViz.frag       # フラグメントシェーダー
│   ├── pages/
│   │   ├── index.vue           # メイン画面（カメラ + 可視化）
│   │   └── history.vue         # 履歴ページ
│   └── nuxt.config.ts
│
├── worker/                     # Cloudflare Workers (Hono)
│   ├── src/
│   │   ├── index.ts            # エントリーポイント
│   │   ├── routes/
│   │   │   ├── colors.ts       # 色データのCRUD API
│   │   │   └── sessions.ts     # セッション管理API
│   │   └── colorHub.ts         # Durable Objects (WebSocket中継)
│   └── wrangler.toml
│
├── analyzer/                   # Python 解析サーバー
│   ├── main.py                 # WebSocketサーバー起動
│   ├── analyzer.py             # K-means色抽出ロジック
│   ├── utils.py                # RGB→HSL変換等ユーティリティ
│   ├── requirements.txt
│   └── Dockerfile
│
└── README.md
```

---

## 5. 環境構築手順

### 前提条件

- Node.js 18以上
- Python 3.11以上
- Wrangler CLI (`npm install -g wrangler`)

### セットアップコマンド

```bash
# 1. Nuxt.js セットアップ
npx nuxi@latest init frontend
cd frontend
npm install three @types/three
npm install -D @nuxtjs/tailwindcss
npm install @vueuse/nuxt @vueuse/core
cd ..

# 2. Cloudflare Workers (Hono) セットアップ
mkdir worker && cd worker
npm init -y
npm install hono
npm install -D wrangler typescript
cd ..

# 3. Python環境セットアップ
mkdir analyzer && cd analyzer
python3 -m venv venv
source venv/bin/activate
pip install websockets opencv-python numpy scikit-learn Pillow fastapi uvicorn
pip freeze > requirements.txt
cd ..
```

### 環境変数

```bash
# worker/.env
PYTHON_WS_URL=ws://localhost:8765
AUTH_SECRET=your_secret_key

# analyzer/.env
WS_HOST=0.0.0.0
WS_PORT=8765
```

---

## 6. 各レイヤーの役割

### フロントエンド（Nuxt.js）

- ブラウザカメラ映像の取得（MediaStream API）
- 30fpsでフレームをJPEG圧縮してWebSocketで送信（解像度: 320×240）
- Pythonから返ってきた色データをThree.jsシェーダーへ即時反映
- 5秒ごと or 色変化が大きい時にHono APIへ保存リクエスト

### Hono / Cloudflare Workers

- PythonサーバーとNuxtの間のWebSocket中継
- 色データのバリデーション
- D1・KVへの書き込み・読み取り
- 認証（Bearerトークン）

### Python 解析サーバー

- WebSocketでフレームを受信
- OpenCVでデコード → K-means（5クラスタ）で主要色抽出
- 各色のRGB・HEX・HSL・占有率を計算してJSON返却

### Cloudflare D1

- 色スナップショットの永続保存
- セッション管理
- 時系列クエリ・集計に使用

### Cloudflare KV

- 直近セッションの色データをキャッシュ（TTL: 30分）
- D1へのアクセスを減らすバッファ役

---

## 7. データフロー

### リアルタイムフロー（毎フレーム）

```
カメラ映像
 → Canvas.toBlob() (JPEG, 320×240)
 → WebSocket送信
 → Python: K-means色抽出
 → JSON返却 { colors: [...], dominant: ... }
 → Three.js シェーダーへ即時反映
```

### 保存フロー（間引き）

```
色データ受信
 → 色差計算（前回との差分）
 → 色差 > 閾値(30) or 最終保存から5秒以上経過
   → KV: 直近データ更新（TTL 30分）
   → 最終D1保存から30秒以上経過の場合
     → D1: color_snapshots に INSERT
```

---

## 8. データベース設計（D1）

### sessions テーブル

```sql
CREATE TABLE sessions (
  id          TEXT PRIMARY KEY,
  started_at  TEXT NOT NULL,
  ended_at    TEXT,
  label       TEXT
);
```

### color_snapshots テーブル

```sql
CREATE TABLE color_snapshots (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id   TEXT NOT NULL,
  captured_at  TEXT NOT NULL,
  color1_hex   TEXT, color1_pct REAL,
  color2_hex   TEXT, color2_pct REAL,
  color3_hex   TEXT, color3_pct REAL,
  color4_hex   TEXT, color4_pct REAL,
  color5_hex   TEXT, color5_pct REAL,
  dominant_hex TEXT,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

---

## 9. 保存戦略

### インターバル設計

| 条件 | 保存先 | 備考 |
|------|------|------|
| 毎フレーム | なし | Three.jsへ即時反映のみ |
| 色差 > 30 or 5秒経過 | KV | 直近キャッシュ更新 |
| 30秒経過 | D1 | 永続保存 |

### 1時間あたりの書き込み見積もり

| ストレージ | 書き込み回数/時間 |
|------|------|
| KV | 最大 720回 |
| D1 | 最大 120回 |

> いずれもCloudflare無料枠内に収まる想定

---

## 10. API仕様

### POST `/api/colors/snapshot`

色スナップショットを保存する。

```json
// リクエスト
{
  "sessionId": "session_001",
  "colors": [
    {
      "hex": "#ff5733",
      "rgb": [255, 87, 51],
      "hsl": { "h": 11, "s": 100, "l": 60 },
      "percentage": 34.2
    }
  ],
  "dominant": "#ff5733",
  "saveType": "longterm"
}

// レスポンス
{ "success": true }
```

### GET `/api/colors/history/:sessionId`

セッションの色履歴を時系列で取得する。

### GET `/api/colors/dominant/recent?limit=50`

直近N件のドミナントカラー推移を取得する。

---

## 11. デプロイ

| レイヤー | サービス | コマンド |
|------|------|------|
| フロントエンド | Cloudflare Pages | `npx wrangler pages deploy .output/public` |
| Workers / Hono | Cloudflare Workers | `npx wrangler deploy` |
| Pythonサーバー | Railway / Render / Fly.io | `railway up` |

### nuxt.config.ts の設定

```ts
export default defineNuxtConfig({
  nitro: {
    preset: 'cloudflare-pages'
  }
})
```

---

## 12. 今後の拡張アイデア

| アイデア | 内容 |
|------|------|
| パレット生成 | 抽出色をそのままUI配色に反映 |
| 感情マッピング | 色温度から感情スコアを算出してシェーダーに反映 |
| 気象データ連動 | 地球上に気温・風をボリュームレンダリング |
| 音楽連動 | 抽出色のHSLを音のピッチ・テンポと同期 |
| 時系列可視化 | D1の履歴データを使った色変化タイムライン |
| PWA対応 | モバイルからカメラで使えるようにする |
| 共有機能 | セッションのパレットをSNSシェア |

---

*最終更新: 2026-06-15*
