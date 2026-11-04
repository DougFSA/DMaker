<script setup lang="ts">
/* O bloco "Espectro de frequência" do painel Filtros: abre, num diálogo, o gráfico do som do item selecionado na linha
   do tempo (ou da saída final já renderizada, sem seleção), com o pico, a nota e o cursor. A análise é do servidor
   (`audio_analyze`), lida do disco como o render a faria: com os efeitos e o ganho do item, como ele soa. Só lê: não
   muda o projeto. */
import { computed, ref, watch } from 'vue'
import { errorMessage } from '@/api'
import { analyzeSpectrum } from '@/api/audioAnalysis'
import type { SpectrumAlgorithm, SpectrumAnalysis, SpectrumAxis, SpectrumParams, SpectrumWindow } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import { effectContextFor } from '@/lib/audioEffects'
import { analysisTargetOf, formatDb, formatHz } from '@/lib/spectrum'
import { useEditorStore } from '@/stores/editor'
import SpectrumPlot from './SpectrumPlot.vue'

const editor = useEditorStore()

/** O item de que a análise fala: o último selecionado, como no bloco de efeitos logo acima. */
const primary = computed(() => {
  const last = editor.selection[editor.selection.length - 1]
  return last ? editor.findItem(last) : null
})
const context = computed(() => effectContextFor(primary.value, editor.view))
const chain = computed(() => (context.value.kind === 'chain' ? context.value.chain : null))
const target = computed(() => (chain.value ? analysisTargetOf(chain.value.listPath) : null))

const algorithms: { value: SpectrumAlgorithm; label: string }[] = [
  { value: 'spectrum', label: 'Espectro' },
  { value: 'autocorrelation', label: 'Autocorrelação' },
  { value: 'enhanced_autocorrelation', label: 'Autocorrelação aprimorada' },
  { value: 'cepstrum', label: 'Cepstro' },
]
const windows: { value: SpectrumWindow; label: string }[] = [
  { value: 'hann', label: 'Hann' },
  { value: 'hamming', label: 'Hamming' },
  { value: 'blackman', label: 'Blackman' },
  { value: 'blackman_harris', label: 'Blackman-Harris' },
  { value: 'welch', label: 'Welch' },
  { value: 'bartlett', label: 'Bartlett' },
  { value: 'rectangular', label: 'Retangular' },
  { value: 'gaussian_2_5', label: 'Gaussiana (a = 2,5)' },
  { value: 'gaussian_3_5', label: 'Gaussiana (a = 3,5)' },
  { value: 'gaussian_4_5', label: 'Gaussiana (a = 4,5)' },
]
const sizes = [128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536].map((size) => ({
  value: String(size),
  label: String(size),
}))
const axes: { value: SpectrumAxis; label: string }[] = [
  { value: 'log', label: 'Logarítmico' },
  { value: 'linear', label: 'Linear' },
]

const open = ref(false)
const algorithm = ref<SpectrumAlgorithm>('spectrum')
const windowName = ref<SpectrumWindow>('hann')
const size = ref('4096')
const axis = ref<SpectrumAxis>('log')

const analysis = ref<SpectrumAnalysis | null>(null)
const busy = ref(false)
const error = ref('')
/** Só a resposta do último pedido vale: mudar um valor com uma análise em curso não deixa a velha sobrescrever a nova. */
let latest = 0

const params = computed<SpectrumParams>(() => ({
  algorithm: algorithm.value,
  window: windowName.value,
  size: Number(size.value),
  axis: axis.value,
}))

async function run(): Promise<void> {
  if (!target.value || !editor.name) return
  const turn = ++latest
  busy.value = true
  error.value = ''
  try {
    editor.flushPendingEdits()
    const result = await analyzeSpectrum(editor.name, { target: target.value, params: params.value })
    if (turn === latest) analysis.value = result
  } catch (failure) {
    if (turn === latest) {
      analysis.value = null
      error.value = errorMessage(failure)
    }
  } finally {
    if (turn === latest) busy.value = false
  }
}

watch(open, (isOpen) => {
  if (isOpen) void run()
})
watch([algorithm, windowName, size, axis], () => {
  if (open.value) void run()
})
// outro item selecionado com o diálogo aberto: o gráfico passa a falar dele
watch(target, () => {
  if (open.value) void run()
})
</script>

<template>
  <section class="spectrum" aria-label="Espectro de frequência" data-audio-spectrum>
    <header class="spectrum__head">
      <div class="spectrum__heading">
        <h4 class="spectrum__title">Espectro de frequência</h4>
        <p v-if="chain" class="spectrum__target" data-spectrum-target>{{ chain.title }}</p>
      </div>
      <AppButton size="sm" :disabled="!chain" title="Mostra o nível de cada frequência do som deste item" data-spectrum-open @click="open = true">
        <AppIcon name="activity" :size="16" />
        Ver espectro
      </AppButton>
    </header>
    <p v-if="chain && chain.listPath === 'audio.master_effects'" class="spectrum__note">
      Sem nada selecionado, o gráfico mostra a saída final já renderizada.
    </p>

    <AppDialog
      v-model:open="open"
      title="Espectro de frequência"
      :description="chain?.title"
      size="xl"
    >
      <div class="spectrum__controls">
        <AppSelect v-model="algorithm" label="Algoritmo" :options="algorithms" />
        <AppSelect v-model="windowName" label="Janela" :options="windows" />
        <AppSelect v-model="size" label="Tamanho da FFT" :options="sizes" />
        <AppSelect v-model="axis" label="Eixo de frequência" :options="axes" />
      </div>
      <p v-if="busy" class="spectrum__status" role="status" data-spectrum-busy>Analisando o som…</p>
      <p v-else-if="error" class="spectrum__status spectrum__status--error" role="alert" data-spectrum-error>{{ error }}</p>
      <template v-if="analysis">
        <SpectrumPlot :analysis="analysis" />
        <p class="spectrum__summary" data-spectrum-summary>{{ analysis.summary }}</p>
        <p v-for="note in analysis.notes ?? []" :key="note" class="spectrum__status">{{ note }}</p>
        <ul class="spectrum__peaks" aria-label="Os maiores picos" data-spectrum-peaks>
          <li v-for="peak in analysis.peaks" :key="peak.frequency">
            <strong>{{ formatHz(peak.frequency) }}</strong>
            <span>{{ formatDb(peak.level_db) }}</span>
            <span v-if="peak.note">{{ peak.note }}</span>
          </li>
        </ul>
      </template>
    </AppDialog>
  </section>
</template>

<style scoped>
.spectrum {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.spectrum__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2) var(--space-3);
}

.spectrum__heading {
  flex: 1 1 8rem;
  min-width: 0;
}

.spectrum__title {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.spectrum__target {
  overflow: hidden;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.spectrum__note,
.spectrum__status {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.spectrum__status--error {
  color: var(--color-error);
}

.spectrum__controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.spectrum__summary {
  margin-top: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.spectrum__peaks {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-4);
  margin: var(--space-3) 0 0;
  padding: 0;
  list-style: none;
  font-size: var(--text-sm);
}

.spectrum__peaks li {
  display: flex;
  gap: var(--space-2);
  font-variant-numeric: tabular-nums;
  color: var(--color-text-soft);
}

.spectrum__peaks strong {
  color: var(--color-text);
}
</style>
