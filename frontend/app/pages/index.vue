<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useWebSocket } from '~/composables/useWebSocket'
import { useThreeJS } from '~/composables/useThreeJS'
import { useColorStorage } from '~/composables/useColorStorage'

const config = useRuntimeConfig()
const videoRef = ref<HTMLVideoElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const sessionId = ref<string>('')

const { connect, sendFrame, isConnected, onColorUpdate } = useWebSocket(config.public.analyzerWsUrl)
const { init, updateColors } = useThreeJS(canvasRef)
const { maybeSave } = useColorStorage(
  sessionId,
  config.public.workerUrl,
  config.public.authToken,
)

onColorUpdate.value = (result) => {
  updateColors(result.colors)
  if (sessionId.value) {
    maybeSave(result.colors, result.dominant)
  }
}

onMounted(async () => {
  const captureCanvas = document.createElement('canvas')
  captureCanvas.width = 320
  captureCanvas.height = 240

  // セッション作成
  try {
    const res = await fetch(`${config.public.workerUrl}/api/sessions`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${config.public.authToken}` },
    })
    const data = await res.json() as { id: string }
    sessionId.value = data.id
  } catch (e) {
    console.warn('Session creation failed, storage disabled', e)
  }

  init()
  connect()

  const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240 } })
  if (videoRef.value) {
    videoRef.value.srcObject = stream
    videoRef.value.play()
  }

  const ctx = captureCanvas.getContext('2d')!
  setInterval(() => {
    if (!videoRef.value || !isConnected.value) return
    ctx.drawImage(videoRef.value, 0, 0, 320, 240)
    captureCanvas.toBlob((blob) => { if (blob) sendFrame(blob) }, 'image/jpeg', 0.7)
  }, 1000 / 30)
})
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-screen gap-6 p-4">
    <h1 class="text-2xl font-bold tracking-widest uppercase">Color Vision</h1>

    <div class="flex gap-6 w-full max-w-5xl">
      <div class="relative w-80 h-60 rounded-xl overflow-hidden border border-white/10">
        <video ref="videoRef" class="w-full h-full object-cover" muted playsinline />
        <div class="absolute top-2 right-2 text-xs px-2 py-1 rounded-full"
          :class="isConnected ? 'bg-green-500/80' : 'bg-red-500/80'">
          {{ isConnected ? 'LIVE' : 'CONNECTING' }}
        </div>
      </div>

      <canvas ref="canvasRef" class="flex-1 h-60 rounded-xl" />
    </div>

    <NuxtLink to="/history" class="text-sm text-white/50 hover:text-white transition-colors">
      View History →
    </NuxtLink>
  </div>
</template>
