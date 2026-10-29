<script setup lang="ts">
/* Os ícones do transporte do player (início, quadro, play, pause, fim, voltar, parar, avançar, volume), em traço
   de 24x24 como os outros ícones da interface. Ficam aqui para não mexer na lista compartilhada dos ícones. */
export type TransportIconName =
  | 'start'
  | 'step-back'
  | 'play'
  | 'pause'
  | 'step-forward'
  | 'end'
  | 'rewind'
  | 'stop'
  | 'forward'
  | 'volume'

defineProps<{ name: TransportIconName; size?: number }>()

const paths: Record<TransportIconName, string> = {
  start: 'M6 5v14M19 5 9 12l10 7z',
  'step-back': 'M15 5l-7 7 7 7',
  play: 'M7 4v16l13-8z',
  pause: 'M8 5v14M16 5v14',
  'step-forward': 'M9 5l7 7-7 7',
  end: 'M18 5v14M5 5l10 7L5 19z',
  rewind: 'M11 5 3 12l8 7zM21 5l-8 7 8 7z',
  stop: 'M6 6h12v12H6z',
  forward: 'M13 5l8 7-8 7zM3 5l8 7-8 7z',
  volume: 'M4 9v6h4l5 4V5L8 9zM16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11',
}
</script>

<template>
  <svg
    :width="size ?? 18"
    :height="size ?? 18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path :d="paths[name]" />
  </svg>
</template>
