<script setup lang="ts">
/* O "Detectar BPM" do bloco da música: pede ao servidor o andamento do ARQUIVO da música (o analisador Achar Batidas, com
   a autocorrelação dos ataques) e põe o valor sugerido nos campos da música, editáveis. A rota só lê e sugere; quem grava é
   o Salvar do editor, e a mudança entra no desfazer como qualquer outra. Quando o ouvido marca outro tempo, a metade e o
   dobro vêm como botões. */
import { ref } from 'vue'
import { errorMessage } from '@/api'
import { detectMusicTempo } from '@/api/audioAnalysis'
import type { TempoDetection } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import { setMusicTempo } from '@/lib/editorSpec'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()

const busy = ref(false)
const error = ref('')
const result = ref<TempoDetection | null>(null)

function formatBpm(value: number): string {
  return value.toLocaleString('pt-BR', { maximumFractionDigits: 2 })
}

async function detect(): Promise<void> {
  if (!editor.name) return
  busy.value = true
  error.value = ''
  try {
    editor.flushPendingEdits()
    const detection = await detectMusicTempo(editor.name)
    result.value = detection
    editor.mutate((spec) => setMusicTempo(spec, detection.bpm, detection.beat_offset))
  } catch (failure) {
    result.value = null
    error.value = errorMessage(failure)
  } finally {
    busy.value = false
  }
}

/** Troca só o andamento por uma das outras leituras (a metade ou o dobro); o primeiro tempo continua o detectado. */
function useReading(bpm: number): void {
  editor.mutate((spec) => setMusicTempo(spec, bpm, null))
}
</script>

<template>
  <div class="tempo-tools" data-music-tempo>
    <AppButton
      size="sm"
      :disabled="busy || !editor.name"
      title="Mede o andamento do arquivo da música (do projeto salvo) e preenche os campos abaixo, que você pode ajustar"
      data-detect-bpm
      @click="detect"
    >
      {{ busy ? 'Detectando…' : 'Detectar BPM' }}
    </AppButton>
    <p v-if="error" class="tempo-tools__status tempo-tools__status--error" role="alert" data-detect-error>{{ error }}</p>
    <template v-else-if="result">
      <p class="tempo-tools__status" role="status" data-detect-result>
        {{ formatBpm(result.bpm) }} BPM, primeiro tempo em {{ formatBpm(result.beat_offset) }} s (confiança
        {{ formatBpm(result.confidence) }}).
      </p>
      <p v-for="warning in result.warnings" :key="warning" class="tempo-tools__status">{{ warning }}</p>
      <p v-if="result.alternatives.length" class="tempo-tools__status">
        Se você ouve outro tempo:
        <AppButton v-for="other in result.alternatives" :key="other" size="sm" data-detect-alternative @click="useReading(other)">
          {{ formatBpm(other) }} BPM
        </AppButton>
      </p>
    </template>
  </div>
</template>

<style scoped>
.tempo-tools {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
}

.tempo-tools__status {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.tempo-tools__status--error {
  color: var(--color-error);
}
</style>
