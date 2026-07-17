<script setup lang="ts">
const config = useRuntimeConfig()

type Snapshot = {
  id: number
  captured_at: string
  dominant_hex: string
  color1_hex: string
  color2_hex: string
  color3_hex: string
  color4_hex: string
  color5_hex: string
}

const { data: recent } = await useFetch<{ dominant_hex: string; captured_at: string }[]>(
  `${config.public.workerUrl}/api/colors/dominant/recent?limit=50`
)
</script>

<template>
  <div class="max-w-4xl mx-auto p-8">
    <div class="flex items-center gap-4 mb-8">
      <NuxtLink to="/" class="text-white/50 hover:text-white">← Back</NuxtLink>
      <h1 class="text-2xl font-bold tracking-widest uppercase">Color History</h1>
    </div>

    <div class="flex gap-1 h-20 rounded-xl overflow-hidden">
      <div
        v-for="(item, i) in recent"
        :key="i"
        class="flex-1 transition-all duration-300"
        :style="{ backgroundColor: item.dominant_hex }"
        :title="item.dominant_hex"
      />
    </div>

    <p class="text-white/30 text-sm mt-4 text-center">
      Recent {{ recent?.length ?? 0 }} dominant colors
    </p>
  </div>
</template>
