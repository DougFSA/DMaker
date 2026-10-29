<script setup lang="ts">
/* Os arquivos prontos de um item da fila, num bloco que abre e fecha (um audiobook tem dezenas): o áudio se ouve
   aqui mesmo, num player só por item, e tudo se baixa; a legenda (.srt) só baixa. */
import { ref } from 'vue'
import type { QueueFile } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import DownloadButton from '@/components/ui/DownloadButton.vue'
import MediaPlayer from '@/components/ui/MediaPlayer.vue'
import { downloadUrl } from '@/lib/speech'

defineProps<{ files: QueueFile[] }>()

/** O arquivo cujo player está aberto; um por item, para não tocar dois áudios por cima um do outro. */
const listening = ref<string | null>(null)

function toggle(file: QueueFile): void {
  listening.value = listening.value === file.name ? null : file.name
}
</script>

<template>
  <details v-if="files.length" class="files">
    <summary class="files__summary">Arquivos prontos ({{ files.length }})</summary>
    <ul class="files__list" aria-label="Arquivos prontos">
      <li v-for="file in files" :key="file.name" class="file" :data-file="file.name">
        <div class="file__row">
          <span class="file__name" :title="file.name">{{ file.name }}</span>
          <div class="file__actions">
            <AppButton v-if="file.audio" size="sm" :aria-label="`${listening === file.name ? 'Fechar' : 'Ouvir'} ${file.name}`" @click="toggle(file)">
              {{ listening === file.name ? 'Fechar' : 'Ouvir' }}
            </AppButton>
            <DownloadButton size="sm" :url="downloadUrl(file.url)" :filename="file.name" />
          </div>
        </div>
        <MediaPlayer v-if="listening === file.name" kind="audio" :src="file.url" :title="file.name" autoplay />
      </li>
    </ul>
  </details>
</template>

<style scoped>
.files {
  margin-top: var(--space-1);
}

.files__summary {
  width: fit-content;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-soft);
  cursor: pointer;
}

.files__summary:hover {
  color: var(--color-text);
}

.files__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 20rem;
  margin: var(--space-3) 0 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.file {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-bg-soft);
}

.file__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2) var(--space-3);
}

.file__name {
  min-width: 0;
  overflow: hidden;
  font-size: var(--text-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file__actions {
  display: flex;
  gap: var(--space-2);
}
</style>
