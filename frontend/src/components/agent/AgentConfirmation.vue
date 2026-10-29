<script setup lang="ts">
/* O agente parou e espera um sim: render final, apagar, sobrescrever ou a autorização do dono de uma voz. */
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { confirmationLabels, type ConfirmationItem } from '@/lib/agent'

const props = defineProps<{ confirmation: ConfirmationItem }>()
const emit = defineEmits<{ answer: [confirmationId: string, approve: boolean] }>()

const labels = confirmationLabels(props.confirmation.type)
</script>

<template>
  <div class="ask" role="group" :aria-label="`Confirmação de ${confirmation.tool}`" :data-state="confirmation.state">
    <p class="ask__question">{{ confirmation.question }}</p>
    <div v-if="confirmation.state === 'pending'" class="ask__buttons">
      <AppButton variant="primary" size="sm" @click="emit('answer', confirmation.confirmationId, true)">
        {{ labels.yes }}
      </AppButton>
      <AppButton variant="secondary" size="sm" @click="emit('answer', confirmation.confirmationId, false)">
        {{ labels.no }}
      </AppButton>
    </div>
    <AppBadge v-else :tone="confirmation.state === 'approved' ? 'success' : 'neutral'">
      {{ confirmation.state === 'approved' ? 'Você confirmou' : 'Você não confirmou' }}
    </AppBadge>
  </div>
</template>

<style scoped>
.ask {
  display: grid;
  gap: var(--space-3);
  max-width: min(46rem, 100%);
  padding: var(--space-4);
  border: 1px solid var(--color-warning);
  border-radius: var(--radius-md);
  background: var(--color-warning-bg);
}

.ask[data-state='approved'],
.ask[data-state='refused'] {
  border-color: var(--color-border);
  background: var(--color-surface);
}

.ask__question {
  font-weight: 600;
}

.ask__buttons {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
</style>
