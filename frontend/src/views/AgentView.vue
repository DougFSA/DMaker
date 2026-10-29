<script setup lang="ts">
/* Agente: conversa em português com um modelo que roda nesta máquina, sem internet. A pessoa pede, o agente
   escolhe o kit de ferramentas, chama as mesmas ferramentas do servidor MCP e mostra o andamento ao vivo (o
   mesmo SSE dos renders). Render final, apagar, sobrescrever e clonar voz esperam um clique de confirmação. */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AgentConfirmation from '@/components/agent/AgentConfirmation.vue'
import AgentToolStep from '@/components/agent/AgentToolStep.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { kitTitle } from '@/lib/agent'
import { useAgentStore } from '@/stores/agent'

const EXAMPLES = [
  'Faz um reel do vídeo D:/videos/aula.mp4 com legenda e a marca MedlyCare',
  'Narra este roteiro com a voz dora e põe no projeto meu-video: Bem-vindo ao DMaker.',
  'Corta as pausas e os vícios desta gravação: D:/videos/entrevista.mp4',
  'Dubla este vídeo para inglês: D:/videos/aula.mp4',
]

const agent = useAgentStore()
const draft = ref('')
const chat = ref<HTMLElement | null>(null)

const statusProblem = computed(() => {
  const status = agent.status
  if (!status) return agent.error || 'Não consegui falar com o servidor do DMaker.'
  if (!status.reachable) return `O modelo local não está respondendo em ${status.url}. Abra o ${status.engine_label}.`
  if (!status.model_installed) return `O modelo '${status.model}' não está instalado. Rode "dmaker doctor --offline" para ver o que falta.`
  return ''
})

onMounted(() => agent.loadStatus())

watch(
  () => agent.items.length,
  async () => {
    await nextTick()
    if (chat.value) chat.value.scrollTop = chat.value.scrollHeight
  },
)

async function submit(): Promise<void> {
  const text = draft.value
  if (await agent.send(text)) draft.value = ''
}

const kits = computed(() => agent.status?.kits ?? [])
</script>

<template>
  <PageHeader
    title="Agente"
    subtitle="Peça em português e o DMaker edita, com um modelo que roda nesta máquina, sem internet."
  >
    <AppBadge v-if="agent.status" :tone="agent.ready ? 'success' : 'warning'" dot>
      {{ agent.status.model }} ({{ agent.status.engine_label }})
    </AppBadge>
    <AppButton size="sm" variant="ghost" :disabled="agent.busy || !agent.items.length" @click="agent.reset()">
      Nova conversa
    </AppButton>
  </PageHeader>

  <AppCard v-if="statusProblem" class="problem">
    <p role="alert">{{ statusProblem }}</p>
    <AppButton size="sm" @click="agent.loadStatus()">Verificar de novo</AppButton>
  </AppCard>

  <section ref="chat" class="chat" aria-label="Conversa com o agente" aria-live="polite">
    <EmptyState
      v-if="!agent.items.length"
      title="O que você quer fazer?"
      description="Descreva o pedido com o caminho dos arquivos. Por exemplo:"
    >
      <ul class="examples">
        <li v-for="example in EXAMPLES" :key="example">
          <button type="button" class="example" @click="draft = example">{{ example }}</button>
        </li>
      </ul>
    </EmptyState>

    <template v-for="item in agent.items" :key="item.id">
      <p v-if="item.kind === 'user'" class="bubble bubble--user">{{ item.text }}</p>
      <p v-else-if="item.kind === 'kits'" class="kits">
        Kit: {{ item.kits.map((name) => kitTitle(name, kits)).join(' e ') }}
      </p>
      <AgentToolStep v-else-if="item.kind === 'tool'" :tool="item" />
      <AgentConfirmation
        v-else-if="item.kind === 'confirmation'"
        :confirmation="item"
        @answer="(id, approve) => agent.answerConfirmation(id, approve)"
      />
      <p v-else-if="item.kind === 'answer'" class="bubble bubble--agent">{{ item.text }}</p>
      <p v-else-if="item.kind === 'error'" class="bubble bubble--error" role="alert">{{ item.text }}</p>
    </template>

    <p v-if="agent.busy && !agent.waitingForYou" class="working">Pensando... modelo em CPU leva alguns minutos.</p>
    <p v-if="agent.waitingForYou" class="working">Esperando a sua confirmação.</p>
  </section>

  <p v-if="agent.error && !statusProblem" class="failure" role="alert">{{ agent.error }}</p>

  <form class="composer" @submit.prevent="submit">
    <label class="sr-only" for="agent-message">Mensagem para o agente</label>
    <textarea
      id="agent-message"
      v-model="draft"
      rows="2"
      placeholder="Ex.: Faz um reel do vídeo D:/videos/aula.mp4 com legenda"
      :disabled="agent.busy"
      @keydown.enter.exact.prevent="submit"
    />
    <AppButton type="submit" variant="primary" :loading="agent.busy" :disabled="!draft.trim() || !agent.ready">
      Enviar
    </AppButton>
  </form>

  <details v-if="kits.length" class="kit-list">
    <summary>O que o agente sabe fazer</summary>
    <ul>
      <li v-for="kit in kits" :key="kit.name">
        <strong>{{ kit.title }}</strong>: {{ kit.description }} ({{ kit.tools }} ferramentas)
      </li>
    </ul>
  </details>
</template>

<style scoped>
.problem {
  margin-bottom: var(--space-4);
}

.problem p {
  margin-bottom: var(--space-3);
  color: var(--color-warning);
}

.chat {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 16rem;
  max-height: calc(100vh - 22rem);
  overflow-y: auto;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-soft);
}

.bubble {
  max-width: min(46rem, 100%);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.bubble--user {
  align-self: flex-end;
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
}

.bubble--agent {
  align-self: flex-start;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}

.bubble--error {
  align-self: flex-start;
  background: var(--color-error-bg);
  color: var(--color-error);
}

.kits,
.working {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.examples {
  display: grid;
  gap: var(--space-2);
  max-width: 40rem;
  list-style: none;
}

.example {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text);
  text-align: left;
  cursor: pointer;
}

.example:hover {
  background: var(--color-surface-hover);
}

.failure {
  margin-top: var(--space-3);
  color: var(--color-error);
}

.composer {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.composer textarea {
  flex: 1;
  min-width: 0;
  padding: var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
  resize: vertical;
}

.composer textarea:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 1px;
}

.kit-list {
  margin-top: var(--space-5);
  color: var(--color-text-soft);
  font-size: var(--text-sm);
}

.kit-list ul {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-2);
  padding-left: var(--space-5);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
