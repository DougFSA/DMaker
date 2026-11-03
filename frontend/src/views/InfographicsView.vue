<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, errorMessage, type InfographicInfo } from '@/api'
import InfographicCard from '@/components/infographics/InfographicCard.vue'
import InfographicForm from '@/components/infographics/InfographicForm.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SearchField from '@/components/ui/SearchField.vue'
import {
  filterInfographics,
  formProblems,
  initialValues,
  requestParams,
  specSnippet,
  type FieldValue,
} from '@/lib/infographics'
import { useCatalogStore } from '@/stores/catalog'
import { useToastsStore } from '@/stores/toasts'

const FRAME_DELAY_MS = 450 // espera a pessoa parar de digitar antes de pedir um quadro novo
const DEFAULT_AT_RATIO = 0.6 // o quadro abre com o modelo já desenhado

const toasts = useToastsStore()
const brands = useCatalogStore()

const models = ref<InfographicInfo[]>([])
const loading = ref(true)
const failure = ref('')
const query = ref('')
// 'default' = sem marca: as cores, a fonte e os cantos do visual padrão
const brand = ref('default')

const chosen = ref<InfographicInfo | null>(null)
const values = ref<Record<string, FieldValue | undefined>>({})
const at = ref(0)

const frameUrl = ref('')
const frameState = ref<'idle' | 'loading' | 'ready' | 'failed'>('idle')
const frameError = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let requestId = 0

const visible = computed(() => filterInfographics(models.value, query.value))
const problems = computed(() => (chosen.value ? formProblems(chosen.value, values.value) : {}))
const hasProblems = computed(() => Object.keys(problems.value).length > 0)
const snippet = computed(() =>
  chosen.value ? specSnippet(chosen.value, requestParams(chosen.value, values.value)) : '',
)

async function load(): Promise<void> {
  failure.value = ''
  loading.value = true
  try {
    models.value = (await api.infographics.catalog()).infographics
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

function choose(info: InfographicInfo): void {
  chosen.value = info
  values.value = initialValues(info)
  at.value = Math.round(info.duration * DEFAULT_AT_RATIO * 20) / 20
}

function releaseFrame(): void {
  if (frameUrl.value) URL.revokeObjectURL(frameUrl.value)
  frameUrl.value = ''
}

async function requestFrame(): Promise<void> {
  const info = chosen.value
  if (!info || hasProblems.value) return
  const mine = ++requestId
  frameState.value = 'loading'
  frameError.value = ''
  try {
    const blob = await api.infographics.frame(info.name, {
      params: requestParams(info, values.value),
      at: at.value,
      brand: brand.value === 'default' ? undefined : brand.value,
    })
    if (mine !== requestId) return // chegou uma resposta de um pedido que já foi trocado por outro
    releaseFrame()
    frameUrl.value = URL.createObjectURL(blob)
    frameState.value = 'ready'
  } catch (error) {
    if (mine !== requestId) return
    frameError.value = errorMessage(error)
    frameState.value = 'failed'
  }
}

function scheduleFrame(): void {
  clearTimeout(timer)
  timer = setTimeout(() => void requestFrame(), FRAME_DELAY_MS)
}

async function copySnippet(): Promise<void> {
  try {
    await navigator.clipboard.writeText(snippet.value)
    toasts.push({ tone: 'success', title: 'Trecho copiado', description: 'Cole em `overlays` na spec do projeto.' })
  } catch {
    // sem permissão de área de transferência: o texto continua na tela, para copiar na mão
    toasts.push({ tone: 'info', title: 'Copie o trecho abaixo', description: snippet.value })
  }
}

watch([chosen, values, at, brand], scheduleFrame, { deep: true })
onMounted(() => {
  void load()
  // a lista de marcas só alimenta o seletor: se faltar, o catálogo continua com o visual padrão
  void brands.load().catch(() => undefined)
})
onBeforeUnmount(() => {
  clearTimeout(timer)
  requestId += 1
  releaseFrame()
})
</script>

<template>
  <div>
    <PageHeader
      title="Infográficos"
      subtitle="Animações prontas para o vídeo explicativo: contador, barra, linha, imagem, etiqueta, grifo e emoji. Escolha um, ajuste os valores e veja o quadro."
    />

    <div class="toolbar">
      <SearchField
        id="infographic-search"
        v-model="query"
        label="Buscar infográficos"
        placeholder="Buscar por nome ou descrição"
      />
      <div v-if="brands.brands.length > 1" class="toolbar__brand">
        <label for="infographic-brand">Marca</label>
        <select id="infographic-brand" v-model="brand" class="input">
          <option value="default">Nenhuma (visual padrão)</option>
          <option v-for="item in brands.brands.filter((b) => b.key !== 'default')" :key="item.key" :value="item.key">
            {{ item.name }}
          </option>
        </select>
      </div>
    </div>
    <p class="hint">
      As cores, a fonte e os cantos vêm da marca: trocar a marca muda o visual sem mexer em nada do modelo. Para usar
      no projeto, copie o trecho de spec do modelo que você ajustou.
    </p>

    <p v-if="loading" class="status" role="status">Carregando os infográficos...</p>

    <AppCard v-else-if="failure">
      <EmptyState icon="alert" title="Não foi possível carregar os infográficos" :description="failure">
        <AppButton variant="primary" @click="load">Tentar de novo</AppButton>
      </EmptyState>
    </AppCard>

    <template v-else>
      <AppCard v-if="chosen" class="editor">
        <header class="editor__head">
          <h2 class="editor__title">{{ chosen.title }}</h2>
          <AppButton size="sm" variant="ghost" @click="chosen = null">Fechar</AppButton>
        </header>
        <p class="editor__description">{{ chosen.description }}</p>

        <div class="editor__body">
          <InfographicForm v-model="values" :info="chosen" class="editor__form" />

          <div class="editor__frame">
            <div class="frame" :data-state="frameState">
              <img v-if="frameUrl" :src="frameUrl" :alt="`Quadro do infográfico ${chosen.title} com os valores digitados`" />
              <p v-if="frameState === 'loading'" class="frame__status" role="status">Gerando o quadro...</p>
              <p v-else-if="hasProblems" class="frame__status" role="status">
                Corrija os campos marcados para ver o quadro.
              </p>
              <p v-if="frameState === 'failed'" class="frame__error" role="alert">{{ frameError }}</p>
            </div>
            <div class="field">
              <label for="infographic-at">Instante do quadro: {{ at.toFixed(2) }} s</label>
              <input id="infographic-at" v-model.number="at" type="range" min="0" :max="chosen.duration" step="0.05" />
            </div>
            <pre class="snippet" aria-label="Trecho de spec">{{ snippet }}</pre>
            <AppButton variant="primary" :disabled="hasProblems" @click="copySnippet">Copiar trecho da spec</AppButton>
          </div>
        </div>
      </AppCard>

      <AppCard v-if="visible.length === 0">
        <EmptyState icon="search" title="Nada encontrado" description="Nenhum infográfico combina com a busca.">
          <AppButton @click="query = ''">Limpar a busca</AppButton>
        </EmptyState>
      </AppCard>

      <ul v-else class="grid">
        <li v-for="info in visible" :key="`${brand}-${info.name}`">
          <InfographicCard :info="info" :brand="brand" :selected="chosen?.name === info.name" @choose="choose" />
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.toolbar__brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.hint {
  margin-bottom: var(--space-5);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.status {
  padding: var(--space-6) 0;
  color: var(--color-text-soft);
}

.editor {
  margin-bottom: var(--space-5);
}

.editor__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.editor__title {
  font-size: var(--text-lg);
  font-weight: 600;
}

.editor__description {
  margin: var(--space-2) 0 var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.editor__body {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: var(--space-5);
}

@media (max-width: 900px) {
  .editor__body {
    grid-template-columns: minmax(0, 1fr);
  }
}

.editor__frame {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.frame {
  position: relative;
  min-height: 8rem;
  overflow: hidden;
  border-radius: var(--radius-md);
  background: #0f172a;
}

.frame img {
  display: block;
  width: 100%;
  height: auto;
}

.frame[data-state='loading'] img {
  opacity: 0.5;
}

.frame__status,
.frame__error {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  padding: var(--space-3);
  text-align: center;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  pointer-events: none;
}

.frame__error {
  color: var(--color-error);
  background: rgb(15 23 42 / 80%);
}

.snippet {
  margin: 0;
  padding: var(--space-3);
  overflow: auto;
  max-height: 14rem;
  font-family: ui-monospace, monospace;
  font-size: var(--text-xs);
  background: var(--color-bg-soft);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 24rem), 1fr));
  gap: var(--space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.grid > li {
  display: flex;
}

.grid > li > * {
  flex: 1;
}
</style>
