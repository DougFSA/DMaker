<script setup lang="ts">
/* O que a pessoa vê de um trabalho de áudio ou de dublagem: a barra com a etapa, a porcentagem e o relógio enquanto
   ele roda, o motivo se falhou e o aviso se parou a pedido. Quem o usa passa o `createJobRun` da sua store. */
import { computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import { useNow } from '@/composables/useNow'
import { formatClock } from '@/lib/format'

/** O que o componente lê de um `createJobRun`. */
export interface JobRunView {
  running: boolean
  label: string
  percent: number | null
  startedAtMs: number | null
  cancelling: boolean
  error: string
  cancelled: boolean
}

const props = withDefaults(
  defineProps<{
    job: JobRunView
    /** Nome do trabalho para o leitor de tela ("Isolar voz"). */
    title: string
    /** Mostra o botão de parar: só os trabalhos que o servidor aceita cancelar. */
    cancellable?: boolean
  }>(),
  { cancellable: false },
)

defineEmits<{ cancel: [] }>()

const now = useNow()
const elapsed = computed(() => (props.job.startedAtMs === null ? '' : formatClock((now.value - props.job.startedAtMs) / 1000)))
</script>

<template>
  <div v-if="job.running" class="run" role="status">
    <ProgressBar :value="job.percent" :label="`Andamento: ${title}`" />
    <div class="run__meta">
      <span class="run__label">{{ job.label }}</span>
      <span v-if="job.percent !== null" class="run__percent">{{ job.percent }}%</span>
      <span class="run__time">{{ elapsed }} decorridos</span>
      <AppButton v-if="cancellable" size="sm" :loading="job.cancelling" @click="$emit('cancel')">Parar</AppButton>
    </div>
  </div>
  <p v-else-if="job.error" class="run run--error" role="alert">
    <AppIcon name="alert" :size="18" />
    <span>{{ job.error }}</span>
  </p>
  <p v-else-if="job.cancelled" class="run run--note" role="status">Parado a pedido. O que já estava pronto ficou guardado.</p>
</template>

<style scoped>
.run {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.run__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.run__label {
  min-width: 0;
  overflow-wrap: anywhere;
}

.run__time {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.run--error {
  flex-direction: row;
  align-items: flex-start;
  color: var(--color-error);
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
}

.run--note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}
</style>
