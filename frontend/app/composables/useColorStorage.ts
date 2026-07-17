import { ref } from 'vue'

type ColorEntry = {
  hex: string
  rgb: [number, number, number]
  hsl: { h: number; s: number; l: number }
  percentage: number
}

// KV無料枠: 1,000書き込み/日 → 10分間隔 = 144回/日（安全圏）
// D1無料枠: 100,000書き込み/日 → 5分間隔 = 288回/日（安全圏）
const KV_INTERVAL_MS = 600_000  // 10分
const D1_INTERVAL_MS = 300_000  // 5分

export function useColorStorage(sessionId: Ref<string>, workerUrl: string, authToken: string) {
  const lastKvSave = ref(0)
  const lastD1Save = ref(0)

  async function maybeSave(colors: ColorEntry[], dominant: string) {
    if (!sessionId.value) return

    const now = Date.now()
    const kvDue = now - lastKvSave.value >= KV_INTERVAL_MS
    const d1Due = now - lastD1Save.value >= D1_INTERVAL_MS

    if (!kvDue && !d1Due) return

    const saveType = d1Due ? 'longterm' : 'realtime'

    try {
      await fetch(`${workerUrl}/api/colors/snapshot`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ sessionId: sessionId.value, colors, dominant, saveType }),
      })

      if (kvDue) lastKvSave.value = now
      if (d1Due) lastD1Save.value = now
    } catch (e) {
      console.warn('Color save failed', e)
    }
  }

  return { maybeSave }
}
