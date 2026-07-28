# Color Vision — Cloudflare セットアップガイド

> Cloudflareアカウント作成後、Workerをデプロイするまでの完全手順

---

## 目次

1. [前提条件](#1-前提条件)
2. [Wrangler ログイン](#2-wrangler-ログイン)
3. [D1 データベース作成](#3-d1-データベース作成)
4. [KV Namespace 作成](#4-kv-namespace-作成)
5. [wrangler.toml の設定](#5-wranglertoml-の設定)
6. [D1 マイグレーション実行](#6-d1-マイグレーション実行)
7. [環境変数の設定](#7-環境変数の設定)
8. [Worker デプロイ](#8-worker-デプロイ)
9. [動作確認](#9-動作確認)
10. [トラブルシューティング](#10-トラブルシューティング)

---

## 1. 前提条件

- Cloudflareアカウント作成済み（https://dash.cloudflare.com）
- Node.js 18以上インストール済み
- `worker/` ディレクトリで `npm install` 済み（wrangler v4.x が入っている）

```bash
# バージョン確認
cd worker
npx wrangler --version
# → 4.100.0 以上であればOK
```

---

## 2. Wrangler ログイン

```bash
cd worker
npx wrangler login
```

ブラウザが自動で開き、Cloudflareの認証画面が表示される。  
**「Allow」** をクリックすると以下が表示されてログイン完了：

```
Authorization granted to Wrangler ✅
```

> **補足:** ログイン時に「Fetch https://developers.cloudflare.com/agent-setup/prompt.md」というメッセージが出ることがあるが、これはCloudflare AI Agentsの案内であり、このプロジェクトには不要。無視してOK。

---

## 3. D1 データベース作成

```bash
cd worker
npx wrangler d1 create color-vision-db
```

**出力例:**

```
✅ Successfully created DB 'color-vision-db' in region APAC

[[d1_databases]]
binding = "DB"
database_name = "color-vision-db"
database_id = "853962ae-2006-46d1-97f5-25a69ff7b35e"
```

> `database_id` をメモしておく（`wrangler.toml` に記入する）。

---

## 4. KV Namespace 作成

```bash
cd worker
npx wrangler kv namespace create COLOR_VISION_KV
```

**出力例:**

```
✅ Successfully created namespace "COLOR_VISION_KV"

[[kv_namespaces]]
binding = "KV"
id = "0e525676bccc4ddabe12f2528d6d4973"
```

> `id` をメモしておく（`wrangler.toml` に記入する）。

---

## 5. wrangler.toml の設定

`worker/wrangler.toml` に取得したIDを記入する。

```toml
name = "color-vision-worker"
main = "src/index.ts"
compatibility_date = "2024-11-01"
compatibility_flags = ["nodejs_compat"]

[[d1_databases]]
binding = "DB"
database_name = "color-vision-db"
database_id = "853962ae-2006-46d1-97f5-25a69ff7b35e"   # ← Step 3 で取得

[[kv_namespaces]]
binding = "KV"
id = "0e525676bccc4ddabe12f2528d6d4973"                  # ← Step 4 で取得

[durable_objects]
bindings = [
  { name = "COLOR_HUB", class_name = "ColorHub" }
]

[[migrations]]
tag = "v1"
new_classes = ["ColorHub"]

[vars]
PYTHON_WS_URL = "ws://localhost:8765"   # ローカル開発用。デプロイ後は本番URLに変更
```

> `AUTH_SECRET` は機密情報のため `.toml` には書かず、Step 7 でシークレットとして登録する。

---

## 6. D1 マイグレーション実行

マイグレーションファイルは `worker/migrations/0001_init.sql` に定義済み。

### テーブル構成

```sql
-- sessions: 1回の利用セッションを記録
CREATE TABLE IF NOT EXISTS sessions (
  id         TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  ended_at   TEXT
);

-- color_snapshots: 色スナップショットの履歴
CREATE TABLE IF NOT EXISTS color_snapshots (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id   TEXT NOT NULL,
  captured_at  TEXT NOT NULL,
  color1_hex   TEXT, color1_pct REAL,
  color2_hex   TEXT, color2_pct REAL,
  color3_hex   TEXT, color3_pct REAL,
  color4_hex   TEXT, color4_pct REAL,
  color5_hex   TEXT, color5_pct REAL,
  dominant_hex TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_session  ON color_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_captured ON color_snapshots(captured_at DESC);
```

### マイグレーション適用（Cloudflare本番環境に反映）

```bash
cd worker
npx wrangler d1 migrations apply color-vision-db --remote
```

**出力例:**

```
Migrations to be applied:
┌─────────────────┐
│ Name            │
├─────────────────┤
│ 0001_init.sql   │
└─────────────────┘
✅ Applied 1 migration
```

### ローカル開発用（任意）

```bash
npx wrangler d1 migrations apply color-vision-db --local
```

---

## 7. 環境変数の設定

`AUTH_SECRET` はAPIの認証トークン。平文で `.toml` に書かず、Wrangler シークレットとして登録する。

```bash
cd worker
npx wrangler secret put AUTH_SECRET
# → プロンプトが出るので任意の文字列を入力（例: openssl rand -hex 32 で生成）
```

フロントエンド側にも同じ値を設定する（後述の `.env.local` に記入）。

---

## 8. Worker デプロイ

```bash
cd worker
npx wrangler deploy
```

**出力例:**

```
✅ Uploaded color-vision-worker (X.XXs)
Published color-vision-worker (X.XXs)
  https://color-vision-worker.<your-subdomain>.workers.dev
```

デプロイ後、本番用の `PYTHON_WS_URL` を更新する：

```bash
npx wrangler secret put PYTHON_WS_URL
# → Pythonサーバーの本番WebSocket URL を入力（例: wss://your-python-server.railway.app）
```

---

## 9. 動作確認

### Worker ヘルスチェック

```bash
curl https://color-vision-worker.<your-subdomain>.workers.dev/health
# → {"ok":true}
```

### D1 テーブル確認

```bash
cd worker
npx wrangler d1 execute color-vision-db --remote --command "SELECT name FROM sqlite_master WHERE type='table';"
# → sessions, color_snapshots が表示されればOK
```

### フロントエンド環境変数設定

`frontend/.env.local` を作成：

```bash
NUXT_PUBLIC_WORKER_URL=https://color-vision-worker.<your-subdomain>.workers.dev
NUXT_PUBLIC_ANALYZER_WS_URL=wss://your-python-server.railway.app
```

---

## 10. トラブルシューティング

### `wrangler login` が反応しない

- ブラウザのポップアップブロックを確認
- `npx wrangler login --browser=false` でURLをコピーして手動でアクセス

### `database_id` を忘れた場合

```bash
npx wrangler d1 list
```

### `KV namespace id` を忘れた場合

```bash
npx wrangler kv namespace list
```

### マイグレーションが失敗する

```bash
# 現在の適用済みマイグレーションを確認
npx wrangler d1 migrations list color-vision-db --remote
```

### デプロイ後にAPIが 401 を返す

`AUTH_SECRET` が設定されていない可能性がある。

```bash
npx wrangler secret list  # 登録済みシークレット一覧
npx wrangler secret put AUTH_SECRET  # 再設定
```

---

## 現在の設定値（このプロジェクト）

| リソース | 名前 | ID |
|---|---|---|
| D1 Database | color-vision-db | `853962ae-2006-46d1-97f5-25a69ff7b35e` |
| KV Namespace | COLOR_VISION_KV | `0e525676bccc4ddabe12f2528d6d4973` |

---

*最終更新: 2026-07-02*
