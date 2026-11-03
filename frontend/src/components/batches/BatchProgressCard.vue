<script setup lang="ts">
/* Andamento e relatório de um lote: um vídeo por linha, com o estado de cada um, o que fazer com ele e, no
   fim, o que saiu, o que falhou e por quê. */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { BatchReport, BatchRow } from '@/api'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import AppTable from '@/components/ui/AppTable.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import { batchPercent, canResume, reasonsOf, resumeLabel, rowTone, statusTone } from '@/lib/batches'
import { formatClock, formatDuration } from '@/lib/format'

const props = defineProps<{
  report: BatchReport
  /** O que o servidor está fazendo agora no vídeo em andamento (etapa do render e o seu percentual). */
  liveLabel?: string
  /** Um pedido de pausa, retomada ou refazer está a caminho. */
  busy?: boolean
  /** A pausa foi pedida e vale quando o vídeo em andamento terminar. */
  pausing?: boolean
}>()
const emit = defineEmits<{ pause: []; resume: []; redo: [row: BatchRow]; play: [row: BatchRow] }>()

const running = computed(() => props.report.status === 'running')
const percent = computed(() => batchPercent(props.report))
// o relatório pode chegar incompleto (uma resposta que não é do lote, ou o lote ainda sendo gravado): sem linhas a tabela fica vazia
const rows = computed(() => props.report.rows ?? [])
const unfinished = computed(() => rows.value.filter((row) => row.state === 'failed' || row.state === 'invalid'))
const counts = computed(() => [
  { label: 'Prontos', value: props.report.done, tone: 'success' },
  { label: 'Falharam', value: props.report.failed, tone: 'error' },
  { label: 'Pulados', value: props.report.skipped, tone: 'warning' },
  { label: 'Esperando', value: props.report.waiting, tone: 'neutral' },
])
</script>

<template>
  <AppCard :title="`Lote ${report.name}`" :subtitle="`Modelo ${report.template}${report.preview ? ', só prévias' : ''}`">
    <template #actions>
      <AppBadge :tone="statusTone(report.status)" dot>{{ report.status_label }}</AppBadge>
      <AppButton v-if="running" size="sm" :loading="busy" :disabled="pausing" @click="emit('pause')">
        {{ pausing ? 'Pausando depois deste vídeo' : 'Pausar' }}
      </AppButton>
      <AppButton v-else-if="canResume(report)" size="sm" variant="primary" :loading="busy" @click="emit('resume')">
        {{ resumeLabel(report) }}
      </AppButton>
    </template>

    <div class="overall">
      <ProgressBar :value="percent" :label="`Andamento do lote ${report.name}`" />
      <div class="overall__meta">
        <span>{{ report.summary }}</span>
        <span v-if="running && liveLabel" class="overall__live">{{ liveLabel }}</span>
      </div>
    </div>

    <AppTable caption="Vídeos do lote">
      <thead>
        <tr>
          <th scope="col" class="cell-num">#</th>
          <th scope="col">Vídeo</th>
          <th scope="col">Situação</th>
          <th scope="col">Resultado</th>
          <th scope="col"><span class="visually-hidden">Ações</span></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.index">
          <td class="cell-num">{{ row.index }}</td>
          <td class="cell-name">
            {{ row.title || `linha ${row.line}` }}
            <span class="muted cell-line">linha {{ row.line }}</span>
          </td>
          <td>
            <AppBadge :tone="rowTone(row.state)" :dot="row.state === 'running'">{{ row.state_label }}</AppBadge>
            <span v-if="row.state === 'running' && liveLabel" class="live">{{ liveLabel }}</span>
          </td>
          <td>
            <template v-if="row.state === 'done'">
              <span>{{ row.duration_s !== null ? formatClock(row.duration_s) : '' }}</span>
              <span v-if="row.render_s !== null" class="muted">
                renderizou em {{ formatDuration(row.render_s) }}
              </span>
            </template>
            <ul v-else-if="reasonsOf(row).length" class="reasons">
              <li v-for="reason in reasonsOf(row)" :key="reason" :title="reason">{{ reason }}</li>
            </ul>
            <span v-else class="muted">-</span>
          </td>
          <td>
            <div class="cell-actions">
              <AppButton v-if="row.state === 'done'" size="sm" variant="primary" @click="emit('play', row)">
                <AppIcon name="play" :size="14" />
                Assistir
              </AppButton>
              <AppButton
                v-if="row.state === 'done' || row.state === 'failed'"
                size="sm"
                :disabled="running"
                @click="emit('redo', row)"
              >
                {{ row.state === 'failed' ? 'Tentar de novo' : 'Refazer' }}
              </AppButton>
              <AppButton
                v-if="row.project"
                size="sm"
                variant="ghost"
                :to="{ name: 'project', params: { name: row.project } }"
              >
                Abrir projeto
              </AppButton>
            </div>
          </td>
        </tr>
      </tbody>
    </AppTable>

    <section class="report" aria-label="Relatório do lote">
      <h4 class="report__title">Relatório</h4>
      <dl class="report__counts">
        <div v-for="item in counts" :key="item.label" :class="['count', `count--${item.tone}`]">
          <dt>{{ item.label }}</dt>
          <dd>{{ item.value }}</dd>
        </div>
      </dl>
      <p class="report__folder">
        Saída: <code>{{ report.output_dir }}</code>
      </p>
      <ul v-if="unfinished.length" class="report__problems">
        <li v-for="row in unfinished" :key="row.index">
          <strong>{{ row.title || `linha ${row.line}` }}</strong>
          (linha {{ row.line }}):
          {{ reasonsOf(row).join('; ') }}
          <RouterLink v-if="row.project" :to="{ name: 'project', params: { name: row.project } }">
            Abrir projeto
          </RouterLink>
        </li>
      </ul>
      <p v-else-if="!running && report.waiting === 0" class="report__ok">Todos os vídeos do lote saíram.</p>
    </section>
  </AppCard>
</template>

<style scoped>
.overall {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

.overall__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.overall__live {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.cell-name {
  max-width: 14rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.cell-line {
  display: block;
  font-weight: 400;
  font-size: var(--text-xs);
}

.cell-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2);
}

.muted {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.live {
  display: block;
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--color-text-soft);
}

.reasons {
  min-width: 14rem;
  margin: 0;
  padding: 0;
  list-style: none;
  color: var(--color-error);
  font-size: var(--text-xs);
  overflow-wrap: break-word;
  word-break: break-word;
}

.report {
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.report__title {
  margin-bottom: var(--space-3);
  font-size: var(--text-md);
}

.report__counts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr));
  gap: var(--space-3);
  margin: 0 0 var(--space-3);
}

.count {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-surface-hover);
}

.count dt {
  font-size: var(--text-xs);
  color: var(--color-text-soft);
}

.count dd {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.count--success dd {
  color: var(--color-success);
}

.count--error dd {
  color: var(--color-error);
}

.count--warning dd {
  color: var(--color-warning);
}

.report__folder {
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
  overflow-wrap: anywhere;
}

.report__problems {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-3) var(--space-4);
  list-style: none;
  border-radius: var(--radius-md);
  background: var(--color-error-bg);
  color: var(--color-error);
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
}

.report__ok {
  font-size: var(--text-sm);
  color: var(--color-success);
}
</style>
