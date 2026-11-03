<script setup lang="ts">
/* As sobras de cache/models: arquivos e pastas que nenhum modelo do DMaker reivindica. A lista mostra o que seria
   apagado antes de a pessoa pedir; quem confirma e apaga é quem usa o cartão. */
import type { ModelLeftover } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import { leftoverLine } from '@/lib/models'

defineProps<{
  leftovers: ModelLeftover[]
  /** "3 item(ns), 2,0 MB". */
  total: string
  loading?: boolean
  /** Por que apagar está bloqueado agora (um download em andamento); vazio libera o botão. */
  blockedReason?: string
}>()

defineEmits<{ prune: [] }>()
</script>

<template>
  <AppCard title="Sobras" subtitle="Arquivos e pastas em cache/models que nenhum modelo do DMaker usa.">
    <div class="leftovers">
      <p class="leftovers__total" data-testid="leftovers-total">{{ total }}</p>
      <ul class="leftovers__list" aria-label="Sobras encontradas">
        <li v-for="item in leftovers" :key="item.path">{{ leftoverLine(item) }}</li>
      </ul>
      <div class="leftovers__actions">
        <AppButton variant="danger" :loading="loading" :disabled="!!blockedReason" @click="$emit('prune')">
          Apagar sobras
        </AppButton>
        <span v-if="blockedReason" class="leftovers__blocked" role="status">{{ blockedReason }}</span>
      </div>
    </div>
  </AppCard>
</template>

<style scoped>
.leftovers {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.leftovers__total {
  font-weight: 600;
}

.leftovers__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  max-height: 14rem;
  padding: var(--space-3);
  overflow-y: auto;
  list-style: none;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-soft);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-soft);
  overflow-wrap: anywhere;
}

.leftovers__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.leftovers__blocked {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}
</style>
