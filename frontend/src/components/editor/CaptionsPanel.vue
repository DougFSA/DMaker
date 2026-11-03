<script setup lang="ts">
/* A aba Legendas: a tabela de cada frase das legendas automáticas (início, fim e texto). Corrigir o texto de uma frase
   refaz o tempo das palavras dela; o vídeo só muda no próximo preview. */
import { onMounted, ref, watch } from 'vue'
import { api, errorMessage, type CaptionCue } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppTable from '@/components/ui/AppTable.vue'
import { formatCueTime, withCueText } from '@/lib/editorCaptions'
import { useEditorStore } from '@/stores/editor'
import { useToastsStore } from '@/stores/toasts'

const editor = useEditorStore()
const toasts = useToastsStore()

const cues = ref<CaptionCue[]>([])
const loading = ref(false)
const saving = ref(false)
const failure = ref('')
const changed = ref(false)

async function load(): Promise<void> {
  const name = editor.name
  if (!name) return
  loading.value = true
  failure.value = ''
  try {
    const document = await api.editor.captions.get(name)
    if (editor.name !== name) return
    cues.value = document.cues
    changed.value = false
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

function changeText(index: number, text: string): void {
  const cue = cues.value[index]
  if (!cue || cue.text === text) return
  cues.value[index] = withCueText(cue, text)
  changed.value = true
}

async function save(): Promise<void> {
  const name = editor.name
  if (!name) return
  saving.value = true
  try {
    await api.editor.captions.put(name, cues.value)
    changed.value = false
    toasts.push({ tone: 'success', title: 'Legendas salvas', description: 'Gere o preview de novo para ver a mudança.' })
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não foi possível salvar as legendas', description: errorMessage(error) })
  } finally {
    saving.value = false
  }
}

onMounted(load)
watch(() => editor.name, load)
</script>

<template>
  <div class="captions">
    <p v-if="loading" class="status" role="status">Carregando as legendas...</p>
    <p v-else-if="failure" class="status status--error" role="alert">{{ failure }}</p>
    <template v-else>
      <p class="intro">
        As legendas que o Whisper gerou neste projeto. Corrija o texto de uma frase e salve; o tempo das palavras é
        refeito sozinho.
      </p>
      <AppTable caption="Legendas automáticas">
        <thead>
          <tr>
            <th scope="col">Início</th>
            <th scope="col">Fim</th>
            <th scope="col">Texto</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(cue, index) in cues" :key="index">
            <td class="time">{{ formatCueTime(cue.start) }}</td>
            <td class="time">{{ formatCueTime(cue.end) }}</td>
            <td>
              <input
                class="input"
                type="text"
                :value="cue.text"
                :aria-label="`Texto da legenda ${index + 1}`"
                @change="changeText(index, ($event.target as HTMLInputElement).value)"
              />
            </td>
          </tr>
        </tbody>
      </AppTable>
      <div class="actions">
        <AppButton variant="primary" :loading="saving" :disabled="!changed" @click="save">Salvar legendas</AppButton>
        <span v-if="changed" class="pending">Há mudanças que ainda não foram salvas.</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.captions {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.intro,
.status {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.status--error {
  color: var(--color-error);
}

.time {
  width: 6.5rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  color: var(--color-text-soft);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.pending {
  font-size: var(--text-sm);
  color: var(--color-warning);
}
</style>
