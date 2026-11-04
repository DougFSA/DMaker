<script setup lang="ts">
/* A janela "Gravar": escolher o microfone, ver o nível (monitorar), gravar uma narração sobre o vídeo com a latência
   compensada, regravar um trecho (punch-in), marcar hora ou gravar só quando há som, e o atalho de 15 s para clonar uma voz.
   Tudo roda nesta aba: a gravação com hora marcada e a ativada por som precisam dela aberta. */
import { computed, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import { clockText } from '@/lib/recordingSchedule'
import { useEditorStore } from '@/stores/editor'
import { SAMPLE_RATES, useRecordingStore } from '@/stores/recording'
import { useToastsStore } from '@/stores/toasts'
import AudioMeter from './AudioMeter.vue'
import RecordCloneTab from './RecordCloneTab.vue'

const recording = useRecordingStore()
const editor = useEditorStore()
const toasts = useToastsStore()
const settings = recording.settings

// ao abrir um projeto: se a aba anterior fechou no meio de uma gravação, o que chegou ao servidor está salvo e dá para recuperar
watch(
  () => editor.name,
  async (name) => {
    if (!name) return
    await recording.loadUnfinished()
    if (recording.unfinished.length > 0) {
      toasts.push({
        tone: 'info',
        title: 'Uma gravação ficou aberta neste projeto',
        description: 'O que chegou ao servidor está salvo. Abra o painel Áudio ou a janela Gravar para recuperar.',
      })
    }
  },
  { immediate: true },
)

const open = computed({
  get: () => recording.dialogOpen,
  set: (value: boolean) => {
    if (!value) void recording.closeDialog()
  },
})

const tabs = [
  { value: 'record' as const, label: 'Gravar no projeto' },
  { value: 'clone' as const, label: 'Gravar para clonar uma voz' },
]
type ChannelChoice = '1' | '2'
const channelOptions: Array<{ value: ChannelChoice; label: string }> = [
  { value: '1', label: 'Mono' },
  { value: '2', label: 'Estéreo' },
]
const channelsValue = computed<ChannelChoice>(() => (settings.channels === 2 ? '2' : '1'))
const deviceOptions = computed(() => [
  { value: '', label: 'Padrão do sistema' },
  ...recording.devices.map((device) => ({ value: device.deviceId, label: device.label })),
])
const rateOptions = SAMPLE_RATES.map((rate) => ({ value: String(rate), label: `${(rate / 1000).toString().replace('.', ',')} kHz` }))

const monitoring = computed(() => recording.phase === 'monitoring')
const recordingNow = computed(() => recording.phase === 'recording')
const working = computed(() => recording.busy)
const hasPunch = computed(() => recording.punchCandidate !== null)
const status = computed(() => {
  switch (recording.phase) {
    case 'monitoring':
      return 'Monitorando: o nível aparece, mas nada é gravado.'
    case 'waiting':
      return `Esperando a hora marcada: começa em ${clockText(recording.countdown)}. Deixe esta aba aberta.`
    case 'recording':
      return recording.settings.soundActivated && !recording.gateOpen
        ? 'Gravação ativada por som: pausada, esperando a próxima fala.'
        : 'Gravando.'
    case 'saving':
      return 'Juntando os pedaços e pondo na linha do tempo...'
    default:
      return ''
  }
})
const punchText = computed(() => {
  const range = recording.punchCandidate
  return range ? `${range.start.toFixed(2).replace('.', ',')} a ${range.end.toFixed(2).replace('.', ',')} s em ${range.target}` : ''
})

function onDevice(value: string): void {
  settings.deviceId = value
  void recording.settingsChanged()
}
function onChannels(value: ChannelChoice): void {
  settings.channels = value === '2' ? 2 : 1
  void recording.settingsChanged()
}
function onRate(value: string): void {
  settings.sampleRate = Number(value)
  void recording.settingsChanged()
}
</script>

<template>
  <AppDialog v-model:open="open" title="Gravar" description="O som vai direto do microfone para este computador, em pedaços de um segundo. Nada sai da máquina." size="lg">
    <div class="rec" data-record-dialog>
      <p v-if="!recording.supported" class="rec__error" role="alert">
        Este navegador não captura o som cru do microfone (faltam getUserMedia e AudioWorklet). Use o Chrome, o Edge ou o Firefox
        atuais, abrindo o DMaker em localhost.
      </p>

      <SegmentedControl v-model="recording.dialogTab" label="O que gravar" :options="tabs" />

      <template v-if="recording.dialogTab === 'record'">
        <section class="rec__block" aria-label="Microfone">
          <AppSelect label="Microfone" :model-value="settings.deviceId" :options="deviceOptions" :disabled="working" data-record-device @update:model-value="onDevice" />
          <div class="rec__row">
            <SegmentedControl :model-value="channelsValue" label="Canais" :options="channelOptions" @update:model-value="onChannels" />
            <AppSelect label="Taxa de amostragem" :model-value="String(settings.sampleRate)" :options="rateOptions" :disabled="working" @update:model-value="onRate" />
          </div>
          <p class="rec__hint">
            O cancelamento de eco, a supressão de ruído e o ganho automático do navegador ficam desligados: eles estragam a voz.
          </p>
          <div class="rec__row rec__row--meter">
            <AudioMeter :levels="recording.levels" />
            <AppButton v-if="!monitoring && !working" size="sm" :disabled="!recording.supported" data-record-monitor @click="recording.monitor()">Monitorar</AppButton>
            <AppButton v-else-if="monitoring" size="sm" data-record-monitor-stop @click="recording.stopMonitor()">Parar de monitorar</AppButton>
          </div>
          <AppCheckbox
            :model-value="settings.listen"
            label="Escutar o microfone pelo fone"
            hint="Use fone de ouvido: com o alto-falante, o som volta ao microfone e faz microfonia."
            @update:model-value="recording.setListen($event)"
          />
        </section>

        <section class="rec__block" aria-label="Onde a gravação cai">
          <AppCheckbox v-model="settings.overVideo" label="Gravar sobre o vídeo" :disabled="working || settings.punchIn" hint="A prévia toca enquanto você grava, e a fala entra no lugar certo, com a latência compensada." />
          <p class="rec__hint" data-record-latency>
            Latência compensada: {{ recording.latencyText || 'calculada ao gravar' }}.
            <AppButton size="sm" :disabled="working || recording.calibrating || !recording.supported" data-record-calibrate @click="recording.calibrate()">
              {{ recording.calibrating ? 'Medindo...' : 'Calibrar a latência' }}
            </AppButton>
          </p>
          <p v-if="recording.calibrationText" class="rec__hint" role="status" data-record-calibration>{{ recording.calibrationText }}</p>
          <p class="rec__hint">Para calibrar, tire o fone: o microfone precisa ouvir o clique que sai do alto-falante.</p>

          <AppCheckbox
            v-model="settings.punchIn"
            :disabled="working || !hasPunch"
            label="Regravar o trecho selecionado (punch-in)"
            :hint="hasPunch ? punchText : 'Abra uma voz gravada no painel Áudio e selecione o trecho na onda.'"
          />
          <AppNumberInput v-if="settings.punchIn" v-model="settings.prerollSeconds" label="Pré-rolagem" unit="s" :min="0" :max="15" :step="0.5" :disabled="working" hint="Quantos segundos do que vem antes tocam antes do trecho." />
        </section>

        <section class="rec__block" aria-label="Quando gravar">
          <AppCheckbox v-model="settings.soundActivated" :disabled="working" label="Gravar só quando há som" hint="Pausa nos silêncios entre as falas e volta quando o som passa do limiar; guarda 300 ms antes da fala." />
          <div v-if="settings.soundActivated" class="rec__row">
            <AppNumberInput v-model="settings.thresholdDb" label="Limiar" unit="dB" :min="-80" :max="-6" :step="1" :disabled="working" />
            <AppNumberInput v-model="settings.waitSeconds" label="Espera" unit="s" :min="0.2" :max="30" :step="0.1" :disabled="working" hint="Silêncio mais longo que isto pausa." />
          </div>
          <AppCheckbox v-model="settings.scheduled" :disabled="working" label="Gravar numa hora marcada" />
          <div v-if="settings.scheduled" class="rec__row">
            <label class="rec__field">
              Início
              <input v-model="settings.startAt" type="datetime-local" :disabled="working" data-record-start-at />
            </label>
            <label class="rec__field">
              Fim
              <input v-model="settings.endAt" type="datetime-local" :disabled="working" data-record-end-at />
            </label>
            <AppNumberInput v-model="settings.durationMinutes" label="Ou a duração" unit="min" :min="0" :step="1" :disabled="working" />
          </div>
          <p v-if="settings.scheduled || settings.soundActivated" class="rec__warn" data-record-tab-warning>
            Esta aba precisa ficar aberta e o computador acordado até o fim: a gravação roda aqui, no navegador.
          </p>
        </section>

        <p v-if="status" class="rec__status" role="status" data-record-status>
          {{ status }}
          <template v-if="recordingNow"> {{ clockText(recording.elapsed) }}<template v-if="recording.unsent > 0"> · enviando ({{ recording.unsent }})</template></template>
        </p>
        <p v-if="recording.notice" class="rec__hint" role="status">{{ recording.notice }}</p>
        <p v-if="recording.error" class="rec__error" role="alert" data-record-error>{{ recording.error }}</p>

        <section v-if="recording.unfinished.length > 0" class="rec__block" aria-label="Gravações interrompidas">
          <strong>Gravações interrompidas</strong>
          <ul class="rec__list">
            <li v-for="item in recording.unfinished" :key="item.id">
              {{ item.id }}: {{ item.duration.toFixed(1).replace('.', ',') }} s salvos
              <AppButton size="sm" @click="recording.recover(item.id)">Recuperar</AppButton>
              <AppButton size="sm" @click="recording.discardUnfinished(item.id)">Descartar</AppButton>
            </li>
          </ul>
        </section>
      </template>

      <RecordCloneTab v-else />
    </div>

    <template v-if="recording.dialogTab === 'record'" #footer>
      <AppButton v-if="recording.phase === 'recording' || recording.phase === 'waiting'" variant="danger" data-record-cancel @click="recording.cancel()">Descartar</AppButton>
      <AppButton v-if="recording.phase === 'recording' || recording.phase === 'waiting'" variant="primary" data-record-stop @click="recording.stop()">
        {{ recording.phase === 'waiting' ? 'Cancelar a espera' : 'Parar e pôr na linha do tempo' }}
      </AppButton>
      <AppButton v-else variant="primary" :disabled="!recording.supported || working" data-record-start @click="recording.start()">
        {{ settings.scheduled ? 'Agendar a gravação' : settings.punchIn ? 'Regravar o trecho' : 'Gravar' }}
      </AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.rec {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.rec__block {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.rec__row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-3);
}

.rec__row--meter {
  align-items: center;
}

.rec__field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: var(--text-sm);
}

.rec__hint {
  font-size: var(--text-xs);
  color: var(--color-text-soft);
}

.rec__warn {
  font-size: var(--text-sm);
  color: var(--color-warning);
}

.rec__status {
  font-size: var(--text-md);
  font-variant-numeric: tabular-nums;
}

.rec__error {
  font-size: var(--text-sm);
  color: var(--color-error);
}

.rec__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: 0;
  list-style: none;
  font-size: var(--text-sm);
}
</style>
