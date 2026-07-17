import { Hono } from 'hono'

type Bindings = {
  DB: D1Database
  KV: KVNamespace
  PERSIST_ENABLED: string
}

type ColorEntry = {
  hex: string
  rgb: [number, number, number]
  hsl: { h: number; s: number; l: number }
  percentage: number
}

type SnapshotBody = {
  sessionId: string
  colors: ColorEntry[]
  dominant: string
  saveType: 'realtime' | 'longterm'
}

const colors = new Hono<{ Bindings: Bindings }>()

colors.post('/snapshot', async (c) => {
  // 永続化オフ時は何も保存せず成功を返す（フロントエンドは変更不要）
  if (c.env.PERSIST_ENABLED !== 'true') {
    return c.json({ success: true, persisted: false })
  }

  const body = await c.req.json<SnapshotBody>()
  const { sessionId, colors: colorData, dominant, saveType } = body

  const kvKey = `session:${sessionId}:latest`
  try {
    await c.env.KV.put(kvKey, JSON.stringify({ colors: colorData, dominant, updatedAt: new Date().toISOString() }), { expirationTtl: 1800 })
  } catch (e) {
    // KV は429レート制限に達しても致命的エラーにしない（キャッシュなので）
    console.error('KV write failed (non-fatal):', e)
  }

  if (saveType === 'longterm') {
    const now = new Date().toISOString()
    const cols = colorData.slice(0, 5)
    await c.env.DB.prepare(`
      INSERT INTO color_snapshots
        (session_id, captured_at, color1_hex, color1_pct, color2_hex, color2_pct,
         color3_hex, color3_pct, color4_hex, color4_pct, color5_hex, color5_pct, dominant_hex)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      sessionId, now,
      cols[0]?.hex ?? null, cols[0]?.percentage ?? null,
      cols[1]?.hex ?? null, cols[1]?.percentage ?? null,
      cols[2]?.hex ?? null, cols[2]?.percentage ?? null,
      cols[3]?.hex ?? null, cols[3]?.percentage ?? null,
      cols[4]?.hex ?? null, cols[4]?.percentage ?? null,
      dominant
    ).run()
  }

  return c.json({ success: true })
})

colors.get('/history/:sessionId', async (c) => {
  const sessionId = c.req.param('sessionId')
  const { results } = await c.env.DB.prepare(
    'SELECT * FROM color_snapshots WHERE session_id = ? ORDER BY captured_at ASC'
  ).bind(sessionId).all()
  return c.json(results)
})

colors.get('/dominant/recent', async (c) => {
  const limit = Number(c.req.query('limit') ?? 50)
  const { results } = await c.env.DB.prepare(
    'SELECT dominant_hex, captured_at FROM color_snapshots ORDER BY captured_at DESC LIMIT ?'
  ).bind(limit).all()
  return c.json(results)
})

export default colors
