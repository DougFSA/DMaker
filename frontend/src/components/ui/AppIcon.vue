<script setup lang="ts">
/* Ícones de traço (24x24) escritos como caminhos SVG, para não depender de pacote de ícones. */
import { computed } from 'vue'

export type IconName =
  | 'folder'
  | 'film'
  | 'mic'
  | 'languages'
  | 'queue'
  | 'layers'
  | 'video'
  | 'search'
  | 'plus'
  | 'play'
  | 'download'
  | 'check'
  | 'alert'
  | 'info'
  | 'x'
  | 'sun'
  | 'moon'
  | 'chevron-left'
  | 'chevron-right'
  | 'chevron-down'
  | 'activity'
  | 'external'
  | 'grid'
  | 'list'
  | 'file'
  | 'upload'
  | 'sparkles'
  | 'arrow-left'

const paths: Record<IconName, string> = {
  folder: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  film: 'M4 4h16v16H4zM8 4v16M16 4v16M4 9h4M4 15h4M16 9h4M16 15h4',
  mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM6 11a6 6 0 0 0 12 0M12 17v4M9 21h6',
  languages: 'M4 5h8M8 3v2M5 9c1.5 3 4 5 7 6M11 5c-.5 4-3 8-7 10M13 21l4-10 4 10M14.5 18h5',
  queue: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  layers: 'M12 3 3 8l9 5 9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5',
  video: 'M3 6h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H3zM17 10l4-2v8l-4-2',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-4.3-4.3',
  plus: 'M12 5v14M5 12h14',
  play: 'M7 4v16l13-8z',
  download: 'M12 4v11M7 11l5 5 5-5M5 20h14',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  alert: 'M12 3 2 20h20zM12 10v4.5M12 17.5h.01',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v5M12 8h.01',
  x: 'M6 6l12 12M18 6 6 18',
  sun: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
  moon: 'M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z',
  'chevron-left': 'M15 5l-7 7 7 7',
  'chevron-right': 'M9 5l7 7-7 7',
  'chevron-down': 'M5 9l7 7 7-7',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  external: 'M14 4h6v6M20 4 10 14M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6',
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  list: 'M4 6h16M4 12h16M4 18h16',
  file: 'M6 3h8l5 5v13H6zM14 3v5h5',
  upload: 'M12 16V5M7 9l5-5 5 5M5 20h14',
  sparkles: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z',
  'arrow-left': 'M19 12H5M11 6l-6 6 6 6',
}

const props = withDefaults(defineProps<{ name: IconName; size?: number }>(), { size: 20 })
const d = computed(() => paths[props.name])
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path :d="d" />
  </svg>
</template>
