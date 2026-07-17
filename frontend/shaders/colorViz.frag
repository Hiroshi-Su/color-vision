uniform vec3 uColors[5];
uniform float uPercentages[5];
uniform float uTime;
uniform int uColorCount;

varying vec2 vUv;

float smoothstep2(float a, float b, float x) {
  float t = clamp((x - a) / (b - a), 0.0, 1.0);
  return t * t * (3.0 - 2.0 * t);
}

void main() {
  float total = 0.0;
  for (int i = 0; i < 5; i++) {
    total += uPercentages[i];
  }

  float x = vUv.x * total;
  float acc = 0.0;
  vec3 color = uColors[0];

  for (int i = 0; i < 5; i++) {
    if (i >= uColorCount) break;
    float next = acc + uPercentages[i];
    if (x >= acc && x < next) {
      float wave = sin(vUv.y * 20.0 + uTime * 2.0) * 0.01;
      float blend = smoothstep2(acc, acc + 0.5, x + wave);
      color = (i == 0) ? uColors[0] : mix(uColors[i - 1], uColors[i], blend);
      break;
    }
    acc = next;
  }

  gl_FragColor = vec4(color, 1.0);
}
