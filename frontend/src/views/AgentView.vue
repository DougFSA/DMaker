<script setup lang="ts">
/* Agente: conversa em português com um modelo que roda nesta máquina, sem internet. A pessoa escolhe o modelo e o
   esforço, pede, e a resposta chega ao vivo (o mesmo SSE dos renders), com as ferramentas chamadas e o andamento.
   Render final, apagar, sobrescrever e clonar voz esperam um clique de confirmação. As conversas ficam salvas no
   servidor e a lista fica ao lado (numa gaveta, em tela estreita). */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AgentAdvanced from '@/components/agent/AgentAdvanced.vue'
import AgentAttachmentTray from '@/components/agent/AgentAttachmentTray.vue'
import AgentChatBar from '@/components/agent/AgentChatBar.vue'
import AgentComposer from '@/components/agent/AgentComposer.vue'
import AgentConversationList from '@/components/agent/AgentConversationList.vue'
import AgentStatusLine from '@/components/agent/AgentStatusLine.vue'
import AgentTranscript from '@/components/agent/AgentTranscript.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import FileUpload from '@/components/ui/FileUpload.vue'
import { useConfirm } from '@/composables/useConfirm'
import { ATTACHMENT_ACCEPT, ATTACHMENT_ACCEPT_LABEL } from '@/lib/agentAttachments'
import { formatBytes, sortModels } from '@/lib/agentModels'
import { useAgentStore } from '@/stores/agent'

const EXAMPLES_OPERATE = [
  'Faz um reel do vídeo D:/videos/aula.mp4 com legenda e a marca MedlyCare',
  'Narra este roteiro com a voz dora e põe no projeto meu-video: Bem-vindo ao DMaker.',
  'Corta as pausas e os vícios desta gravação: D:/videos/entrevista.mp4',
  'Dubla este vídeo para inglês: D:/videos/aula.mp4',
]

const EXAMPLES_FREE = [
  'Me ajuda a escrever o gancho dos três primeiros segundos de um reel sobre dicas de gravação.',
  'Explica a diferença entre cortar pelo ritmo da fala e cortar pelas pausas.',
  'Revisa este texto de legenda e deixa mais curto: Hoje eu vou mostrar três erros que todo mundo comete.',
]

const agent = useAgentStore()
const confirm = useConfirm()
const draft = ref('')
const chat = ref<HTMLElement | null>(null)
const drawerOpen = ref(false)
/** A pessoa está lendo o fim da conversa? Só então a resposta que cresce rola a tela junto. */
let pinnedToEnd = true

const examples = computed(() => (agent.mode === 'free' ? EXAMPLES_FREE : EXAMPLES_OPERATE))
const placeholder = computed(() =>
  agent.mode === 'free' ? 'Escreva a sua mensagem' : 'Ex.: Faz um reel do vídeo D:/videos/aula.mp4 com legenda',
)
const kits = computed(() => agent.status?.kits ?? [])
const models = computed(() => sortModels(agent.models?.models ?? [], agent.models?.default_model ?? ''))
const statusLabel = computed(() => agent.status?.engine_label ?? '')

onMounted(() => agent.init())

function onScroll(): void {
  const element = chat.value
  if (element) pinnedToEnd = element.scrollHeight - element.scrollTop - element.clientHeight < 80
}

async function scrollToEnd(): Promise<void> {
  await nextTick()
  const element = chat.value
  if (!element) return
  // a conversa vazia mostra os exemplos desde o título; só a que tem mensagens acompanha o fim
  if (!agent.items.length) element.scrollTop = 0
  else if (pinnedToEnd) element.scrollTop = element.scrollHeight
}

// cada trecho que chega troca a lista de itens, então a resposta que cresce também passa por aqui
watch(() => agent.items, scrollToEnd)
watch(
  () => agent.conversationId,
  () => {
    pinnedToEnd = true
    void scrollToEnd()
  },
)

/** O modelo é maior que a memória inteira: avisa antes de enviar e deixa a pessoa decidir. */
async function confirmMemory(): Promise<boolean> {
  const model = agent.selectedModel
  const total = agent.models?.memory ? ` e o computador tem ${formatBytes(agent.models.memory.total)} de memória` : ''
  return confirm({
    title: 'Enviar com um modelo que não cabe na memória?',
    description: `O modelo ${agent.modelName} tem ${formatBytes(model?.size)}${total}.`,
    warning: 'A resposta vai ficar muito lenta e o computador pode travar. Prefira um modelo menor.',
    confirmLabel: 'Enviar mesmo assim',
    cancelLabel: 'Não enviar',
    tone: 'danger',
  })
}

async function submit(): Promise<void> {
  const text = draft.value
  // uma mensagem pode seguir só com anexos: a loja escreve "Veja o anexo." quando o campo está vazio
  if ((!text.trim() && !agent.pendingCount) || agent.busy || !agent.sendable) return
  if (agent.confirmsMemory && !(await confirmMemory())) return
  if (await agent.send(text)) draft.value = ''
}

/** Os arquivos escolhidos no botão Anexar sobem na hora; a lista do botão volta a ficar vazia para a próxima escolha. */
const picked = ref<File[]>([])
function onPicked(files: File[]): void {
  picked.value = []
  void agent.attach(files)
}

/** Descarregar durante uma resposta: o servidor recusa o modelo em uso, então a tela avisa antes de tentar. */
async function unloadModel(name: string): Promise<void> {
  if (agent.busy) {
    const accepted = await confirm({
      title: 'Descarregar o modelo durante uma resposta?',
      description: `O agente está respondendo. O DMaker não descarrega o modelo ${name} enquanto uma resposta o usa: pare a resposta antes.`,
      confirmLabel: 'Tentar mesmo assim',
      cancelLabel: 'Cancelar',
      tone: 'danger',
    })
    if (!accepted) return
  }
  await agent.unload(name)
}

async function openConversation(id: string): Promise<void> {
  drawerOpen.value = false
  await agent.open(id)
}

async function removeConversation(id: string): Promise<void> {
  const target = agent.conversations.find((conversation) => conversation.id === id)
  const accepted = await confirm({
    title: 'Apagar esta conversa?',
    description: target ? `"${target.title}" sai do disco, com os arquivos anexados a ela.` : undefined,
    warning: 'Isso não se desfaz.',
    confirmLabel: 'Apagar',
    tone: 'danger',
  })
  if (accepted) await agent.remove(id)
}

function startNew(): void {
  drawerOpen.value = false
  agent.startNew()
}
</script>

<template>
  <div class="agent">
    <div class="agent__frame">
      <PageHeader
        title="Agente"
        subtitle="Peça em português e o DMaker edita, com um modelo que roda nesta máquina, sem internet."
      >
        <AppBadge v-if="agent.status" :tone="agent.ready ? 'success' : 'warning'" dot>{{ statusLabel }}</AppBadge>
        <AppButton
          class="agent__toggle"
          size="sm"
          variant="secondary"
          aria-controls="agent-conversations"
          :aria-expanded="drawerOpen"
          @click="drawerOpen = !drawerOpen"
        >
          <AppIcon name="list" :size="16" />
          Conversas
        </AppButton>
        <AppButton size="sm" variant="ghost" :disabled="!agent.detail" @click="startNew">
          <AppIcon name="plus" :size="16" />
          Nova conversa
        </AppButton>
      </PageHeader>

      <AppCard v-if="agent.problem" class="problem">
        <p role="alert">{{ agent.problem }}</p>
        <AppButton size="sm" @click="agent.init()">Verificar de novo</AppButton>
      </AppCard>

      <div class="agent__layout">
        <aside
          id="agent-conversations"
          class="agent__list"
          :class="{ 'agent__list--open': drawerOpen }"
          aria-label="Conversas salvas"
          @keydown.esc="drawerOpen = false"
        >
          <AgentConversationList
            :conversations="agent.conversations"
            :active-id="agent.conversationId"
            @select="openConversation"
            @rename="(id, title) => agent.rename(id, title)"
            @remove="removeConversation"
          />
        </aside>
        <div v-if="drawerOpen" class="agent__scrim" @click="drawerOpen = false" />

        <section class="agent__main">
          <AgentChatBar
            :mode="agent.mode"
            :mode-locked="agent.modeLocked"
            :models="models"
            :memory="agent.models?.memory ?? null"
            :model-name="agent.modelName"
            :selected="agent.selectedModel"
            :effort="agent.effort"
            :busy="agent.busy"
            @update:mode="agent.setMode($event)"
            @update:model="agent.setModel($event)"
            @update:effort="agent.setEffort($event)"
          >
            <template #advanced>
              <AgentAdvanced
                :engine="agent.engine"
                :model="agent.selectedModel"
                :options="agent.options"
                :disabled="agent.busy"
                :loaded="agent.loaded?.models ?? null"
                :unloading="agent.unloading"
                :unload-error="agent.unloadError"
                @update:options="agent.setOptions($event)"
                @unload="unloadModel"
                @open="agent.loadLoaded()"
              />
            </template>
          </AgentChatBar>

          <section ref="chat" class="chat" aria-label="Conversa com o agente" aria-live="polite" :aria-busy="agent.busy" @scroll="onScroll">
            <EmptyState
              v-if="!agent.items.length"
              title="O que você quer fazer?"
              :description="
                agent.mode === 'free'
                  ? 'Converse com o modelo sem ferramentas. Por exemplo:'
                  : 'Descreva o pedido com o caminho dos arquivos. Por exemplo:'
              "
            >
              <ul class="examples">
                <li v-for="example in examples" :key="example">
                  <button type="button" class="example" @click="draft = example">{{ example }}</button>
                </li>
              </ul>
            </EmptyState>

            <AgentTranscript
              :items="agent.items"
              :kits="kits"
              :conversation-id="agent.conversationId"
              @answer="(id, approve) => agent.answerConfirmation(id, approve)"
            />

            <AgentStatusLine v-if="agent.busy" :stage="agent.stage" :stopping="agent.stopping" :waiting="!!agent.waitingForYou" />
          </section>

          <div v-if="agent.error && !agent.problem" class="failure" role="alert">
            <p>{{ agent.error }}</p>
            <span v-if="agent.suggestedModels.length" class="failure__models">
              <AppButton v-for="name in agent.suggestedModels" :key="name" size="sm" variant="secondary" @click="agent.setModel(name)">
                Usar {{ name }}
              </AppButton>
            </span>
          </div>

          <AgentComposer
            v-model="draft"
            :placeholder="placeholder"
            :busy="agent.busy"
            :stopping="agent.stopping"
            :ready="agent.sendable"
            :has-attachments="agent.pendingCount > 0"
            @submit="submit"
            @stop="agent.stop()"
            @attach="agent.attach($event)"
          >
            <template v-if="agent.attachmentCards.length || agent.warnings.length || agent.attachNotice" #above>
              <AgentAttachmentTray
                :cards="agent.attachmentCards"
                :warnings="agent.warnings"
                :notice="agent.attachNotice"
                :conversation-id="agent.conversationId"
                @remove="agent.removeAttachment($event)"
                @use-model="agent.setModel($event)"
              />
            </template>
            <template #actions>
              <FileUpload
                v-model="picked"
                compact
                multiple
                label="Anexar arquivos"
                button-label="Anexar"
                :accept="ATTACHMENT_ACCEPT"
                :accept-label="ATTACHMENT_ACCEPT_LABEL"
                :show-list="false"
                :disabled="agent.busy"
                @select="onPicked"
              />
            </template>
          </AgentComposer>

          <details v-if="kits.length && agent.mode === 'operate'" class="kit-list">
            <summary>O que o agente sabe fazer</summary>
            <ul>
              <li v-for="kit in kits" :key="kit.name">
                <strong>{{ kit.title }}</strong>: {{ kit.description }} ({{ kit.tools }} ferramentas)
              </li>
            </ul>
          </details>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* a tela mede o próprio espaço, e não a janela: a barra lateral do app já tira uma boa parte da largura. A moldura
   ocupa a altura que sobra da janela (menos a barra do topo e o respiro do conteúdo), para a caixa de mensagem ficar
   à vista e só a conversa rolar; em janela baixa, o mínimo garante que a conversa tenha espaço e a página inteira rola. */
.agent {
  container: agent / inline-size;
}

.agent__frame {
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--topbar-height) - 5.5rem);
  min-height: 38rem;
}

.problem {
  flex: none;
  margin-bottom: var(--space-4);
}

.problem p {
  margin-bottom: var(--space-3);
  color: var(--color-warning);
}

.agent__layout {
  position: relative;
  display: grid;
  flex: 1;
  grid-template-columns: 17rem minmax(0, 1fr);
  gap: var(--space-4);
  min-height: 0;
}

.agent__list {
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-soft);
}

.agent__main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.agent__toggle {
  display: none;
}

.chat {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 10rem;
  overflow-y: auto;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-soft);
}

.examples {
  display: grid;
  gap: var(--space-2);
  max-width: 40rem;
  margin: 0;
  padding: 0;
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
  display: grid;
  flex: none;
  gap: var(--space-2);
  margin-top: var(--space-3);
  color: var(--color-error);
}

.failure__models {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.kit-list {
  flex: none;
  margin-top: var(--space-3);
  color: var(--color-text-soft);
  font-size: var(--text-sm);
}

.kit-list ul {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-2);
  padding-left: var(--space-5);
}

/* tela estreita: a lista vira uma gaveta que desliza por cima da conversa */
@container agent (max-width: 760px) {
  .agent__layout {
    grid-template-columns: minmax(0, 1fr);
  }

  /* no celular a página rola inteira, com uma conversa de altura fixa, em vez de espremer tudo na altura da janela */
  .agent__frame {
    height: auto;
    min-height: 0;
  }

  .agent__layout {
    flex: none;
  }

  .chat {
    flex: none;
    height: clamp(16rem, 50vh, 28rem);
  }

  .agent__toggle {
    display: inline-flex;
  }

  .agent__list {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 15;
    width: min(20rem, 88%);
    box-shadow: var(--shadow-lg);
    transform: translateX(-110%);
    visibility: hidden;
    transition:
      transform 200ms ease,
      visibility 200ms;
  }

  .agent__list--open {
    transform: translateX(0);
    visibility: visible;
  }

  .agent__scrim {
    position: absolute;
    inset: 0;
    z-index: 14;
    background: var(--color-overlay);
  }
}
</style>
