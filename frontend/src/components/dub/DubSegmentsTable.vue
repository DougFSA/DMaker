<script setup lang="ts">
/* A tabela de falas da dublagem: o tempo e o original só se leem; a tradução, o falante e a trava se editam. Depois de
   gerar, cada fala ganha a situação dela (cabe, avança, comprimida, esticado, não coube) e a marca "nova" quando
   foi sintetizada agora. A edição fica na tela até "Salvar traduções" (ou gerar), que quem usa a tabela comanda. */
import { computed } from 'vue'
import type { DubSegmentReport } from '@/api'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import AppTable from '@/components/ui/AppTable.vue'
import AppTextarea from '@/components/ui/AppTextarea.vue'
import { describeFit, describeSpan, isNewSpeech, statusTone, type DubRow } from '@/lib/dub'

const props = withDefaults(
  defineProps<{
    /** Os nomes dos falantes do projeto; o seletor de falante só aparece com dois ou mais. */
    speakers?: string[]
    /** Como cada fala coube, pelo id dela (vazio antes de gerar). */
    reports?: Record<string, DubSegmentReport>
    disabled?: boolean
  }>(),
  { speakers: () => [], reports: () => ({}), disabled: false },
)

const rows = defineModel<DubRow[]>({ required: true })

const withSpeakers = computed(() => props.speakers.length > 1)
const hasReports = computed(() => Object.keys(props.reports).length > 0)
const speakerOptions = computed(() => props.speakers.map((name) => ({ value: name, label: name })))

function change(index: number, patch: Partial<DubRow>): void {
  rows.value = rows.value.map((row, position) => (position === index ? { ...row, ...patch } : row))
}
</script>

<template>
  <AppTable caption="Falas da dublagem: tempo, original, tradução e trava">
    <thead>
      <tr>
        <th scope="col">Tempo</th>
        <th v-if="withSpeakers" scope="col">Falante</th>
        <th scope="col">Original</th>
        <th scope="col">Tradução</th>
        <th v-if="hasReports" scope="col">Situação</th>
        <th scope="col">Travar</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="(row, index) in rows" :key="row.id">
        <td class="time">{{ describeSpan(row.start, row.end) }}</td>
        <td v-if="withSpeakers" class="speaker">
          <AppSelect
            :model-value="row.speaker ?? ''"
            :label="`Falante da fala ${row.id}`"
            hide-label
            :placeholder="row.speaker ? undefined : 'Sem falante'"
            :options="speakerOptions"
            :disabled="disabled"
            @update:model-value="change(index, { speaker: $event || null })"
          />
        </td>
        <td class="original">{{ row.original }}</td>
        <td class="translation">
          <AppTextarea
            :model-value="row.text"
            :label="`Tradução da fala ${row.id}`"
            hide-label
            :rows="2"
            :disabled="disabled"
            @update:model-value="change(index, { text: $event })"
          />
        </td>
        <td v-if="hasReports" class="fit">
          <template v-if="reports[row.id]">
            <AppBadge :tone="statusTone(reports[row.id]!.status)" :title="reports[row.id]!.message">
              {{ describeFit(reports[row.id]!) }}
            </AppBadge>
            <AppBadge v-if="isNewSpeech(reports[row.id]!)" tone="accent" title="Sintetizada agora, não veio do cache">
              nova
            </AppBadge>
          </template>
        </td>
        <td class="lock">
          <AppCheckbox
            :model-value="row.locked"
            label="Travar"
            :disabled="disabled"
            @update:model-value="change(index, { locked: $event })"
          />
        </td>
      </tr>
    </tbody>
  </AppTable>
</template>

<style scoped>
.time {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  color: var(--color-text-soft);
}

.speaker {
  min-width: 8.5rem;
}

.original {
  min-width: 9rem;
  max-width: 18rem;
  color: var(--color-text-soft);
  overflow-wrap: anywhere;
}

.translation {
  min-width: 14rem;
}

.fit {
  min-width: 8rem;
}

.fit :deep(.badge + .badge) {
  margin-left: var(--space-1);
}

.lock {
  white-space: nowrap;
}
</style>
