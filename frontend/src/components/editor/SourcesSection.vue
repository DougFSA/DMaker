<script setup lang="ts">
/* Fontes sincronizadas (câmeras e gravadores do mesmo evento): adicionar, remover, renomear (leva as referências
   junto), sincronização automática ou manual e "Sincronizar agora", que mede o deslocamento pelo áudio. */
import { computed, ref } from 'vue'
import { api, errorMessage, type SyncResult } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import AppTable from '@/components/ui/AppTable.vue'
import { MASTER_FIELD, SOURCE_FIELDS, SOURCE_OFFSET_FIELD } from '@/lib/editorFields'
import { SYNC_MODE_LABEL } from '@/lib/editorLabels'
import {
  addSource,
  applySyncValues,
  planSync,
  removeSource,
  renameSource,
  setSyncMode,
  sourceNames,
  syncModeOf,
  syncRowName,
  type SyncMode,
} from '@/lib/editorSpec'
import { useEditorStore } from '@/stores/editor'
import { useToastsStore } from '@/stores/toasts'
import EditorSection from './EditorSection.vue'
import FileField from './FileField.vue'
import MediaThumb from './MediaThumb.vue'
import SpecField from './SpecField.vue'

const open = defineModel<boolean>('open', { default: true })
const editor = useEditorStore()
const toasts = useToastsStore()

const names = computed(() => (editor.spec ? sourceNames(editor.spec) : []))
const masterChoices = computed(() => names.value.map((name) => ({ value: name, label: name })))
const masterField = computed(() => ({
  ...MASTER_FIELD,
  emptyLabel: names.value.length ? `Automática (${names.value[0]})` : 'Nenhuma fonte',
}))
const modeOptions = (['auto', 'manual'] as SyncMode[]).map((mode) => ({ value: mode, label: SYNC_MODE_LABEL[mode] }))

// o nome novo só vale ao sair do campo: renomear a cada tecla trocaria as referências letra por letra
const renaming = ref<Record<string, string>>({})
const syncing = ref(false)
const syncResults = ref<SyncResult[] | null>(null)

function sourceAt(name: string): Record<string, unknown> {
  return ((editor.get('sources') as Record<string, Record<string, unknown>> | undefined)?.[name] ?? {}) as Record<
    string,
    unknown
  >
}

/** Os arquivos em sequência de uma fonte que veio em partes (a câmera que parte a gravação a cada 30 minutos). */
function partsOf(name: string): string[] {
  const parts = sourceAt(name).parts
  return Array.isArray(parts) ? (parts as string[]) : []
}

function fileOf(name: string): string {
  const src = sourceAt(name).src
  return typeof src === 'string' ? src : ''
}

function filesOf(name: string): string[] {
  const parts = partsOf(name)
  return parts.length ? parts : fileOf(name) ? [fileOf(name)] : []
}

function add(): void {
  editor.mutate((spec) => addSource(spec))
}

function remove(name: string): void {
  editor.mutate((spec) => removeSource(spec, name))
}

function commitRename(name: string): void {
  const typed = renaming.value[name]
  delete renaming.value[name]
  if (typed === undefined) return
  const result = editor.mutate((spec) => renameSource(spec, name, typed))
  if (result === 'exists') {
    toasts.push({ tone: 'error', title: `Já existe uma fonte chamada “${typed.trim()}”` })
  }
}

function changeMode(name: string, mode: string): void {
  editor.mutate((spec) => setSyncMode(spec, name, mode as SyncMode))
}

async function syncNow(): Promise<void> {
  if (!editor.spec) return
  const planned = planSync(editor.spec)
  if (!planned.ok) {
    toasts.push({ tone: 'error', title: planned.reason })
    return
  }
  syncing.value = true
  try {
    const { plan } = planned
    syncResults.value = await api.editor.sync({
      master: plan.masterFile,
      others: plan.others.map((other) => other.file),
      master_stream: plan.masterStream,
    })
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não foi possível sincronizar', description: errorMessage(error) })
  } finally {
    syncing.value = false
  }
}

function useValues(): void {
  const rows = syncResults.value
  if (!rows) return
  editor.mutate((spec) => applySyncValues(spec, rows))
  syncResults.value = null
  toasts.push({ tone: 'success', title: 'Valores de sincronização aplicados' })
}
</script>

<template>
  <EditorSection v-model:open="open" title="Fontes sincronizadas" :count="names.length">
    <template #actions>
      <AppButton size="sm" :loading="syncing" :disabled="names.length < 2" @click="syncNow">Sincronizar agora</AppButton>
      <AppButton size="sm" @click="add">Adicionar fonte</AppButton>
    </template>

    <p v-if="names.length === 0" class="empty">
      Nenhuma fonte sincronizada ainda. Use fontes quando várias câmeras ou gravadores captaram o mesmo evento.
    </p>

    <template v-else>
      <div class="master">
        <SpecField :field="masterField" base="" :choices="masterChoices" />
      </div>

      <ul class="rows">
        <li v-for="name in names" :key="name" class="row">
          <div class="row__head">
            <MediaThumb v-if="filesOf(name)[0]" :src="filesOf(name)[0] as string" kind="video" />
            <AppInput
              :model-value="renaming[name] ?? name"
              label="Nome"
              @update:model-value="renaming[name] = $event"
              @change="commitRename(name)"
            />
            <AppButton variant="ghost" size="sm" :aria-label="`Remover a fonte ${name}`" @click="remove(name)">
              Remover
            </AppButton>
          </div>
          <div class="field-grid">
            <p v-if="partsOf(name).length" class="note">
              Esta fonte é feita de {{ partsOf(name).length }} arquivos em sequência: edite as partes na aba JSON.
            </p>
            <FileField
              v-else
              :model-value="fileOf(name)"
              label="Arquivo"
              @update:model-value="editor.setField(`sources.${name}.src`, $event || undefined)"
            />
            <AppSelect
              :model-value="syncModeOf(sourceAt(name))"
              label="Sincronização"
              :options="modeOptions"
              @update:model-value="changeMode(name, $event)"
            />
            <SpecField v-if="syncModeOf(sourceAt(name)) === 'manual'" :field="SOURCE_OFFSET_FIELD" :base="`sources.${name}`" />
            <SpecField v-for="field in SOURCE_FIELDS" :key="field.key" :field="field" :base="`sources.${name}`" />
          </div>
        </li>
      </ul>

      <div v-if="syncResults" class="results">
        <AppTable caption="Deslocamento medido pelo áudio">
          <thead>
            <tr>
              <th scope="col">Arquivo</th>
              <th scope="col" class="cell-num">Deslocamento (s)</th>
              <th scope="col" class="cell-num">Confiança</th>
              <th scope="col">Confiável</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in syncResults" :key="row.path">
              <td>{{ syncRowName(row) }}</td>
              <td class="cell-num">{{ row.offset_s.toFixed(3) }}</td>
              <td class="cell-num">{{ Math.round(row.confidence * 100) }}%</td>
              <td>{{ row.reliable ? 'Sim' : 'Não' }}</td>
            </tr>
          </tbody>
        </AppTable>
        <div class="results__actions">
          <AppButton variant="primary" size="sm" @click="useValues">Usar estes valores</AppButton>
          <AppButton variant="ghost" size="sm" @click="syncResults = null">Descartar</AppButton>
        </div>
      </div>
    </template>
  </EditorSection>
</template>

<style scoped>
.empty,
.note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.master {
  max-width: 22rem;
}

.rows {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.row {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
}

.row__head {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
}

.row__head > :nth-child(2) {
  flex: 1;
  max-width: 20rem;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr));
  gap: var(--space-3) var(--space-4);
  align-items: start;
}

.results {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.results__actions {
  display: flex;
  gap: var(--space-2);
}
</style>
