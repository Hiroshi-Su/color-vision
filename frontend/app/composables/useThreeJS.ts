import { ref, onUnmounted } from 'vue'
import * as THREE from 'three'

type ColorEntry = { rgb: [number, number, number]; percentage: number }

const LERP_FACTOR = 0.08  // 小さいほど遅くなめらか、大きいほど速い

export function useThreeJS(canvas: Ref<HTMLCanvasElement | null>) {
  const renderer = ref<THREE.WebGLRenderer | null>(null)
  const scene = new THREE.Scene()
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1)
  let animId = 0

  // 現在値（lerp済み）とターゲット値（最新データ）を分離
  const currentColors = Array(5).fill(null).map(() => new THREE.Color(0, 0, 0))
  const targetColors = Array(5).fill(null).map(() => new THREE.Color(0, 0, 0))
  const currentPercentages = Array(5).fill(0)
  const targetPercentages = Array(5).fill(0)

  const uniforms = {
    uColors: { value: currentColors },
    uPercentages: { value: currentPercentages },
    uColorCount: { value: 0 },
    uTime: { value: 0 },
  }

  function init() {
    if (!canvas.value) return

    renderer.value = new THREE.WebGLRenderer({ canvas: canvas.value, antialias: true })
    renderer.value.setPixelRatio(window.devicePixelRatio)
    renderer.value.setSize(canvas.value.clientWidth, canvas.value.clientHeight)

    const geo = new THREE.PlaneGeometry(2, 2)
    const mat = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: `
        varying vec2 vUv;
        void main() { vUv = uv; gl_Position = vec4(position, 1.0); }
      `,
      fragmentShader: `
        uniform vec3 uColors[5];
        uniform float uPercentages[5];
        uniform float uTime;
        uniform int uColorCount;
        varying vec2 vUv;
        void main() {
          float total = 0.0;
          for (int i = 0; i < 5; i++) total += uPercentages[i];
          if (total == 0.0) { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }
          float x = vUv.x * total;
          float acc = 0.0;
          vec3 color = uColors[0];
          for (int i = 0; i < 5; i++) {
            if (i >= uColorCount) break;
            float next = acc + uPercentages[i];
            if (x >= acc && x < next) { color = uColors[i]; break; }
            acc = next;
          }
          float wave = sin(vUv.y * 15.0 + uTime) * 0.015;
          color += wave;
          gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
        }
      `,
    })

    scene.add(new THREE.Mesh(geo, mat))

    const tick = () => {
      uniforms.uTime.value += 0.016

      // 毎フレーム current を target に向けて lerp
      for (let i = 0; i < 5; i++) {
        currentColors[i].lerp(targetColors[i], LERP_FACTOR)
        currentPercentages[i] += (targetPercentages[i] - currentPercentages[i]) * LERP_FACTOR
      }

      renderer.value?.render(scene, camera)
      animId = requestAnimationFrame(tick)
    }
    tick()
  }

  function updateColors(colors: ColorEntry[]) {
    uniforms.uColorCount.value = colors.length
    // ターゲットだけ更新。currentはtickで徐々に近づく
    colors.forEach((c, i) => {
      targetColors[i].setRGB(c.rgb[0] / 255, c.rgb[1] / 255, c.rgb[2] / 255)
      targetPercentages[i] = c.percentage
    })
    // 使われていない枠はゼロに
    for (let i = colors.length; i < 5; i++) {
      targetPercentages[i] = 0
    }
  }

  function dispose() {
    cancelAnimationFrame(animId)
    renderer.value?.dispose()
  }

  onUnmounted(dispose)

  return { init, updateColors }
}
