import { ref, onUnmounted } from 'vue'

/**
 * ColorHub（Cloudflare Durable Object）から色データを受信するだけのクライアント。
 *
 * useWebSocket との違い:
 *   useWebSocket … カメラのJPEGを送り、解析結果を受け取る（構成A・双方向）
 *   useColorHub  … 何も送らず、他が流した色を受け取るだけ（構成C・受信専用）
 *
 * これによりブラウザの仕事が「シェーダー描画のみ」になり、
 * カメラ取得・JPEG圧縮・送信の負荷が消える。
 * カメラと解析、LED駆動は Python 側（capture_pi.py）が担当する。
 */

export type PalettePayload = {
  mode: 'palette'
  source?: string
  dominant: [number, number, number]
  colors: { rgb: [number, number, number]; percentage: number }[]
}

export type MatrixPayload = {
  mode: 'matrix'
  source?: string
  width: number
  height: number
  pixels: [number, number, number][]
}

export type HubPayload = PalettePayload | MatrixPayload

const RECONNECT_MS = 2000

export function useColorHub(url: string, listenSource = '') {
  const isConnected = ref(false)
  /** 直近に受信したペイロードのモード（表示のデバッグ用） */
  const lastMode = ref<string>('')
  /** 直近に受信したペイロードの送信元拠点 */
  const lastSource = ref<string>('')
  /** 受信件数。0のまま増えなければ配信側が動いていない */
  const receivedCount = ref(0)
  /** フィルタで捨てた件数。listenSource の指定ミスに気づける */
  const filteredCount = ref(0)

  const onPalette = ref<((payload: PalettePayload) => void) | null>(null)
  const onMatrix = ref<((payload: MatrixPayload) => void) | null>(null)

  let ws: WebSocket | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let closedByUs = false

  function connect() {
    if (!url) {
      console.warn('[hub] URL が未設定です（NUXT_PUBLIC_COLORHUB_WS_URL）')
      return
    }

    ws = new WebSocket(url)

    ws.onopen = () => { isConnected.value = true }

    ws.onclose = () => {
      isConnected.value = false
      if (!closedByUs) {
        retryTimer = setTimeout(connect, RECONNECT_MS)
      }
    }

    ws.onerror = () => { isConnected.value = false }

    ws.onmessage = (event) => {
      let payload: HubPayload
      try {
        payload = JSON.parse(event.data)
      } catch {
        return  // JSON以外は無視
      }
      if (!payload || typeof payload !== 'object' || !('mode' in payload)) return

      // 拠点フィルタ。listenSource が空なら全て受け入れる
      const source = payload.source ?? ''
      if (listenSource && source !== listenSource) {
        filteredCount.value++
        return
      }

      receivedCount.value++
      lastMode.value = payload.mode
      lastSource.value = source

      if (payload.mode === 'palette') {
        onPalette.value?.(payload)
      } else if (payload.mode === 'matrix') {
        onMatrix.value?.(payload)
      }
    }
  }

  function disconnect() {
    closedByUs = true
    if (retryTimer) clearTimeout(retryTimer)
    ws?.close()
  }

  onUnmounted(disconnect)

  return {
    connect,
    disconnect,
    isConnected,
    lastMode,
    lastSource,
    receivedCount,
    filteredCount,
    onPalette,
    onMatrix,
  }
}
