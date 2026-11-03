<script setup lang="ts">
/* Fila de narrações: os roteiros longos que o servidor narra em segundo plano, um por vez. A lista se atualiza sozinha
   (o servidor manda a fila inteira a cada mudança) e cada item tem os botões do estado dele. O roteiro entra pelo
   "Mandar para a fila" da Narração ou por "Importar roteiro", que lê um arquivo. */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import ImportScriptDialog from '@/components/queue/ImportScriptDialog.vue'
import QueueItemCard from '@/components/queue/QueueItemCard.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { narrationSummary } from '@/lib/queue'
import { voiceLabel } from '@/lib/speech'
import { languageLabel } from '@/lib/voice'
import { useNarrationStore } from '@/stores/narration'
import { useQueueStore, type ImportChoices } from '@/stores/queue'
import { useVoiceStore } from '@/stores/voice'

const queue = useQueueStore()
const narration = useNarrationStore()
const voices = useVoiceStore()

const importing = ref(false)

const narratedWith = computed(() => {
  const voice = narration.voiceList.find((candidate) => candidate.id === narration.voiceId)
  const language = narration.language ? languageLabel(narration.language, voices.options?.languages ?? []) : null
  return narrationSummary(voice ? voiceLabel(voice) : null, language, narration.speed)
})

onMounted(() => {
  void queue.start()
  // o diálogo de importar diz com que voz o roteiro será narrado, então precisa da lista de vozes e dos idiomas
  void narration.loadVoices()
  void voices.loadOptions().catch(() => undefined)
})

// a lista só se atualiza enquanto a tela está aberta: a fila em si segue no servidor
onUnmounted(() => queue.stop())

async function importScript(file: File, choices: ImportChoices): Promise<void> {
  if (await queue.importScript(file, choices)) importing.value = false
}
</script>

<template>
  <PageHeader title="Fila" subtitle="As narrações longas que esperam a vez, e o que já ficou pronto.">
    <AppButton @click="importing = true">
      <AppIcon name="upload" :size="18" />
      Importar roteiro
    </AppButton>
    <AppButton :disabled="!queue.canClear" :loading="queue.clearing" @click="queue.clearFinished()">
      Limpar concluídos
    </AppButton>
  </PageHeader>

  <p v-if="queue.offline" class="notice" role="status">
    Sem conexão com o servidor. Tentando de novo; a lista abaixo pode estar desatualizada.
  </p>

  <div v-if="queue.failure && !queue.view" class="failure" role="alert">
    <p>Não consegui ler a fila: {{ queue.failure }}</p>
    <AppButton size="sm" @click="queue.reload()">Tentar de novo</AppButton>
  </div>

  <template v-else-if="queue.view && queue.summary">
    <p class="summary">{{ queue.summary.text }}</p>
    <p v-if="queue.summary.warning" class="warning" role="alert">{{ queue.summary.warning }}</p>

    <EmptyState
      v-if="queue.items.length === 0"
      icon="queue"
      title="Nada na fila"
      description="Mande um roteiro pelo botão Mandar para a fila, na Narração, ou importe um arquivo."
    >
      <AppButton to="/voz/narracao">Ir para a Narração</AppButton>
      <AppButton variant="primary" @click="importing = true">Importar roteiro</AppButton>
    </EmptyState>

    <ul v-else class="queue" aria-label="Itens da fila">
      <QueueItemCard
        v-for="item in queue.items"
        :key="item.id"
        :item="item"
        :working="!!queue.working[item.id]"
        :limits="queue.limits[item.id]"
        @act="queue.act(item.id, $event)"
      />
    </ul>
  </template>

  <p v-else class="summary" role="status">Carregando a fila...</p>

  <ImportScriptDialog v-model:open="importing" :busy="queue.importing" :narrated-with="narratedWith" @send="importScript" />
</template>

<style scoped>
.queue {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.summary {
  margin-bottom: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.notice,
.warning {
  margin-bottom: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
}

.notice {
  border: 1px solid var(--color-warning);
  background: var(--color-warning-bg);
  color: var(--color-warning);
}

.warning {
  border: 1px solid var(--color-error);
  background: var(--color-error-bg);
  color: var(--color-error);
}

.failure {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-error);
}
</style>
