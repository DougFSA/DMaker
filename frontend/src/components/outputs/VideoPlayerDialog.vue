<script setup lang="ts">
import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppIcon from '@/components/ui/AppIcon.vue'

export interface PlayableVideo {
  /** URL servida pelo backend (/api/file?path=...). */
  url: string
  name: string
  subtitle?: string
}

defineProps<{ video: PlayableVideo | null }>()
const open = defineModel<boolean>('open', { default: false })
</script>

<template>
  <AppDialog v-model:open="open" :title="video?.name ?? 'Vídeo'" :description="video?.subtitle" size="lg">
    <div v-if="video" class="player">
      <!-- o vídeo só monta com o diálogo aberto: fechar descarta o elemento e para o áudio -->
      <video :key="video.url" class="player__video" :src="video.url" controls autoplay playsinline preload="metadata">
        Seu navegador não consegue tocar este vídeo.
      </video>
    </div>
    <template #footer>
      <AppButton v-if="video" :href="video.url" :download="video.name">
        <AppIcon name="download" :size="18" />
        Baixar
      </AppButton>
      <AppButton variant="primary" @click="open = false">Fechar</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.player {
  display: grid;
  place-items: center;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: #000;
}

.player__video {
  display: block;
  max-width: 100%;
  max-height: 62vh;
  border-radius: var(--radius-sm);
  background: #000;
}
</style>
