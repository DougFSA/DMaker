<script setup lang="ts">
/* As narrações geradas nesta sessão (as últimas 30): ouvir de novo, baixar, reusar o texto no roteiro ou inserir no
   projeto aberto. Some ao recarregar a página: o arquivo continua na pasta de saída, mas a lista não. */
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import DownloadButton from '@/components/ui/DownloadButton.vue'
import { formatDuration } from '@/lib/format'
import { excerpt } from '@/lib/narration'
import { downloadUrl } from '@/lib/speech'
import type { NarrationItem } from '@/stores/narration'

defineProps<{
  items: NarrationItem[]
  /** A narração que está no player do resultado. */
  currentId: number | null
  /** Há um projeto aberto para receber a narração. */
  canInsert: boolean
  /** Uma inserção está em andamento. */
  inserting: boolean
}>()

defineEmits<{ play: [item: NarrationItem]; reuse: [item: NarrationItem]; insert: [item: NarrationItem] }>()

const time = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
</script>

<template>
  <AppCard title="Histórico da sessão" subtitle="As narrações que você gerou desde que abriu a interface.">
    <p v-if="items.length === 0" class="history__empty">As narrações geradas nesta sessão aparecem aqui.</p>
    <ul v-else class="history" aria-label="Narrações geradas nesta sessão">
      <li v-for="item in items" :key="item.id" :class="['entry', { 'is-current': item.id === currentId }]" :data-history="item.id">
        <p class="entry__text">{{ excerpt(item.text) }}</p>
        <p class="entry__meta">{{ item.voiceName }} · {{ formatDuration(item.duration) }} · {{ time.format(item.at) }}</p>
        <div class="entry__actions">
          <AppButton size="sm" @click="$emit('play', item)">Ouvir</AppButton>
          <DownloadButton size="sm" label="Baixar" :url="downloadUrl(item.audioUrl)" />
          <AppButton size="sm" @click="$emit('reuse', item)">Reusar texto</AppButton>
          <AppButton
            size="sm"
            :disabled="!canInsert"
            :loading="inserting"
            title="Insere no projeto aberto, na posição do campo Começa em do resultado"
            @click="$emit('insert', item)"
          >
            Inserir no projeto
          </AppButton>
        </div>
      </li>
    </ul>
  </AppCard>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.history__empty {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.entry {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
}

.entry.is-current {
  border-color: var(--color-accent-soft);
}

.entry__text {
  overflow-wrap: anywhere;
}

.entry__meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.entry__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
</style>
