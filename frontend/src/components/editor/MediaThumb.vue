<script setup lang="ts">
/* Miniatura de um arquivo da spec: o primeiro quadro do vídeo ou a própria imagem. Some se o servidor não achar o arquivo. */
import { computed, ref, watch } from 'vue'
import { useEditorStore } from '@/stores/editor'

const props = defineProps<{ src: string; kind: 'video' | 'image' }>()

const AUDIO_ONLY = /\.(wav|mp3|m4a|aac|flac|ogg|opus)$/i

const editor = useEditorStore()
const failed = ref(false)

const url = computed(() => `/api/file?path=${encodeURIComponent(editor.resolvePath(props.src))}`)
// um áudio não tem quadro para mostrar: o elemento de vídeo tocaria sem erro e a miniatura ficaria em branco
const showable = computed(() => !!props.src && !AUDIO_ONLY.test(props.src) && !failed.value)

watch(
  () => props.src,
  () => {
    failed.value = false
  },
)
</script>

<template>
  <div v-if="showable" class="thumb">
    <img v-if="kind === 'image'" :src="url" alt="" loading="lazy" @error="failed = true" />
    <!-- #t=0.1 mostra o primeiro quadro sem tocar; metadata baixa só o começo do arquivo -->
    <video v-else :src="`${url}#t=0.1`" preload="metadata" muted playsinline @error="failed = true" />
  </div>
</template>

<style scoped>
.thumb {
  width: 7.5rem;
  height: 4.25rem;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-soft);
}

.thumb img,
.thumb video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
