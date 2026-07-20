<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useWebSocket } from '~/composables/useWebSocket'

const config = useRuntimeConfig()
const videoRef = ref<HTMLVideoElement | null>(null)
const gridCanvasRef = ref<HTMLCanvasElement | null>(null)

const { connect, sendFrame, isConnected, onColorUpdate } = useWebSocket(config.public.analyzerWsUrl)

// matrixの解像度（analyzerから受け取った値で確定する）
const gridW = ref(0)
const gridH = ref(0)
const hasMatrix = ref(false)
// 診断用ステータス
const cameraOk = ref(false)
const cameraError = ref('')
const framesReceived = ref(0)
const matrixMissing = ref(false) // 受信はするがmatrixフィールドが無い（=analyzerがpaletteモード）

const CELL = 22 // 1マスの表示ピクセル

onColorUpdate.value = (result) => {
  framesReceived.value++
  const m = result.matrix
  if (!m) {
    matrixMissing.value = true
    return
  }
  matrixMissing.value = false
  hasMatrix.value = true
  gridW.value = m.width
  gridH.value = m.height

  const canvas = gridCanvasRef.value
  if (!canvas) return
  canvas.width = m.width * CELL
  canvas.height = m.height * CELL
  const ctx = canvas.getContext('2d')!

  // pixels は左上原点・行優先（analyzer/hub.py と同じ向き）
  for (let i = 0; i < m.pixels.length; i++) {
    const x = i % m.width
    const y = Math.floor(i / m.width)
    const [r, g, b] = m.pixels[i]!
    ctx.fillStyle = `rgb(${r},${g},${b})`
    ctx.fillRect(x * CELL, y * CELL, CELL, CELL)
  }
}

onMounted(async () => {
  const captureCanvas = document.createElement('canvas')
  captureCanvas.width = 320
  captureCanvas.height = 240

  connect()

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240 } })
    if (videoRef.value) {
      videoRef.value.srcObject = stream
      videoRef.value.play()
    }
    cameraOk.value = true
  } catch (e) {
    // 別タブ（/ など）がカメラを専有している / 権限拒否 などで失敗する
    cameraError.value = (e as Error)?.message || String(e)
    console.error('getUserMedia failed:', e)
  }

  const ctx = captureCanvas.getContext('2d')!
  // カメラ取得の成否に関わらずループは張り、cameraOk時のみ送信する
  setInterval(() => {
    if (!videoRef.value || !isConnected.value || !cameraOk.value) return
    ctx.drawImage(videoRef.value, 0, 0, 320, 240)
    captureCanvas.toBlob((blob) => { if (blob) sendFrame(blob) }, 'image/jpeg', 0.7)
  }, 1000 / 30)
})
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-screen gap-6 p-4">
    <h1 class="text-2xl font-bold tracking-widest uppercase">Matrix Preview</h1>

    <!-- 診断パネル -->
    <div class="text-xs text-white/60 flex flex-col items-center gap-1">
      <div class="flex gap-3">
        <span :class="isConnected ? 'text-green-400' : 'text-red-400'">
          WS: {{ isConnected ? '接続' : '未接続' }}
        </span>
        <span :class="cameraOk ? 'text-green-400' : 'text-red-400'">
          カメラ: {{ cameraOk ? 'OK' : (cameraError ? 'エラー' : '取得中…') }}
        </span>
        <span>受信: {{ framesReceived }} フレーム</span>
      </div>
      <p v-if="cameraError" class="text-red-400/90 text-center max-w-md">
        カメラ取得失敗: {{ cameraError }}<br>
        （<code>/</code> など他タブがカメラ使用中の可能性。他タブを閉じて再読み込みしてください）
      </p>
      <p v-if="matrixMissing" class="text-yellow-400/90 text-center max-w-md">
        フレームは届いていますが matrix が含まれません。analyzer を <code>LED_MODE=matrix</code> で起動してください。
      </p>
    </div>

    <p v-if="hasMatrix" class="text-sm text-white/50">
      {{ gridW }} × {{ gridH }} = {{ gridW * gridH }} マス（左上原点）
    </p>

    <div class="flex flex-wrap gap-6 items-start justify-center">
      <div class="relative w-80 h-60 rounded-xl overflow-hidden border border-white/10">
        <video ref="videoRef" class="w-full h-full object-cover" muted playsinline />
        <div class="absolute top-2 right-2 text-xs px-2 py-1 rounded-full"
          :class="isConnected ? 'bg-green-500/80' : 'bg-red-500/80'">
          {{ isConnected ? 'LIVE' : 'CONNECTING' }}
        </div>
      </div>

      <canvas ref="gridCanvasRef" class="rounded-xl border border-white/10" />
    </div>

    <NuxtLink to="/" class="text-sm text-white/50 hover:text-white transition-colors">
      ← Back to Visualizer
    </NuxtLink>
  </div>
</template>
