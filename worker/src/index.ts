import { Hono } from 'hono'
import type { MiddlewareHandler } from 'hono'
import { cors } from 'hono/cors'
import { bearerAuth } from 'hono/bearer-auth'
import colorsRouter from './routes/colors'
import sessionsRouter from './routes/sessions'

export { ColorHub } from './colorHub'

type Bindings = {
  DB: D1Database
  KV: KVNamespace
  COLOR_HUB: DurableObjectNamespace
  AUTH_SECRET: string
  PYTHON_WS_URL: string
  PERSIST_ENABLED: string
}

const app = new Hono<{ Bindings: Bindings }>()

app.use('*', cors())
// GETは公開、POST/PATCH/DELETEのみ認証必須
app.use('/api/*', async (c, next) => {
  if (c.req.method === 'GET') return next()
  const auth = bearerAuth({ token: c.env.AUTH_SECRET }) as MiddlewareHandler<{ Bindings: Bindings }>
  return auth(c, next)
})

app.route('/api/colors', colorsRouter)
app.route('/api/sessions', sessionsRouter)

// WebSocket → ColorHub（Python / ブラウザ / ESP32 が同じハブに接続）
app.get('/ws', (c) => {
  if (c.req.header('Upgrade') !== 'websocket') {
    return c.text('Expected WebSocket', 426)
  }
  const id = c.env.COLOR_HUB.idFromName('global')
  return c.env.COLOR_HUB.get(id).fetch(c.req.raw)
})

app.get('/health', (c) => c.json({ ok: true }))

export default app
