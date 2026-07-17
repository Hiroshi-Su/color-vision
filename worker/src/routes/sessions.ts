import { Hono } from 'hono'

type Bindings = {
  DB: D1Database
  PERSIST_ENABLED: string
}

const sessions = new Hono<{ Bindings: Bindings }>()

sessions.post('/', async (c) => {
  // Web標準のcrypto（Workersネイティブ）を使用。node:crypto依存を排除
  const id = crypto.randomUUID()
  const startedAt = new Date().toISOString()
  // 永続化オフ時はIDだけ発行してD1には書き込まない（フロントエンドは変更不要）
  if (c.env.PERSIST_ENABLED === 'true') {
    await c.env.DB.prepare('INSERT INTO sessions (id, started_at) VALUES (?, ?)').bind(id, startedAt).run()
  }
  return c.json({ id, startedAt })
})

sessions.patch('/:id/end', async (c) => {
  const id = c.req.param('id')
  const endedAt = new Date().toISOString()
  if (c.env.PERSIST_ENABLED === 'true') {
    await c.env.DB.prepare('UPDATE sessions SET ended_at = ? WHERE id = ?').bind(endedAt, id).run()
  }
  return c.json({ success: true })
})

sessions.get('/', async (c) => {
  const { results } = await c.env.DB.prepare('SELECT * FROM sessions ORDER BY started_at DESC LIMIT 50').all()
  return c.json(results)
})

export default sessions
