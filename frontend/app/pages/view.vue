<script setup lang="ts">
/**
 * 受信専用ビュー（構成C）
 *
 * カメラを使わず、ColorHubから流れてくる色データを受け取って描画するだけのページ。
 * palette（帯グラフ）と matrix（低解像度グリッド）の両方に対応し、
 * 届いたモードに応じて自動で表示を切り替える。
 *
 * カメラ・解析・LED駆動は Python（capture_pi.py）が担当するため、
 * ブラウザの仕事は描画のみになりPi 4でも軽く動く。
 *
 * URLパラメータ:
 *   ?source=kanazawa   その拠点の色だけ表示（省略時は全拠点を受け入れる）
 *   ?url=wss://...     接続先を上書き（既定は NUXT_PUBLIC_COLORHUB_WS_URL）
 *   ?ui=0              ステータス表示を隠す（展示・全画面用）
 *   ?smooth=1          matrixのマス間をなめらかに補間（既定はLED忠実のくっきり表示）
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useColorHub } from '~/composables/useColorHub'
import { useThreeJS } from '~/composables/useThreeJS'
import { useMatrixCanvas } from '~/composables/useMatrixCanvas'

const config = useRuntimeConfig()
const route = useRoute()

const hubUrl = (route.query.url as string) || config.public.colorHubWsUrl
const listenSource = (route.query.source as string) ?? ''
const showUi = route.query.ui !== '0'
const smooth = route.query.smooth === '1'

const paletteCanvasRef = ref<HTMLCanvasElement | null>(null)
const matrixCanvasRef = ref<HTMLCanvasElement | null>(null)

// 直近に描画したモード。palette/matrix でcanvasの表示を切り替える
const activeMode = ref<'palette' | 'matrix' | ''>('')

const { init, updateColors } = useThreeJS(paletteCanvasRef)
const matrixCanvas = useMatrixCanvas(matrixCanvasRef)
matrixCanvas.crisp.value = !smooth

const {
  connect, isConnected, lastMode, lastSource, receivedCount, filteredCount,
  onPalette, onMatrix,
} = useColorHub(hubUrl, listenSource)

onPalette.value = (payload) => {
  activeMode.value = 'palette'
  updateColors(payload.colors)
}

onMatrix.value = (payload) => {
  activeMode.value = 'matrix'
  matrixCanvas.draw(payload)
}

// 受信が始まっていないときに原因を出す
const hint = computed(() => {
  if (!hubUrl) return 'NUXT_PUBLIC_COLORHUB_WS_URL が未設定です'
  if (!isConnected.value) return '接続中…'
  if (receivedCount.value === 0 && filteredCount.value > 0) {
    return `?source=${listenSource} に一致しない色のみ届いています（${filteredCount.value}件を除外）`
  }
  if (receivedCount.value === 0) {
    return '接続済み。配信側（capture_pi.py）の COLORHUB_WS_URL を確認してください'
  }
  return ''
})

onMounted(() => {
  init()
  matrixCanvas.observe()
  connect()
})
</script>

<template>
  <div class="relative min-h-screen bg-black">
    <!-- palette用（Three.js/WebGL）。matrix受信中は隠す -->
    <canvas
      ref="paletteCanvasRef"
      class="absolute inset-0 w-screen h-screen block"
      :class="activeMode === 'matrix' ? 'hidden' : ''"
    />
    <!-- matrix用（2D）。palette受信中は隠す -->
    <canvas
      ref="matrixCanvasRef"
      class="absolute inset-0 w-screen h-screen block"
      :class="activeMode === 'matrix' ? '' : 'hidden'"
    />

    <div v-if="showUi" class="absolute top-0 left-0 p-4 flex flex-col gap-2 pointer-events-none">
      <div class="flex items-center gap-2">
        <span
          class="text-xs px-2 py-1 rounded-full"
          :class="isConnected ? 'bg-green-500/80' : 'bg-red-500/80'"
        >{{ isConnected ? 'RECEIVING' : 'CONNECTING' }}</span>
        <span class="text-xs text-white/60">
          {{ listenSource || 'all sources' }}
        </span>
      </div>

      <div v-if="receivedCount > 0" class="text-xs text-white/40">
        {{ lastMode }} / {{ lastSource || 'no tag' }} / {{ receivedCount }} received
      </div>

      <div v-if="hint" class="text-xs text-yellow-400/80 max-w-md">
        {{ hint }}
      </div>
    </div>

    <NuxtLink
      v-if="showUi"
      to="/"
      class="absolute bottom-4 left-4 text-xs text-white/40 hover:text-white transition-colors"
    >← Camera mode</NuxtLink>
  </div>
</template>
