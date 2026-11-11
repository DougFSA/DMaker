<script setup lang="ts">
/* As ferramentas da Redução de ruído, dentro do cartão do efeito: "Pegar perfil de ruído" (guarda um trecho que só tem
   chiado, dado por início e fim que podem vir do cursor, e aponta o efeito para ele) e "Comparar antes e depois"
   (toca um trecho do item com o efeito desligado e ligado, sem gravar nada). O perfil e a ligação do efeito a ele são UM
   passo do desfazer. O painel de onda com seleção é do DMK-62; até lá o trecho se dá por início e fim. */
import { computed, ref, watch } from 'vue'
import { api, errorMessage, type EffectCompareResponse, type NoiseProfileReport } from '@/api'
import AbCompare from '@/components/ui/AbCompare.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import { AUTO_PROFILE, effectPath, freeProfileName, profileNames, targetOfList } from '@/lib/audioEffects'
import { pruneEmpty } from '@/lib/editorPaths'
import { formatSeconds } from '@/lib/speech'
import { useEditorStore } from '@/stores/editor'
import { useNoiseProfilesStore } from '@/stores/noiseProfiles'

const props = defineProps<{
  /** Onde a cadeia mora na spec (`audio.voiceover.0.effects`) e a posição do efeito nela. */
  listPath: string
  index: number
  /** O perfil que o efeito usa agora (`auto` ou o nome de um perfil do projeto). */
  profile: string
}>()

const editor = useEditorStore()
const measured = useNoiseProfilesStore()

const target = computed(() => targetOfList(props.listPath))
const existing = computed(() => profileNames(editor.spec))

const profileName = ref(freeProfileName(existing.value))
const start = ref<number | null>(null)
const end = ref<number | null>(null)
const taking = ref(false)
const measuring = ref(false)
const problem = ref('')

/** O nível medido do perfil que o efeito usa, quando já foi medido nesta sessão. */
const report = computed<NoiseProfileReport | null>(() => measured.reports[props.profile] ?? null)
/** Um perfil guardado que ainda não foi medido (o projeto acabou de abrir): o botão "Ver o nível" o mede. */
const measurable = computed(() => props.profile !== AUTO_PROFILE && existing.value.includes(props.profile) && !report.value)

/** Um trecho pela metade (só o início, ou só o fim) não diz onde acaba ou começa o ruído. */
const intervalProblem = computed(() => {
  if ((start.value === null) !== (end.value === null)) return 'Dê o início e o fim, ou deixe os dois vazios para usar o trecho mais quieto do item.'
  if (start.value !== null && end.value !== null && end.value <= start.value) return 'O fim precisa ser maior que o início.'
  return null
})

const cursor = computed(() => Math.round(editor.playhead * 1000) / 1000)

async function take(): Promise<void> {
  const name = profileName.value.trim()
  const project = editor.name
  if (!project || !name || intervalProblem.value) return
  taking.value = true
  problem.value = ''
  editor.flushPendingEdits()
  const pick = {
    type: 'noise_profile_set' as const,
    name,
    target: target.value,
    ...(start.value !== null && end.value !== null ? { start: start.value, end: end.value } : {}),
  }
  // o perfil e o apontar do efeito para ele valem um passo só do desfazer
  const done = await editor.applyOps([
    pick,
    { type: 'set_field', path: effectPath(props.listPath, props.index, 'profile'), value: name },
  ])
  if (!done || !editor.spec) {
    taking.value = false
    return
  }
  try {
    measured.remember(await api.editor.noiseProfile(project, pruneEmpty(editor.spec), name))
  } catch (error) {
    problem.value = errorMessage(error)
  } finally {
    taking.value = false
  }
}

/** Mede o nível de um perfil que o projeto já guardava (sem pegar de novo). */
async function measure(): Promise<void> {
  const project = editor.name
  if (!project || !editor.spec) return
  measuring.value = true
  problem.value = ''
  try {
    measured.remember(await api.editor.noiseProfile(project, pruneEmpty(editor.spec), props.profile))
  } catch (error) {
    problem.value = errorMessage(error)
  } finally {
    measuring.value = false
  }
}

/* ---------- a barra de nível por banda ---------- */

const CHART = { width: 230, height: 44, floor: -100, ceiling: -20 }

/** Os pontos da linha do nível por banda: a frequência vai de uma banda à outra e o nível de -100 a -20 dBFS vira a altura. */
const chartPoints = computed(() => {
  const bands = report.value?.bands ?? []
  if (bands.length < 2) return ''
  return bands
    .map((band, position) => {
      const x = (position / (bands.length - 1)) * CHART.width
      const level = Math.min(Math.max(band.db, CHART.floor), CHART.ceiling)
      const y = CHART.height - ((level - CHART.floor) / (CHART.ceiling - CHART.floor)) * CHART.height
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})

/* ---------- comparar antes e depois ---------- */

const duration = ref<number | null>(6)
const comparing = ref(false)
const comparison = ref<EffectCompareResponse | null>(null)
const compareProblem = ref('')

async function compare(): Promise<void> {
  const project = editor.name
  if (!project || !editor.spec || duration.value === null) return
  comparing.value = true
  compareProblem.value = ''
  editor.flushPendingEdits()
  try {
    comparison.value = await api.editor.effectCompare(project, pruneEmpty(editor.spec), {
      target: target.value,
      index: props.index,
      at: cursor.value,
      duration: duration.value,
    })
  } catch (error) {
    comparison.value = null
    compareProblem.value = errorMessage(error)
  } finally {
    comparing.value = false
  }
}

// mudar o efeito ou o perfil torna a comparação de antes velha: some até a pessoa pedir de novo
watch(
  () => JSON.stringify(editor.spec ? pruneEmpty(editor.spec) : null),
  () => {
    comparison.value = null
  },
)
</script>

<template>
  <div class="noise" data-noise-tools>
    <section class="noise__block" aria-label="Pegar perfil de ruído">
      <h6 class="noise__title">Perfil de ruído</h6>
      <p class="noise__help">
        Dê o trecho em que só se ouve o chiado, em segundos da linha do tempo (o cursor ajuda). Sem início e fim, o perfil é o trecho mais
        quieto do item.
      </p>
      <div class="noise__fields">
        <AppInput v-model="profileName" label="Nome do perfil" :maxlength="40" data-noise-name />
        <div class="noise__time">
          <AppNumberInput v-model="start" label="Início" unit="s" :min="0" data-noise-start />
          <AppButton size="sm" variant="ghost" data-noise-start-cursor title="Usa a posição do cursor como início" @click="start = cursor">
            Cursor
          </AppButton>
        </div>
        <div class="noise__time">
          <AppNumberInput v-model="end" label="Fim" unit="s" :min="0" data-noise-end />
          <AppButton size="sm" variant="ghost" data-noise-end-cursor title="Usa a posição do cursor como fim" @click="end = cursor">
            Cursor
          </AppButton>
        </div>
      </div>
      <p v-if="intervalProblem" class="noise__problem" role="alert" data-noise-interval-problem>{{ intervalProblem }}</p>
      <AppButton
        size="sm"
        :loading="taking"
        :disabled="!profileName.trim() || !!intervalProblem"
        data-noise-take
        @click="take"
      >
        Pegar perfil de ruído
      </AppButton>
      <p v-if="problem" class="noise__problem" role="alert" data-noise-problem>{{ problem }}</p>
      <AppButton v-if="measurable" size="sm" variant="ghost" :loading="measuring" data-noise-measure @click="measure">
        Ver o nível do perfil {{ profile }}
      </AppButton>
      <div v-if="report" class="noise__report" data-noise-report>
        <p class="noise__line">
          Perfil <strong>{{ report.name }}</strong>: {{ formatSeconds(report.start) }} a {{ formatSeconds(report.end) }} s do item, nível
          {{ report.level_db.toFixed(1) }} dBFS.
        </p>
        <svg
          class="noise__chart"
          :viewBox="`0 0 ${CHART.width} ${CHART.height}`"
          role="img"
          aria-label="Nível do ruído por banda de frequência, de 100 Hz a 16 kHz"
        >
          <polyline :points="chartPoints" fill="none" stroke="currentColor" stroke-width="1.5" />
        </svg>
      </div>
    </section>

    <section class="noise__block" aria-label="Comparar antes e depois">
      <h6 class="noise__title">Comparar antes e depois</h6>
      <p class="noise__help">
        Prepara um trecho do item a partir do cursor, sem o efeito e com ele, para ouvir um depois do outro. Nada é gravado.
      </p>
      <div class="noise__time">
        <AppNumberInput v-model="duration" label="Duração" unit="s" :min="1" :max="30" data-compare-duration />
        <AppButton size="sm" :loading="comparing" :disabled="duration === null" data-compare-run @click="compare">
          Preparar comparação
        </AppButton>
      </div>
      <p v-if="compareProblem" class="noise__problem" role="alert" data-compare-problem>{{ compareProblem }}</p>
      <AbCompare
        v-if="comparison"
        kind="audio"
        label="Comparar antes e depois da Redução de ruído"
        start-at="beginning"
        :first="{ label: 'Sem o efeito', src: comparison.before_url, refreshKey: comparison.before_url }"
        :second="{ label: 'Com o efeito', src: comparison.after_url, refreshKey: comparison.after_url }"
        data-compare-result
      />
    </section>
  </div>
</template>

<style scoped>
.noise {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--color-border);
}

.noise__block {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  align-items: flex-start;
}

.noise__title {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.noise__help {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.noise__fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(8rem, 1fr));
  gap: var(--space-3);
  width: 100%;
  align-items: start;
}

.noise__time {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
}

.noise__problem {
  font-size: var(--text-sm);
  color: var(--color-danger);
}

.noise__line {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.noise__report {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  width: 100%;
  color: var(--color-accent);
}

.noise__chart {
  width: 100%;
  max-width: 18rem;
  height: auto;
  border-bottom: 1px solid var(--color-border);
}
</style>
