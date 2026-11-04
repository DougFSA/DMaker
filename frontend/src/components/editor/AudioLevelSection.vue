<script setup lang="ts">
/* O bloco "Nível do item" do painel Filtros: RMS, pico e LUFS integrado do item selecionado como ele soa (com os efeitos
   que a edição tem agora). Mede só quando a pessoa pede, no botão Medir, e não a cada seleção: é uma leitura do arquivo.
   Só lê: não muda o projeto. */
import { computed, ref, watch } from 'vue'
import { api, errorMessage, type AudioItemLevel } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import { effectContextFor, targetOfList } from '@/lib/audioEffects'
import { pruneEmpty } from '@/lib/editorPaths'
import { formatDb } from '@/lib/spectrum'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()

const primary = computed(() => {
  const last = editor.selection[editor.selection.length - 1]
  return last ? editor.findItem(last) : null
})
const context = computed(() => effectContextFor(primary.value, editor.view))
/** O item medido: o master (a mistura inteira) não é um arquivo, então não tem este bloco. */
const target = computed(() => {
  if (context.value.kind !== 'chain') return null
  const key = targetOfList(context.value.chain.listPath)
  return key === 'audio.master' ? null : key
})

const level = ref<AudioItemLevel | null>(null)
const measuring = ref(false)
const problem = ref('')

// o resultado é do item que foi medido: trocar a seleção apaga a leitura velha
watch(target, () => {
  level.value = null
  problem.value = ''
})

async function measure(): Promise<void> {
  const project = editor.name
  if (!project || !editor.spec || !target.value) return
  measuring.value = true
  problem.value = ''
  editor.flushPendingEdits()
  try {
    level.value = await api.editor.audioLevel(project, pruneEmpty(editor.spec), target.value)
  } catch (error) {
    level.value = null
    problem.value = errorMessage(error)
  } finally {
    measuring.value = false
  }
}
</script>

<template>
  <section v-if="target" class="level" aria-label="Nível do item" data-audio-level>
    <header class="level__head">
      <h4 class="level__title">Nível do item</h4>
      <AppButton size="sm" :loading="measuring" title="Mede o RMS, o pico e o LUFS do item como ele soa" data-level-measure @click="measure">
        Medir
      </AppButton>
    </header>
    <dl v-if="level" class="level__values" data-level-values>
      <div>
        <dt>RMS</dt>
        <dd data-level-rms>{{ formatDb(level.rms_db) }}</dd>
      </div>
      <div>
        <dt>Pico</dt>
        <dd data-level-peak>{{ formatDb(level.peak_db) }}</dd>
      </div>
      <div>
        <dt>LUFS integrado</dt>
        <dd data-level-lufs>{{ level.lufs === null ? 'sem som' : `${level.lufs.toFixed(1)} LUFS` }}</dd>
      </div>
    </dl>
    <p v-if="problem" class="level__note level__note--error" role="alert" data-level-error>{{ problem }}</p>
  </section>
</template>

<style scoped>
.level {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.level__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.level__title {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.level__values {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.level__values dt {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.level__values dd {
  margin: 0;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.level__note--error {
  font-size: var(--text-sm);
  color: var(--color-danger);
}
</style>
