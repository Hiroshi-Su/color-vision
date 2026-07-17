export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: true },
  ssr: false,

  modules: ['@nuxtjs/tailwindcss', '@vueuse/nuxt'],

  nitro: {
    preset: process.env.NODE_ENV === 'production' ? 'cloudflare-pages' : undefined,
  },

  runtimeConfig: {
    public: {
      workerUrl: process.env.NUXT_PUBLIC_WORKER_URL ?? 'https://color-vision-worker.color-vision.workers.dev',
      analyzerWsUrl: process.env.NUXT_PUBLIC_ANALYZER_WS_URL ?? 'ws://localhost:8765',
      authToken: process.env.NUXT_PUBLIC_AUTH_TOKEN ?? '',
    },
  },

  vite: {
    assetsInclude: ['**/*.vert', '**/*.frag'],
  },
})
