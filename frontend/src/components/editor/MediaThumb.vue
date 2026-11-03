<script setup lang="ts">
/* Miniatura de um arquivo da spec: o primeiro quadro do vídeo ou a própria imagem. O servidor só serve caminho
   absoluto, e um `src` relativo à pasta do projeto só vira absoluto quando a vista do projeto chega: antes disso a
   miniatura espera em vez de pedir `/api/file?path=cam2.mp4` (que dá 404 e a esconderia para sempre). Arquivo que
   a vista marcou como ausente mostra um aviso no lugar. Some se o servidor não achar o arquivo. */
import { computed, ref, watch } from 'vue'
import { isAbsolutePath } from '@/lib/editorPaths'
import { fileUrl } from '@/lib/player'
import { useEditorStore } from '@/stores/editor'

/** `compact`: a miniatura pequena das listas (a do painel Mídia); sem ela, a dos cartões da aba Propriedades. */
const props = defineProps<{ src: string; kind: 'video' | 'image'; compact?: boolean }>()

const AUDIO_ONLY = /\.(wav|mp3|m4a|aac|flac|ogg|opus)$/i

const editor = useEditorStore()
const failed = ref(false)

const resolved = computed(() => editor.resolvePath(props.src))
const url = computed(() => fileUrl(resolved.value))
const missing = computed(() => editor.isMissing(props.src))
// um áudio não tem quadro para mostrar: o elemento de vídeo tocaria sem erro e a miniatura ficaria em branco
const showable = computed(
  () => !!props.src && !AUDIO_ONLY.test(props.src) && !failed.value && !missing.value && isAbsolutePath(resolved.value),
)

// outro arquivo (ou o mesmo, agora com o caminho resolvido) merece uma tentativa nova
watch(url, () => {
  failed.value = false
})
</script>

<template>
  <div v-if="showable" :class="['thumb', { 'thumb--compact': compact }]">
    <img v-if="kind === 'image'" :src="url" alt="" loading="lazy" @error="failed = true" />
    <!-- #t=0.1 mostra o primeiro quadro sem tocar; metadata baixa só o começo do arquivo -->
    <video v-else :src="`${url}#t=0.1`" preload="metadata" muted playsinline @error="failed = true" />
  </div>
  <div
    v-else-if="missing && !!src"
    :class="['thumb', 'thumb--missing', { 'thumb--compact': compact }]"
    role="img"
    aria-label="Arquivo não encontrado"
  >
    {{ compact ? 'Ausente' : 'Arquivo não encontrado' }}
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

.thumb--compact {
  width: 4.5rem;
  height: 2.75rem;
}

.thumb img,
.thumb video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.thumb--missing {
  display: grid;
  place-items: center;
  padding: var(--space-1);
  border-color: var(--color-error);
  background: var(--color-error-bg);
  color: var(--color-error);
  font-size: var(--text-xs);
  text-align: center;
}
</style>
