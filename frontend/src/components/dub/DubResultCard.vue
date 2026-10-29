<script setup lang="ts">
/* O resultado de gerar a dublagem: o resumo, os avisos de falas que não couberam e o vídeo (ou áudio) original ao lado
   do dublado para comparar de ouvido, com os downloads e o "Usar no projeto". */
import { computed } from 'vue'
import UseInProject from '@/components/speech/UseInProject.vue'
import AbCompare from '@/components/ui/AbCompare.vue'
import AppCard from '@/components/ui/AppCard.vue'
import DownloadButton from '@/components/ui/DownloadButton.vue'
import { describeResult, mediaKindOf } from '@/lib/dub'
import type { MediaEntry } from '@/lib/media'
import type { DubOutcome } from '@/stores/dubbing'

const props = defineProps<{
  outcome: DubOutcome
  /** O projeto e a entrada da spec de onde veio o arquivo dublado; sem eles, "Usar no projeto" explica o que falta. */
  project: string | null
  entry: MediaEntry | null
}>()

defineEmits<{ used: [points: number] }>()

const kind = computed(() => mediaKindOf(props.outcome.output))
const noun = computed(() => (kind.value === 'video' ? 'vídeo' : 'áudio'))
</script>

<template>
  <AppCard title="Dublagem pronta" subtitle="Ouça o original e o dublado e escolha o que fazer com o resultado.">
    <div class="result">
      <p class="summary">{{ describeResult(outcome) }}</p>
      <ul v-if="outcome.warnings.length > 0" class="warnings" aria-label="Avisos da geração">
        <li v-for="warning in outcome.warnings" :key="warning">{{ warning }}</li>
      </ul>
      <AbCompare
        :kind="kind"
        start-at="beginning"
        label="Original e dublado"
        :first="{ label: 'Original', src: outcome.original_url }"
        :second="{ label: 'Dublado', src: outcome.output_url, refreshKey: outcome.stamp }"
      />
      <div class="actions">
        <DownloadButton :label="`Baixar o ${noun} dublado`" :url="outcome.download_url" />
        <DownloadButton label="Baixar a legenda (.srt)" :url="outcome.srt_url" />
        <UseInProject
          :project="project"
          :entry="entry"
          :new-path="outcome.output"
          :what="`${noun} dublado`"
          @used="$emit('used', $event)"
        />
      </div>
    </div>
  </AppCard>
</template>

<style scoped>
.result {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.summary {
  font-size: var(--text-md);
  overflow-wrap: anywhere;
}

.warnings {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-left: var(--space-5);
  font-size: var(--text-sm);
  color: var(--color-warning);
  overflow-wrap: anywhere;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}
</style>
