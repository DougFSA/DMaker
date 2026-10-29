<script setup lang="ts">
/* Escolhe o que renderizar: prévia (opcionalmente só alguns trechos), versão final ou exportação em vários formatos. */
import { computed, ref, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import { segmentRange } from '@/lib/render'
import { useCatalogStore } from '@/stores/catalog'

export type RenderChoice =
  | { kind: 'preview'; segments: string | null }
  | { kind: 'final' }
  | { kind: 'export'; presets: string[] }

type Mode = RenderChoice['kind']

const props = defineProps<{
  projectName: string
  busy?: boolean
  /** O modo que o diálogo mostra ao abrir (o editor tem um botão para cada); sem ele, vale o último escolhido. */
  initialMode?: Mode
}>()
const emit = defineEmits<{ submit: [choice: RenderChoice] }>()
const open = defineModel<boolean>('open', { default: false })

const catalog = useCatalogStore()

const mode = ref<Mode>('preview')
const from = ref('')
const to = ref('')
const presets = ref<string[]>([])
const failure = ref('')

const modes: Array<{ value: Mode; title: string; hint: string }> = [
  { value: 'preview', title: 'Prévia', hint: 'Versão rápida e leve, boa para conferir o ritmo e os textos.' },
  { value: 'final', title: 'Versão final', hint: 'Qualidade completa do formato do projeto. Demora mais.' },
  { value: 'export', title: 'Exportar em vários formatos', hint: 'Gera a versão final para cada formato marcado.' },
]

const submitLabel = computed(() =>
  mode.value === 'preview' ? 'Gerar prévia' : mode.value === 'final' ? 'Renderizar' : 'Exportar',
)

watch(open, (isOpen) => {
  if (!isOpen) return
  failure.value = ''
  if (props.initialMode) mode.value = props.initialMode
  void catalog.load().catch(() => undefined)
})

function submit(): void {
  failure.value = ''
  if (mode.value === 'preview') {
    const range = segmentRange(from.value, to.value)
    if (range.error) {
      failure.value = range.error
      return
    }
    emit('submit', { kind: 'preview', segments: range.value })
  } else if (mode.value === 'final') {
    emit('submit', { kind: 'final' })
  } else {
    if (presets.value.length === 0) {
      failure.value = 'Escolha ao menos um formato.'
      return
    }
    emit('submit', { kind: 'export', presets: presets.value })
  }
}
</script>

<template>
  <AppDialog
    v-model:open="open"
    title="Renderizar"
    :description="`Projeto ${props.projectName}. O andamento aparece ao vivo na barra superior.`"
  >
    <form id="render-form" class="form" @submit.prevent="submit">
      <fieldset class="modes">
        <legend class="visually-hidden">O que renderizar</legend>
        <label v-for="item in modes" :key="item.value" :class="['mode', { 'is-on': mode === item.value }]">
          <input v-model="mode" type="radio" name="render-mode" :value="item.value" />
          <span>
            <strong>{{ item.title }}</strong>
            <small>{{ item.hint }}</small>
          </span>
        </label>
      </fieldset>

      <div v-if="mode === 'preview'" class="range">
        <div class="field">
          <label for="render-from">Só do trecho</label>
          <input id="render-from" v-model="from" class="input" type="number" min="0" inputmode="numeric" placeholder="início" />
        </div>
        <div class="field">
          <label for="render-to">até o trecho</label>
          <input id="render-to" v-model="to" class="input" type="number" min="0" inputmode="numeric" placeholder="fim" />
        </div>
        <p class="field-hint range__hint">
          Use os números da coluna # da validação (o primeiro trecho é o 0). Não inclui sobreposições nem legendas.
          Deixe os dois vazios para a prévia do vídeo inteiro.
        </p>
      </div>

      <fieldset v-if="mode === 'export'" class="presets">
        <legend class="field-label">Formatos</legend>
        <label v-for="item in catalog.presets" :key="item.id" class="check">
          <input v-model="presets" type="checkbox" :value="item.id" />
          {{ item.platform }} {{ item.name }} <small class="preset-id">{{ item.id }}</small>
        </label>
      </fieldset>

      <p v-if="failure" class="form__error" role="alert">{{ failure }}</p>
    </form>

    <template #footer>
      <AppButton @click="open = false">Cancelar</AppButton>
      <AppButton variant="primary" type="submit" form="render-form" :loading="busy">{{ submitLabel }}</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.modes,
.presets {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  border: 0;
}

.mode {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition:
    border-color var(--transition),
    background var(--transition);
}

.mode:hover {
  border-color: var(--color-border-strong);
}

.mode.is-on {
  border-color: var(--color-accent);
  background: var(--color-accent-bg);
}

.mode input {
  margin-top: 0.3rem;
  accent-color: var(--color-accent);
}

.mode strong {
  display: block;
  font-size: var(--text-md);
}

.mode small {
  color: var(--color-text-soft);
  font-size: var(--text-sm);
}

.range {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.range__hint {
  grid-column: 1 / -1;
}

.presets {
  max-height: 14rem;
  overflow-y: auto;
}

.preset-id {
  color: var(--color-text-muted);
}

.form__error {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  background: var(--color-error-bg);
  color: var(--color-error);
  font-size: var(--text-sm);
}
</style>
