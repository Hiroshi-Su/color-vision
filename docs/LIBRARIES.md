# Color Vision — 使用ライブラリ詳細ガイド

> 各ライブラリの役割・選定理由・主要APIをまとめたリファレンス

---

## フロントエンド

---

### Nuxt.js 4 / Vue 3

| 項目 | 内容 |
|------|------|
| バージョン | nuxt ^4.4.8 / vue ^3.5.35 |
| 公式サイト | https://nuxt.com |
| 役割 | フルスタックVueフレームワーク |

**概要**
Vue 3ベースのフルスタックフレームワーク。SSR/SSGとCloudflare Pagesへのデプロイを標準でサポートする。`nuxt.config.ts`に`preset: 'cloudflare-pages'`を設定するだけでエッジデプロイに対応できる。

**このプロジェクトでの使い方**
- `pages/` ディレクトリ：ファイルベースルーティング（`/`, `/history`）
- `composables/` ディレクトリ：WebSocket・Three.js・保存ロジックの分離
- `useRuntimeConfig()`：環境変数をサーバー/クライアントで安全に扱う
- `useFetch()`：Workerへの型安全なデータフェッチ

**主要API**
```ts
// 環境変数の取得
const config = useRuntimeConfig()
config.public.workerUrl

// データフェッチ
const { data } = await useFetch<T>(`${url}/api/colors/history`)
```

---

### Three.js

| 項目 | 内容 |
|------|------|
| バージョン | ^0.184.0 |
| 公式サイト | https://threejs.org |
| 役割 | WebGLを抽象化した3D描画ライブラリ |

**概要**
WebGL APIを高レベルに抽象化したJavaScriptライブラリ。シーン・カメラ・レンダラーというシンプルな構造で3Dグラフィックを描画できる。ShaderMaterialを使うことでカスタムGLSLシェーダーを直接記述できる。

**このプロジェクトでの使い方**
- `PlaneGeometry(2, 2)`：フルスクリーンの板ポリゴンを作成
- `ShaderMaterial`：頂点・フラグメントシェーダーを渡してGLSL描画
- `uniforms`：Pythonから返ってきた色データをシェーダーにリアルタイム転送
- `OrthographicCamera`：2D描画のための正投影カメラ

**主要API**
```ts
import * as THREE from 'three'

const uniforms = {
  uColors: { value: Array(5).fill(new THREE.Color(0, 0, 0)) },
  uPercentages: { value: Array(5).fill(0) },
  uTime: { value: 0 },
}

const mat = new THREE.ShaderMaterial({
  uniforms,
  vertexShader: `...`,
  fragmentShader: `...`,
})
```

---

### GLSL（OpenGL Shading Language）

| 項目 | 内容 |
|------|------|
| バージョン | WebGL 2.0（GLSL ES 3.00） |
| 役割 | GPUで並列実行するシェーダー言語 |

**概要**
GPUの各ピクセルを並列処理するためのC言語ライクな言語。フラグメントシェーダーで各ピクセルの色を計算する。`uniform`変数でCPU側（JavaScript）からリアルタイムにデータを渡せる。

**このプロジェクトでの使い方**
- `uColors[5]`：5色のRGB値をuniformで受け取る
- `uPercentages[5]`：各色の占有率に応じて横方向に色帯を描画
- `uTime`：時間を使ったsin波でなめらかな揺らぎアニメーション

**シェーダーの構造**
```glsl
// フラグメントシェーダー（概念）
uniform vec3 uColors[5];      // 5色のRGB
uniform float uPercentages[5]; // 各色の占有率
uniform float uTime;           // 経過時間

void main() {
  // vUv.xの位置に応じてどの色帯にいるか判定
  // sinを使った揺らぎを加算
  gl_FragColor = vec4(color, 1.0);
}
```

---

### @vueuse/nuxt / @vueuse/core

| 項目 | 内容 |
|------|------|
| バージョン | ^14.3.0 |
| 公式サイト | https://vueuse.org |
| 役割 | Vue 3向けComposablesコレクション |

**概要**
200以上のComposablesを提供するVue 3ユーティリティライブラリ。カメラ・センサー・アニメーション・ネットワーク状態など多様なWebAPIをVue 3のリアクティブシステムと統合する。

**このプロジェクトで使えるAPI**
```ts
import { useUserMedia, useRafFn, useEventListener } from '@vueuse/core'

// カメラ映像の取得
const { stream } = useUserMedia({ constraints: { video: true } })

// requestAnimationFrameのラッパー
const { pause, resume } = useRafFn(() => {
  // 毎フレームの処理
})
```

---

### @nuxtjs/tailwindcss

| 項目 | 内容 |
|------|------|
| バージョン | ^6.14.0 |
| 公式サイト | https://tailwindcss.nuxtjs.org |
| 役割 | Nuxt向けTailwind CSS統合 |

**概要**
ユーティリティファーストCSSフレームワーク。クラス名を組み合わせるだけでスタイルを記述でき、未使用のCSSは自動的にパージされるため本番ビルドが軽量になる。

---

## バックエンド / ミドルウェア

---

### Hono

| 項目 | 内容 |
|------|------|
| バージョン | ^4.12.25 |
| 公式サイト | https://hono.dev |
| 役割 | Cloudflare Workers対応の軽量Webフレームワーク |

**概要**
Cloudflare Workers・Deno・Node.jsで動作するWebフレームワーク。Express.jsに近いAPIで軽量・高速。型安全なルーティング、ミドルウェア、バリデーションを提供する。

**このプロジェクトでの使い方**
- ルーティング：`/api/colors/*`, `/api/sessions/*`
- ミドルウェア：`cors()`・`bearerAuth()`
- D1・KVへのアクセスは`c.env`経由で型安全に扱う

**主要API**
```ts
import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { bearerAuth } from 'hono/bearer-auth'

type Bindings = { DB: D1Database; KV: KVNamespace }
const app = new Hono<{ Bindings: Bindings }>()

app.use('*', cors())
app.post('/api/colors/snapshot', async (c) => {
  const body = await c.req.json()
  await c.env.DB.prepare('INSERT INTO ...').bind(...).run()
  return c.json({ success: true })
})
```

---

### Cloudflare Workers

| 項目 | 内容 |
|------|------|
| ランタイム | V8 Isolate |
| 公式サイト | https://workers.cloudflare.com |
| 役割 | エッジサーバーレス実行環境 |

**概要**
Cloudflareのエッジネットワーク上で動作するサーバーレス実行環境。V8 Isolateを使い世界200以上のロケーションで低レイテンシに実行される。Node.jsとは異なりServiceWorker形式のAPIを使う。

**主要な制約と特徴**
- CPU時間：リクエストあたり10ms（Bundled）または30秒（Unbound）
- メモリ：128MB上限
- ファイルシステムアクセス：不可（KV/D1/R2を使う）
- `node:crypto`などNode.js互換レイヤー使用可（`nodejs_compat`フラグ）

---

### Durable Objects

| 項目 | 内容 |
|------|------|
| 公式サイト | https://developers.cloudflare.com/durable-objects/ |
| 役割 | WebSocket接続の状態管理・メッセージ中継 |

**概要**
Cloudflare Workers上でステートフルな処理を実現するオブジェクト。1つのDurable Objectインスタンスは世界に1つだけ存在し、WebSocket接続を保持できる。ブラウザ・PythonサーバーからのWebSocket接続をColorHubで管理する。

**主要API**
```ts
export class ColorHub extends DurableObject {
  async fetch(request: Request) {
    const pair = new WebSocketPair()
    this.ctx.acceptWebSocket(pair[1])
    return new Response(null, { status: 101, webSocket: pair[0] })
  }
  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    // 接続中の他クライアントに中継
  }
}
```

---

### Cloudflare D1

| 項目 | 内容 |
|------|------|
| 公式サイト | https://developers.cloudflare.com/d1/ |
| 役割 | エッジSQLiteデータベース（永続保存） |

**概要**
WorkersバインドのSQLiteデータベース。標準的なSQLで操作でき、Workers側からはD1Databaseバインディング経由でアクセスする。無料枠：100,000行読み取り/日、1,000行書き込み/日。

**主要API**
```ts
// INSERT
await c.env.DB.prepare(
  'INSERT INTO color_snapshots (session_id, captured_at, dominant_hex) VALUES (?, ?, ?)'
).bind(sessionId, now, dominant).run()

// SELECT
const { results } = await c.env.DB.prepare(
  'SELECT * FROM color_snapshots WHERE session_id = ? ORDER BY captured_at ASC'
).bind(sessionId).all()
```

---

### Cloudflare KV

| 項目 | 内容 |
|------|------|
| 公式サイト | https://developers.cloudflare.com/kv/ |
| 役割 | エッジキーバリューストア（TTLキャッシュ） |

**概要**
グローバルに分散されたキーバリューストア。TTL（有効期限）付きの書き込みに対応しており、直近の色データを30分間キャッシュするのに使う。無料枠：100,000読み取り/日、1,000書き込み/日。

**主要API**
```ts
// TTL付き書き込み（30分 = 1800秒）
await c.env.KV.put(
  `session:${sessionId}:latest`,
  JSON.stringify(data),
  { expirationTtl: 1800 }
)

// 読み取り
const raw = await c.env.KV.get(`session:${sessionId}:latest`)
const data = raw ? JSON.parse(raw) : null
```

---

### Wrangler

| 項目 | 内容 |
|------|------|
| バージョン | ^4.100.0 |
| 公式サイト | https://developers.cloudflare.com/workers/wrangler/ |
| 役割 | Cloudflare Workers/Pages の CLI開発ツール |

**概要**
Cloudflare WorkersのCLIツール。ローカル開発サーバー（Miniflare）の起動、D1マイグレーション、KV操作、本番デプロイまでをカバーする。

**主要コマンド**
```bash
# ローカル開発サーバー起動
npx wrangler dev

# D1データベース作成
npx wrangler d1 create color-vision-db

# D1マイグレーション実行
npx wrangler d1 execute color-vision-db --file=./schema.sql

# KV Namespace作成
npx wrangler kv namespace create COLOR_VISION_KV

# デプロイ
npx wrangler deploy
```

---

## Python 解析サーバー

---

### OpenCV (opencv-python)

| 項目 | 内容 |
|------|------|
| バージョン | 4.13.0.92 |
| 公式サイト | https://opencv.org |
| 役割 | 画像デコード・前処理 |

**概要**
コンピュータビジョンの定番ライブラリ。WebSocketで受信したJPEGバイナリをNumPy配列にデコードし、BGR→RGB変換を行う。

**このプロジェクトでの使い方**
```python
import cv2
import numpy as np

# JPEGバイナリ → NumPy配列
arr = np.frombuffer(frame_bytes, dtype=np.uint8)
img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # BGR形式

# BGR → RGB変換
img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
```

---

### scikit-learn

| 項目 | 内容 |
|------|------|
| バージョン | 1.9.0 |
| 公式サイト | https://scikit-learn.org |
| 役割 | K-meansクラスタリングによる色抽出 |

**概要**
機械学習ライブラリ。K-meansクラスタリングを使って画像内のピクセル色を5つのクラスタに分類し、各クラスタの代表色と占有率を算出する。

**K-meansによる色抽出の仕組み**
1. 画像の全ピクセルをRGB値として3次元空間にプロット
2. K-means（K=5）で5つのグループに分類
3. 各グループの重心（平均色）を代表色として採用
4. グループ内のピクセル数 ÷ 全ピクセル数 = 占有率

```python
from sklearn.cluster import KMeans

kmeans = KMeans(n_clusters=5, n_init=3, max_iter=100, random_state=42)
kmeans.fit(pixels)  # pixels: (N, 3) のRGB配列

centers = kmeans.cluster_centers_.astype(int)  # 5色の代表RGB
labels = kmeans.labels_                         # 各ピクセルの所属クラスタ
counts = np.bincount(labels)                    # 各クラスタのピクセル数
```

---

### NumPy

| 項目 | 内容 |
|------|------|
| バージョン | 2.4.6 |
| 公式サイト | https://numpy.org |
| 役割 | ピクセル配列の高速処理 |

**概要**
数値計算ライブラリ。画像のピクセルデータを2D/3D配列として扱い、reshape・スライシング・ランダムサンプリングを高速に行う。

```python
import numpy as np

# 画像 (H, W, 3) → ピクセルリスト (H*W, 3)
pixels = img_rgb.reshape(-1, 3).astype(np.float32)

# 処理速度のため10,000ピクセルにランダムサンプリング
idx = np.random.choice(len(pixels), 10000, replace=False)
pixels = pixels[idx]
```

---

### websockets

| 項目 | 内容 |
|------|------|
| バージョン | 16.0 |
| 公式サイト | https://websockets.readthedocs.io |
| 役割 | PythonのWebSocketサーバー |

**概要**
asyncioベースのWebSocketライブラリ。ブラウザからJPEGフレームを受信し、解析結果のJSONを返す双方向通信サーバーを構築する。

```python
import asyncio
import websockets

async def handler(websocket):
    async for message in websocket:
        if isinstance(message, bytes):  # JPEGバイナリ
            result = extract_colors(message)
            await websocket.send(json.dumps(result))

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        await asyncio.Future()  # 永続稼働
```

---

### FastAPI

| 項目 | 内容 |
|------|------|
| バージョン | 0.137.0 |
| 公式サイト | https://fastapi.tiangolo.com |
| 役割 | REST APIサーバー（補助・ヘルスチェック等） |

**概要**
PythonのモダンREST APIフレームワーク。Pydanticによる型バリデーション、OpenAPIドキュメント自動生成が特徴。メインはWebSocketだが、ヘルスチェックエンドポイントやデバッグAPIの追加に使う。

---

## データフロー整理

```
[ブラウザ] canvas.toBlob(JPEG)
    ↓ WebSocket (バイナリ)
[Python/websockets] 受信
    ↓ cv2.imdecode → RGB変換
[OpenCV] 前処理
    ↓ pixels.reshape(-1, 3)
[NumPy] 配列整形
    ↓ KMeans(n_clusters=5).fit(pixels)
[scikit-learn] クラスタリング
    ↓ JSON { colors: [...], dominant: "..." }
[Python/websockets] 送信
    ↓ WebSocket (JSON文字列)
[ブラウザ/useWebSocket] 受信
    ↓ uniforms.uColors.value[i] = new THREE.Color(...)
[Three.js ShaderMaterial] GPU転送
    ↓ フラグメントシェーダー実行（全ピクセル並列）
[GLSL] 色帯レンダリング
```

---

*最終更新: 2026-06-15*
