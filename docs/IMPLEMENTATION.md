# Color Vision — 実装詳細ガイド

> 各コンポーネントの実装方針・データフロー・コード解説

---

## 目次

1. [全体フロー概観](#1-全体フロー概観)
2. [フロントエンド実装](#2-フロントエンド実装)
3. [Python解析サーバー実装](#3-python解析サーバー実装)
4. [Cloudflare Worker実装](#4-cloudflare-worker実装)
5. [GLSLシェーダー実装](#5-glslシェーダー実装)
6. [ローカル開発の起動手順](#6-ローカル開発の起動手順)

---

## 1. 全体フロー概観

```
ブラウザ (Nuxt.js)
  ├─ CameraCapture: 30fps でカメラフレームをJPEGに変換
  ├─ useWebSocket: JPEGバイナリをWebSocketで送信
  │       ↓ ws://analyzer:8765
  │
Python解析サーバー (FastAPI + websockets)
  ├─ main.py: WebSocketサーバー受信
  ├─ analyzer.py: OpenCV → K-means → 5色抽出
  │       ↓ JSON { colors: [...], dominant: "#..." }
  │
ブラウザ (Nuxt.js)
  ├─ useThreeJS: Three.js uniformsを更新 → GLSLシェーダーがGPUで再描画
  └─ useColorStorage: 色差・時間で保存判定
          ↓ POST /api/colors/snapshot (Bearer認証)
Cloudflare Worker (Hono)
  ├─ routes/colors.ts: バリデーション + 保存
  ├─ KV: 直近データキャッシュ (TTL 30分)
  └─ D1: 永続SQLiteに INSERT
```

---

## 2. フロントエンド実装

### 2-1. カメラフレームの取得と送信

**ファイル:** `frontend/pages/index.vue`

```
カメラ映像 (MediaStream)
  → <video> タグに表示
  → 非表示の <canvas> (320×240) に drawImage
  → canvas.toBlob(JPEG, quality=0.7) で圧縮
  → WebSocket.send(blob) で送信 (30fps = 33ms間隔)
```

**サイズを 320×240 にする理由**
- K-meansの処理速度確保（高解像度だとピクセル数が増えCPU負荷が上がる）
- さらに analyzer.py 内でランダムサンプリング 10,000px に絞ることで安定した応答速度を実現

### 2-2. WebSocket管理 (`composables/useWebSocket.ts`)

```typescript
// 接続・再接続・送受信をカプセル化
const { connect, sendFrame, isConnected, onColorUpdate } = useWebSocket(wsUrl)

// コールバックで色データを受け取る
onColorUpdate.value = (result) => {
  updateColors(result.colors) // → Three.js uniformsへ
}
```

**再接続ロジック**
- `ws.onclose` で `setTimeout(connect, 2000)` を呼び出し
- Pythonサーバーが一時停止してもブラウザリロード不要

### 2-3. 保存タイミング制御 (`composables/useColorStorage.ts`)

```
色データ受信
  ├─ KV保存から10分以上 → KV更新 (saveType: "realtime")
  └─ D1保存から5分以上  → D1 INSERT (saveType: "longterm")
  ※ どちらも経過していない場合はスキップ
```

**間隔設定の根拠（Cloudflare無料枠との兼ね合い）**

| 保存先 | 間隔 | 1日あたりの書き込み数 | 無料枠 | 状態 |
|---|---|---|---|---|
| KV | 10分 | ~144回 | 1,000回/日 | ✓ 安全圏 |
| D1 | 5分 | ~288回 | 100,000回/日 | ✓ 安全圏 |

**過去の設定と問題点**

当初は「色の変化量（RGB距離 > 30）でKV即時書き込み」という設計だったが、
カメラが動くたびに毎秒KVに書き込みが発生し `429 Too Many Requests` が頻発。
時間ベースのみの制御に変更することで解決。

> KV無料枠は **1,000書き込み/日**（= 86秒に1回が理論上限）。
> 色変化ベースのトリガーはKV上限を簡単に超えるため使用しない。

### 2-4. Three.jsシェーダーの更新 (`composables/useThreeJS.ts`)

```typescript
function updateColors(colors: ColorEntry[]) {
  uniforms.uColorCount.value = colors.length
  colors.forEach((c, i) => {
    // RGB [0-255] → THREE.Color [0.0-1.0]
    uniforms.uColors.value[i] = new THREE.Color(
      c.rgb[0] / 255, c.rgb[1] / 255, c.rgb[2] / 255
    )
    uniforms.uPercentages.value[i] = c.percentage
  })
}
```

- `uniforms` はシェーダーへの参照を共有するため、値を変更するだけで次フレームに反映される
- `requestAnimationFrame` のループは毎フレーム `uTime` をインクリメントし、シェーダーでの揺らぎアニメーションに使う

---

## 3. Python解析サーバー実装

### 3-1. K-meansによる色抽出 (`analyzer/analyzer.py`)

```python
def extract_colors(frame_bytes: bytes, n_colors: int = 5) -> dict:
    # 1. JPEGバイナリ → NumPy配列 → RGB画像
    arr = np.frombuffer(frame_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # 2. (H, W, 3) → (H*W, 3) に展開
    pixels = img_rgb.reshape(-1, 3).astype(np.float32)

    # 3. 10,000ピクセルにランダムサンプリング（速度最適化）
    if len(pixels) > 10000:
        idx = np.random.choice(len(pixels), 10000, replace=False)
        pixels = pixels[idx]

    # 4. K-meansで5クラスタに分類
    kmeans = KMeans(n_clusters=5, n_init=3, max_iter=100, random_state=42)
    kmeans.fit(pixels)

    # 5. 各クラスタの代表色・占有率を計算
    centers = kmeans.cluster_centers_.astype(int)
    counts = np.bincount(kmeans.labels_, minlength=n_colors)
    # 占有率の多い順にソート
    for i in np.argsort(counts)[::-1]:
        ...
```

**`n_init=3` の意味**
K-meansは初期値に依存するため、3回試行して最良の結果を採用する（速度と精度のバランス）。

### 3-4. 色数（n_colors）の選択基準

K-meansは映像の全色を **N色に強制圧縮** するアルゴリズムのため、何色にしても映像そのままにはならない。

| 色数 | 特徴 | 向いているシーン |
|---|---|---|
| 3色 | 大胆・シンプル | 夕焼け・空など単純な構成 |
| **5色（デフォルト）** | バランスが良い | 一般的な室内・人物 |
| 8色 | 細かいニュアンスまで拾える | 自然・複雑な背景 |
| 12色 | かなり精細 | 絵画・カラフルなシーン |
| 16色以上 | 処理が重くなり始める | 特殊用途 |

### 3-5. 色数を変更する際の修正箇所

色数を **N** に変える場合、**3箇所**の変更が必要。

**1. `analyzer/analyzer.py`**
```python
def extract_colors(frame_bytes: bytes, n_colors: int = N)
```

**2. `frontend/app/composables/useThreeJS.ts`（uniform配列サイズ）**
```typescript
uColors: { value: Array(N).fill(new THREE.Color(0, 0, 0)) },
uPercentages: { value: Array(N).fill(0) },
```

**3. `useThreeJS.ts` 内のGLSLシェーダー（ループ上限）**
```glsl
for (int i = 0; i < N; i++) total += uPercentages[i];
for (int i = 0; i < N; i++) {
```

### 3-2. RGB → HEX / HSL変換 (`analyzer/utils.py`)

```python
import colorsys

def rgb_to_hsl(r, g, b) -> dict:
    # Pythonの colorsys は (r,g,b) → (h,l,s) 順に注意
    h, l, s = colorsys.rgb_to_hls(r/255, g/255, b/255)
    return {"h": round(h*360), "s": round(s*100), "l": round(l*100)}
```

HSLをJSON出力に含めているのは、フロントエンドで感情マッピングや色温度計算に使えるようにするため。

### 3-3. WebSocketサーバー (`analyzer/main.py`)

```python
async def handler(websocket):
    async for message in websocket:
        if isinstance(message, bytes):  # JPEGバイナリ受信
            result = extract_colors(message)
            await websocket.send(json.dumps(result))  # JSON返却

async with websockets.serve(handler, HOST, PORT):
    await asyncio.Future()  # Ctrl+Cまで稼働
```

---

## 4. Cloudflare Worker実装

### 4-1. エントリーポイント (`worker/src/index.ts`)

```typescript
type Bindings = {
  DB: D1Database        // D1バインディング
  KV: KVNamespace       // KVバインディング
  COLOR_HUB: DurableObjectNamespace
  AUTH_SECRET: string   // 環境変数
}

const app = new Hono<{ Bindings: Bindings }>()
app.use('*', cors())
app.use('/api/*', (c, next) => bearerAuth({ token: c.env.AUTH_SECRET })(c, next))
```

- 全APIに `cors()` を適用（ブラウザからのフェッチを許可）
- `/api/*` は `bearerAuth` で認証（`Authorization: Bearer <token>` が必要）

### 4-2. スナップショット保存 (`worker/src/routes/colors.ts`)

```typescript
// KVに直近データをキャッシュ（TTL 30分）
await c.env.KV.put(
  `session:${sessionId}:latest`,
  JSON.stringify({ colors, dominant, updatedAt: new Date().toISOString() }),
  { expirationTtl: 1800 }
)

// saveType が "longterm" の場合のみ D1 にINSERT
if (saveType === 'longterm') {
  await c.env.DB.prepare(`
    INSERT INTO color_snapshots
      (session_id, captured_at, color1_hex, color1_pct, ..., dominant_hex)
    VALUES (?, ?, ?, ?, ..., ?)
  `).bind(sessionId, now, ...colorValues, dominant).run()
}
```

### 4-3. Durable Objects によるWebSocket中継 (`worker/src/colorHub.ts`)

```typescript
export class ColorHub extends DurableObject {
  private clients: Set<WebSocket> = new Set()

  async fetch(request: Request) {
    // WebSocketアップグレード
    const pair = new WebSocketPair()
    this.ctx.acceptWebSocket(pair[1])
    this.clients.add(pair[1])
    return new Response(null, { status: 101, webSocket: pair[0] })
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    // 送信元以外の全クライアントに中継
    for (const client of this.clients) {
      if (client !== ws && client.readyState === WebSocket.READY_STATE_OPEN) {
        client.send(message)
      }
    }
  }
}
```

Durable Objectはグローバルに1インスタンスが保証されるため、複数の接続（ブラウザ・Pythonサーバー）が同じ `clients` セットを共有できる。

### 4-4. D1スキーマとマイグレーション

```sql
-- schema.sql（wrangler d1 execute で適用）
CREATE TABLE IF NOT EXISTS sessions (
  id         TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  ended_at   TEXT,
  label      TEXT
);

CREATE TABLE IF NOT EXISTS color_snapshots (
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

CREATE INDEX IF NOT EXISTS idx_snapshots_session
  ON color_snapshots(session_id, captured_at);
```

---

## 5. GLSLシェーダー実装

### フラグメントシェーダーの動作

```glsl
uniform vec3 uColors[5];       // 5色のRGB (0.0〜1.0)
uniform float uPercentages[5]; // 各色の占有率 (例: 34.2, 28.1, ...)
uniform float uTime;           // 経過時間（揺らぎ用）
uniform int uColorCount;       // 実際の色数

varying vec2 vUv;              // UV座標 (0.0〜1.0)

void main() {
  // 占有率の合計を計算
  float total = 0.0;
  for (int i = 0; i < 5; i++) total += uPercentages[i];

  // UV.xを占有率スケールに変換 (0〜total の範囲に)
  float x = vUv.x * total;

  // どの色帯にいるか判定
  float acc = 0.0;
  vec3 color = uColors[0];
  for (int i = 0; i < 5; i++) {
    if (i >= uColorCount) break;
    float next = acc + uPercentages[i];
    if (x >= acc && x < next) {
      color = uColors[i];
      break;
    }
    acc = next;
  }

  // Y方向のsin波で揺らぎを追加
  float wave = sin(vUv.y * 15.0 + uTime) * 0.015;
  color += wave;

  gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
```

**ポイント**
- 色帯の幅は `uPercentages` で動的に決まる（占有率34%の色は34%の幅を占める）
- `wave` は微小な明度変動で、静止しているように見えないアニメーションを実現
- `clamp(color, 0.0, 1.0)` でwave加算による白飛び・黒潰れを防止

---

## 6. トラブルシューティング

### `.env.local` の環境変数がNuxt devサーバーに反映されない

**症状**
```
index.vue:34 POST http://localhost:8787/api/sessions net::ERR_CONNECTION_REFUSED
```
`NUXT_PUBLIC_WORKER_URL` を `.env.local` に設定しても、Nuxtのバックグラウンドプロセスが読み込まず `localhost:8787` のままになる。

**原因**
バックグラウンドで起動したdev serverプロセスは、起動時に `.env.local` を読み込むタイミングでファイルが認識されないケースがある。`nitro.preset: 'cloudflare-pages'` を設定している場合はCloudflareエミュレーションモードが優先されenv varが上書きされることもある。

**解決策**
`nuxt.config.ts` のデフォルト値に本番URLを直接記述する。WorkerのURLは公開情報なので問題なし。

```typescript
runtimeConfig: {
  public: {
    // デフォルト値を本番URLに設定（.env.local が読まれない場合のフォールバック）
    workerUrl: process.env.NUXT_PUBLIC_WORKER_URL ?? 'https://color-vision-worker.color-vision.workers.dev',
    analyzerWsUrl: process.env.NUXT_PUBLIC_ANALYZER_WS_URL ?? 'ws://localhost:8765',
    authToken: process.env.NUXT_PUBLIC_AUTH_TOKEN ?? '<AUTH_SECRETと同じ値>',
  },
},
```

**合わせて確認すること**
- `nitro.preset` はproduction時のみ `'cloudflare-pages'` を使う:
  ```typescript
  nitro: {
    preset: process.env.NODE_ENV === 'production' ? 'cloudflare-pages' : undefined,
  },
  ```
- devサーバーを再起動: `Ctrl+C` → `npm run dev`

---

## 7. ローカル開発の起動手順

### Step 1: Pythonサーバー起動

```bash
cd analyzer
source venv/bin/activate
python main.py
# → WebSocket server running on ws://0.0.0.0:8765
```

### Step 2: Cloudflare Worker起動

```bash
cd worker
cp .env.example .env  # 環境変数設定
npx wrangler dev      # → http://localhost:8787
```

### Step 3: フロントエンド起動

```bash
cd frontend
cp .env.example .env.local  # 環境変数設定
npm run dev                  # → http://localhost:3000
```

### 動作確認チェックリスト

- [ ] `http://localhost:3000` でカメラ許可ダイアログが表示される
- [ ] カメラ映像が画面左に表示される
- [ ] ステータスバッジが `LIVE` になる
- [ ] Three.jsキャンバスに色帯が描画・更新される
- [ ] `http://localhost:3000/history` で履歴ページが表示される

---

*最終更新: 2026-06-15*
