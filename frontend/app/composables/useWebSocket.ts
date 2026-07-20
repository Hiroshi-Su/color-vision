import { ref, onUnmounted } from 'vue'

type ColorEntry = {
  hex: string
  rgb: [number, number, number]
  hsl: { h: number; s: number; l: number }
  percentage: number
}

type MatrixPayload = {
  mode: 'matrix'
  width: number
  height: number
  pixels: [number, number, number][]
}

type ColorResult = {
  colors: ColorEntry[]
  dominant: string
  // analyzerがmatrixモードのとき同梱される（プレビュー用）
  matrix?: MatrixPayload
}

export function useWebSocket(url: string) {
  const ws = ref<WebSocket | null>(null)
  const isConnected = ref(false)
  const lastResult = ref<ColorResult | null>(null)
  const onColorUpdate = ref<((result: ColorResult) => void) | null>(null)

  function connect() {
    ws.value = new WebSocket(url)

    ws.value.onopen = () => { isConnected.value = true }
    ws.value.onclose = () => {
      isConnected.value = false
      setTimeout(connect, 2000)
    }
    ws.value.onmessage = (event) => {
      const result: ColorResult = JSON.parse(event.data)
      lastResult.value = result
      onColorUpdate.value?.(result)
    }
  }

  function sendFrame(blob: Blob) {
    if (ws.value?.readyState === WebSocket.OPEN) {
      ws.value.send(blob)
    }
  }

  function disconnect() {
    ws.value?.close()
  }

  onUnmounted(disconnect)

  return { connect, disconnect, sendFrame, isConnected, lastResult, onColorUpdate }
}
