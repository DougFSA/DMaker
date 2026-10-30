<script setup lang="ts">
/* A linha de status do agente enquanto responde: a etapa que o servidor informou (carregando o modelo, lendo o
   pedido, pensando, escrevendo, chamando uma ferramenta) com o tempo decorrido. Substitui o "Pensando..." fixo. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { formatDuration } from '@/lib/format'
import type { StageInfo } from '@/lib/agent'

const props = defineProps<{
  stage: (StageInfo & { since: number }) | null
  /** A pessoa clicou em Parar e o servidor ainda não terminou o turno. */
  stopping: boolean
  /** O agente parou e espera o clique da pessoa numa confirmação. */
  waiting: boolean
}>()

const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  timer = setInterval(() => (now.value = Date.now()), 1000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

const elapsed = computed(() => (props.stage ? formatDuration(Math.max(0, now.value - props.stage.since) / 1000) : ''))

const text = computed(() => {
  if (props.waiting) return 'Esperando a sua confirmação.'
  if (props.stopping) {
    // uma ferramenta em andamento (um render, por exemplo) só para quando termina
    return props.stage?.stage === 'tool' ? 'Parando. A ferramenta em andamento precisa terminar antes.' : 'Parando...'
  }
  if (!props.stage) return 'Aguardando o modelo...'
  return `${props.stage.label}... ${elapsed.value}`
})
</script>

<template>
  <p class="working" role="status" :data-stopping="stopping">
    <span v-if="!waiting" class="working__dot" aria-hidden="true" />
    {{ text }}
  </p>
</template>

<style scoped>
.working {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.working__dot {
  flex: none;
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: var(--color-accent);
  animation: pulse 1.2s ease-in-out infinite;
}

.working[data-stopping='true'] .working__dot {
  background: var(--color-warning);
}

@keyframes pulse {
  50% {
    opacity: 0.3;
    transform: scale(0.7);
  }
}
</style>
