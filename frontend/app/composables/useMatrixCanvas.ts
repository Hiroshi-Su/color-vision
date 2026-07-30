import { ref, onUnmounted } from 'vue'
import type { Ref } from 'vue'

/**
 * matrixペイロード（左上原点・行優先の W×H グリッド）を canvas に描く。
 *
 * 受信専用ビュー（/view）でLEDパネルの映像をディスプレイに映すために使う。
 * 小さな W×H のオフスクリーンにピクセルを置き、それを画面いっぱいに
 * 拡大コピーする。拡大時の補間を切り替えられる:
 *
 *   crisp  = true  … 最近傍（LEDのマス目がくっきり。既定・LED忠実）
 *   crisp  = false … バイリニア（マス間をなめらかに補間・映像的）
 *
 * グリッドの縦横比は保ったまま中央に収める（レターボックス）。
 * 画面比とグリッド比が違ってもマスが歪まない。
 */

type MatrixLike = {
  width: number
  height: number
  pixels: [number, number, number][]
}

export function useMatrixCanvas(canvas: Ref<HTMLCanvasElement | null>) {
  const crisp = ref(true)
  // 直近のペイロードを保持しておき、リサイズ時に再描画する
  let last: MatrixLike | null = null
  // W×H の等倍オフスクリーン（ここに実ピクセルを置く）
  let offscreen: HTMLCanvasElement | null = null

  function ensureOffscreen(width: number, height: number): HTMLCanvasElement {
    if (!offscreen || offscreen.width !== width || offscreen.height !== height) {
      offscreen = document.createElement('canvas')
      offscreen.width = width
      offscreen.height = height
    }
    return offscreen
  }

  function draw(payload: MatrixLike) {
    last = payload
    const el = canvas.value
    if (!el) return
    const { width, height, pixels } = payload
    if (!width || !height || pixels.length < width * height) return

    // 表示canvasを実ピクセルサイズに合わせる（DPR考慮）
    const dpr = window.devicePixelRatio || 1
    const cssW = el.clientWidth
    const cssH = el.clientHeight
    if (el.width !== Math.round(cssW * dpr) || el.height !== Math.round(cssH * dpr)) {
      el.width = Math.round(cssW * dpr)
      el.height = Math.round(cssH * dpr)
    }

    const ctx = el.getContext('2d')
    if (!ctx) return

    // オフスクリーンに W×H を1マス=1pxで書き込む
    const off = ensureOffscreen(width, height)
    const octx = off.getContext('2d')
    if (!octx) return
    const img = octx.createImageData(width, height)
    for (let i = 0; i < width * height; i++) {
      const p = pixels[i]
      const j = i * 4
      img.data[j] = p[0]
      img.data[j + 1] = p[1]
      img.data[j + 2] = p[2]
      img.data[j + 3] = 255
    }
    octx.putImageData(img, 0, 0)

    // グリッド比を保って中央に収める（contain）
    const scale = Math.min(el.width / width, el.height / height)
    const drawW = width * scale
    const drawH = height * scale
    const dx = (el.width - drawW) / 2
    const dy = (el.height - drawH) / 2

    ctx.fillStyle = '#000'
    ctx.fillRect(0, 0, el.width, el.height)
    ctx.imageSmoothingEnabled = !crisp.value
    ctx.drawImage(off, 0, 0, width, height, dx, dy, drawW, drawH)
  }

  /** 画面リサイズ時、直近のフレームを新しいサイズで描き直す */
  function redraw() {
    if (last) draw(last)
  }

  function setCrisp(value: boolean) {
    crisp.value = value
    redraw()
  }

  let ro: ResizeObserver | null = null
  function observe() {
    if (typeof ResizeObserver !== 'undefined' && canvas.value) {
      ro = new ResizeObserver(() => redraw())
      ro.observe(canvas.value)
    }
  }

  onUnmounted(() => ro?.disconnect())

  return { draw, redraw, setCrisp, crisp, observe }
}
