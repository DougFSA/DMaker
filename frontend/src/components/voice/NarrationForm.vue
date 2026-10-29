<script setup lang="ts">
/* A Narração: o roteiro, a voz, o idioma, a velocidade e a semente. "Gerar narração" é um job com andamento e
   tempo decorrido, que toca cada fala assim que fica pronta; "Parar" cancela entre duas falas e guarda o que saiu.
   "Mandar para a fila" entrega o mesmo roteiro à fila, para textos longos. */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { errorMessage, type VoiceOption } from '@/api'
import JobRunStatus from '@/components/speech/JobRunStatus.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import AppSlider from '@/components/ui/AppSlider.vue'
import AppTextarea from '@/components/ui/AppTextarea.vue'
import LivePreviewPanel from '@/components/voice/LivePreviewPanel.vue'
import SendToQueueDialog from '@/components/voice/SendToQueueDialog.vue'
import { scriptProblem, scriptStats, seedProblem, speedLabel } from '@/lib/narration'
import { useNarrationStore, type QueueChoices } from '@/stores/narration'
import { useToastsStore } from '@/stores/toasts'

defineProps<{ languages: VoiceOption[]; brands: VoiceOption[] }>()

const narration = useNarrationStore()
const toasts = useToastsStore()
const router = useRouter()
const queueOpen = ref(false)

const stats = computed(() => scriptStats(narration.text, narration.speed))
const scriptError = computed(() => scriptProblem(narration.text))
const seedError = computed(() => seedProblem(narration.seed))
const voiceHint = computed(() =>
  narration.voiceFailure
    ? `Não consegui carregar as vozes: ${narration.voiceFailure}`
    : 'A voz que você escolhe em Usar, na aba Vozes, aparece aqui.',
)
/** Depois de parar ou silenciar a prévia, o botão já não tem o que silenciar. */
const liveFinished = computed(() => narration.live.muted || narration.live.stoppedAfter !== null)
const liveStopped = computed(() => narration.live.stoppedAfter !== null)

async function sendToQueue(choices: QueueChoices): Promise<void> {
  try {
    await narration.sendToQueue(choices)
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não consegui mandar para a fila', description: errorMessage(error) })
    return
  }
  queueOpen.value = false
  toasts.push({
    tone: 'success',
    title: 'Roteiro na fila',
    description: 'Ele será narrado em segundo plano, um por vez.',
    action: { label: 'Ver a fila', run: () => void router.push('/fila') },
  })
}
</script>

<template>
  <AppCard title="Narração" subtitle="Escreva o roteiro e ouça cada fala assim que ela fica pronta.">
    <form class="form" @submit.prevent="narration.generate()">
      <div class="grid">
        <AppSelect
          label="Voz"
          placeholder="Voz automática"
          :model-value="narration.voiceId"
          :options="narration.voiceOptions"
          :hint="voiceHint"
          @update:model-value="narration.chooseVoice"
        />
        <AppSelect v-model="narration.language" label="Idioma" placeholder="Idioma da voz (padrão)" :options="languages" />
        <AppSlider v-model="narration.speed" label="Velocidade" :min="0.5" :max="2" :step="0.05" :format="speedLabel" />
        <AppNumberInput
          v-model="narration.seed"
          label="Semente (opcional)"
          :min="0"
          :step="1"
          placeholder="Repete o mesmo jeito de falar"
          :error="seedError"
        />
      </div>

      <AppSelect
        v-model="narration.brand"
        label="Dicionário de pronúncia"
        placeholder="O da marca da voz"
        :options="brands"
        hint="Além dos termos de todas as marcas, vale o dicionário da marca escolhida."
      />

      <AppTextarea
        v-model="narration.text"
        label="Roteiro"
        :rows="9"
        placeholder="Escreva o texto que a voz vai narrar."
        :hint="stats"
        :error="scriptError"
      />
      <p class="tip">
        Para uma pausa fixa, escreva <code>[pausa 1.2]</code> no ponto desejado. Linha em branco separa parágrafos com
        uma pausa maior.
      </p>
      <p class="tip">
        Para fixar a pronúncia só de uma ocorrência, escreva <code>[[termo|pronúncia]]</code>, por exemplo
        <code>[[DMaker|Di-mêiker]]</code>. A fala usa a pronúncia e as legendas mostram o termo.
      </p>

      <div class="actions">
        <AppButton type="submit" variant="primary" :loading="narration.job.running" :disabled="!narration.canGenerate">
          Gerar narração
        </AppButton>
        <AppButton
          :disabled="!narration.text.trim()"
          title="Narra em segundo plano, um roteiro por vez, sem travar a tela. Roteiro longo ou vários de uma vez: use a fila."
          @click="queueOpen = true"
        >
          Mandar para a fila
        </AppButton>
      </div>

      <JobRunStatus :job="narration.job" title="Gerar narração" cancellable @cancel="narration.stop()" />
      <p v-if="narration.job.running" class="tip">
        Na CPU a síntese é lenta: cada segundo de áudio leva dezenas de segundos. Falas repetidas saem do cache.
      </p>

      <LivePreviewPanel
        v-if="narration.live.visible"
        :status="narration.liveText"
        :finished="liveFinished"
        :stopped="liveStopped"
        @mute="narration.muteLive()"
      />
    </form>

    <SendToQueueDialog
      v-model:open="queueOpen"
      :busy="narration.queueing"
      :characters="narration.text.trim().length"
      @send="sendToQueue"
    />
  </AppCard>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr));
  gap: var(--space-4);
}

.tip {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.tip code {
  padding: 0.05rem 0.35rem;
  border-radius: var(--radius-sm);
  background: var(--color-bg-soft);
  font-size: var(--text-xs);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}
</style>
