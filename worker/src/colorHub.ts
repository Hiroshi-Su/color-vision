import { DurableObject } from 'cloudflare:workers'

/**
 * ColorHub — 色データの集会所（Durable Object）
 *
 * 全クライアント（Python analyzer / ブラウザ / ESP32）が同じWebSocketハブに接続し、
 * 受信したメッセージを送信者以外の全員にブロードキャストする。
 *
 * Hibernation API (`ctx.acceptWebSocket` / `ctx.getWebSockets`) を使用しているため、
 * DOが休止してもWebSocket接続は維持され、メモリ上の状態に依存しない。
 */
export class ColorHub extends DurableObject {
  async fetch(request: Request): Promise<Response> {
    const upgrade = request.headers.get('Upgrade')
    if (upgrade !== 'websocket') {
      return new Response('Expected WebSocket', { status: 426 })
    }

    const pair = new WebSocketPair()
    const [client, server] = Object.values(pair)

    this.ctx.acceptWebSocket(server)

    return new Response(null, { status: 101, webSocket: client })
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    // 休止復帰後もctx.getWebSockets()は接続中の全ソケットを返す
    for (const client of this.ctx.getWebSockets()) {
      if (client !== ws && client.readyState === WebSocket.READY_STATE_OPEN) {
        client.send(message)
      }
    }
  }

  async webSocketClose(ws: WebSocket, code: number) {
    ws.close(code, 'ColorHub closing')
  }

  async webSocketError(ws: WebSocket) {
    ws.close(1011, 'ColorHub error')
  }
}
