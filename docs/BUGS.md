# 🐛 バグ管理・対処ログ

Color Vision プロジェクトのバグを記録・追跡する台帳。新しいバグは一覧の先頭に追記する。

> ※ このディレクトリ（`docs/`）は `.gitignore` 済みのローカル専用ドキュメント。

## ステータス凡例

| 記号 | 意味 |
|---|---|
| 🔴 Open | 未対処 |
| 🟡 In Progress | 調査・対応中 |
| 🟢 Fixed | 修正済み |
| ⚪️ Won't Fix / 保留 | 対応しない・保留 |

## 一覧

| ID | 重要度 | 状態 | 概要 | 発見日 |
|---|---|---|---|---|
| BUG-001 | 中 | 🔴 Open | `/api/sessions` が 400 で色履歴のD1/KV保存が無効化される | 2026-07-21 |

---

## BUG-001 — `/api/sessions` が 400 Bad Request、色履歴の保存が無効化される

- **重要度:** 中（可視化・LED出力には影響なし。履歴保存機能のみ無効）
- **状態:** 🔴 Open（未対処）
- **発見日:** 2026-07-21
- **関連:** Cloudflare リソース（D1/KV）作成・Wrangler ログインが未完了の可能性

### 症状（ブラウザコンソール）

`/`（index）ページを開いた直後に発生：

```
color-vision-worker.color-vision.workers.dev/api/sessions:1
  Failed to load resource: the server responded with a status of 400 ()
Session creation failed, storage disabled
  SyntaxError: Unexpected token 'B', "Bad Request" is not valid JSON
```

- `POST /api/sessions` が **400 Bad Request** を返す
- レスポンス本文が `Bad Request`（プレーンテキスト）のため、フロントの `res.json()` が JSON パースで失敗
- `index.vue` の `catch` が握りつぶし、`Session creation failed, storage disabled` を出して**履歴保存を無効化**（アプリは落ちない）

### 再現手順

1. analyzer と worker（デプロイ済み）が動く状態で `/` を開く
2. `onMounted` で `POST ${workerUrl}/api/sessions` が実行される
3. 400 が返り、以降 `sessionId` が空のまま → スナップショット保存が全てスキップされる

### 影響範囲

- ❌ 色スナップショットの **KV キャッシュ / D1 永続保存**が効かない
- ❌ `/history` にデータが溜まらない
- ✅ リアルタイム可視化（Three.js）・**matrix / palette の LED 出力には影響なし**
- ⚠️ リロード（HMR）とは**無関係**（別件）

### 該当箇所

| ファイル | 内容 |
|---|---|
| `frontend/app/pages/index.vue` | `onMounted` で `POST /api/sessions`（`Authorization: Bearer ${authToken}`）→ 失敗を catch |
| `worker/src/index.ts` | `/api/*` の非GETに `bearerAuth({ token: AUTH_SECRET })` を適用 |
| `worker/src/routes/sessions.ts` | `POST /` はIDを発行し、`PERSIST_ENABLED==='true'` の時のみ D1 に INSERT |

### 原因の仮説（未確定・確度順）

1. **Authorization ヘッダが不正（空トークン）** — Hono の `bearerAuth` は
   `Authorization` が `Bearer <token>` 形式に一致しないと **400 "Bad Request"** を返す
   （トークン不一致なら 401、ヘッダ欠落なら 401）。400 が出ている＝
   **ヘッダが `Bearer `（トークン空）になっている**可能性が高い。
   → 実行中の dev サーバーに `NUXT_PUBLIC_AUTH_TOKEN` が読み込まれていない疑い
   （`.env.local` 追加前に起動した／読み込まれていない 等）。
2. **デプロイ済み Worker 側の設定不足** — `AUTH_SECRET` / `PERSIST_ENABLED` / D1 バインディングが
   未設定。プロジェクトの「次のステップ（D1/KV作成・Wranglerログイン）」が未完了なことと符合。

> 補足: 400 という値が手がかり。401 ならトークン不一致・ヘッダ欠落だが、
> 今回は 400 なので「ヘッダはあるが形式が壊れている（＝トークンが空）」が最有力。

### 対処案 / 次アクション

- [ ] DevTools > Network で `POST /api/sessions` の**リクエスト `Authorization` ヘッダ**を確認
      （`Bearer ` の後が空でないか）とレスポンス本文を確認
- [ ] `NUXT_PUBLIC_AUTH_TOKEN` が実行中の dev サーバーに反映されているか確認
      （`.env.local` 追加後は `npm run dev` を再起動）
- [ ] デプロイ済み Worker の `AUTH_SECRET` がフロントの token と一致しているか確認
      （`wrangler secret list` 等）
- [ ] Cloudflare セットアップ完了（`wrangler login`、D1/KV 作成、`PERSIST_ENABLED=true`）
- [ ] 副次改善: フロントの `res.json()` を `res.ok` チェック後に呼ぶようにし、
      非JSONレスポンスでの `SyntaxError` を避ける（エラーメッセージを分かりやすく）

### 回避策

- 可視化・LED 用途では**対応不要**（保存が静かに無効化されるだけでアプリは正常動作）
- 履歴機能が必要になった時点で上記の対処を行う
