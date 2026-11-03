<script setup lang="ts">
/* O resumo do disco no alto da tela de Modelos: a pasta onde os modelos moram e quanto eles ocupam, quanto sobra
   livre e quanto é sobra. O servidor já mediu e formatou tudo; aqui só se mostra. */
import { computed } from 'vue'
import type { ModelInventory } from '@/api'
import { summaryParts } from '@/lib/models'

const props = defineProps<{ inventory: ModelInventory }>()

const parts = computed(() => summaryParts(props.inventory))
</script>

<template>
  <div class="summary">
    <p class="summary__line" data-testid="models-summary">{{ parts.join(' · ') }}</p>
    <p class="summary__folder">
      Pasta: <code data-testid="models-dir">{{ inventory.models_dir }}</code>
    </p>
  </div>
</template>

<style scoped>
.summary {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.summary__line {
  font-weight: 600;
}

.summary__folder {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
  overflow-wrap: anywhere;
}

code {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}
</style>
