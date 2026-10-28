<script setup lang="ts">
/* Cortar uma gravação falada: escolhe o arquivo e a intensidade, e o servidor cria um projeto com as pausas,
   os vícios e as repetições já cortados (job com progresso; a lista do que saiu aparece no projeto). */
import { computed, ref, watch } from 'vue'
import { api, errorMessage, type CutIntensity } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import SegmentedControl, { type SegmentOption } from '@/components/ui/SegmentedControl.vue'
import { defaultCutName, INTENSITIES } from '@/lib/cuts'
import { baseName } from '@/lib/format'
import { useCatalogStore } from '@/stores/catalog'
import FileBrowserDialog from './FileBrowserDialog.vue'

const emit = defineEmits<{ started: [job: { jobId: string; name: string }] }>()
const open = defineModel<boolean>('open', { default: false })

const catalog = useCatalogStore()

const source = ref('')
const name = ref('')
const nameTouched = ref(false)
const intensity = ref<CutIntensity>('normal')
const minPause = ref(0.5)
const breath = ref(0.15)
const preset = ref('')
const brand = ref('')
const captions = ref(true)
const browsing = ref(false)
const submitting = ref(false)
const failure = ref('')

const intensityOptions: SegmentOption<CutIntensity>[] = INTENSITIES.map(({ value, label }) => ({ value, label }))
const intensityHint = computed(() => INTENSITIES.find((item) => item.value === intensity.value)?.hint ?? '')

watch(open, async (isOpen) => {
  if (!isOpen) return
  failure.value = ''
  try {
    await catalog.load()
  } catch (error) {
    failure.value = errorMessage(error)
    return
  }
  preset.value ||= catalog.presets[0]?.id ?? ''
})

function onPicked(paths: string[]): void {
  source.value = paths[0] ?? ''
  // o nome acompanha o arquivo até a pessoa escrever o dela
  if (!nameTouched.value) name.value = defaultCutName(source.value)
}

async function submit(): Promise<void> {
  failure.value = ''
  const projectName = name.value.trim()
  if (!source.value) {
    failure.value = 'Escolha a gravação que será cortada.'
    return
  }
  if (!projectName) {
    failure.value = 'Informe um nome para o projeto.'
    return
  }
  submitting.value = true
  try {
    const { job_id: jobId } = await api.autocut.start({
      source: source.value,
      name: projectName,
      intensity: intensity.value,
      min_pause: minPause.value,
      breath: breath.value,
      preset: preset.value || undefined,
      brand: brand.value || null,
      captions: captions.value,
    })
    open.value = false
    emit('started', { jobId, name: projectName })
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AppDialog
    v-model:open="open"
    title="Cortar gravação"
    description="Tira as pausas, os vícios de fala e as repetições. Você confere a lista do que saiu antes de renderizar."
    size="lg"
  >
    <form id="autocut-form" class="form" @submit.prevent="submit">
      <div class="field">
        <span class="field-label">Gravação</span>
        <div class="picker">
          <AppButton @click="browsing = true">
            <AppIcon name="folder" :size="18" />
            {{ source ? 'Trocar arquivo' : 'Escolher arquivo' }}
          </AppButton>
          <span v-if="source" class="picker__file" :title="source">{{ baseName(source) }}</span>
          <span v-else class="picker__file picker__file--empty">Vídeo ou áudio com fala</span>
        </div>
      </div>

      <div class="field">
        <label for="ac-name">Nome do projeto</label>
        <input
          id="ac-name"
          v-model="name"
          class="input"
          type="text"
          autocomplete="off"
          placeholder="ex.: entrevista-corte"
          @input="nameTouched = true"
        />
      </div>

      <div class="field">
        <span class="field-label">Intensidade</span>
        <SegmentedControl v-model="intensity" :options="intensityOptions" label="Intensidade do corte" />
        <p class="field-hint">{{ intensityHint }}</p>
      </div>

      <details class="advanced">
        <summary>Ajustes</summary>
        <div class="advanced__grid">
          <div class="field">
            <label for="ac-pause">Pausa mínima (s)</label>
            <input id="ac-pause" v-model.number="minPause" class="input" type="number" min="0.1" max="10" step="0.1" />
            <p class="field-hint">Pausas maiores que isso são cortadas.</p>
          </div>
          <div class="field">
            <label for="ac-breath">Respiro (s)</label>
            <input id="ac-breath" v-model.number="breath" class="input" type="number" min="0" max="2" step="0.05" />
            <p class="field-hint">Silêncio que sobra antes e depois de cada fala.</p>
          </div>
          <div class="field">
            <label for="ac-preset">Formato</label>
            <select id="ac-preset" v-model="preset" class="input">
              <option v-for="item in catalog.presets" :key="item.id" :value="item.id">
                {{ item.platform }} {{ item.name }} ({{ item.id }})
              </option>
            </select>
          </div>
          <div class="field">
            <label for="ac-brand">Marca</label>
            <select id="ac-brand" v-model="brand" class="input">
              <option value="">Nenhuma</option>
              <option v-for="item in catalog.brands" :key="item.key" :value="item.key">{{ item.name }}</option>
            </select>
          </div>
        </div>
        <label class="check"><input v-model="captions" type="checkbox" /> Legendas automáticas seguindo a fala cortada</label>
      </details>

      <p class="field-hint">
        A transcrição roda no computador e leva alguns minutos; o andamento aparece na barra superior.
      </p>
      <p v-if="failure" class="form__error" role="alert">{{ failure }}</p>
    </form>

    <template #footer>
      <AppButton @click="open = false">Cancelar</AppButton>
      <AppButton variant="primary" type="submit" form="autocut-form" :loading="submitting">Cortar</AppButton>
    </template>

    <FileBrowserDialog v-model:open="browsing" mode="file" title="Escolher a gravação" @select="onPicked" />
  </AppDialog>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.picker {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.picker__file {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.picker__file--empty {
  color: var(--color-text-muted);
  font-weight: 400;
}

.advanced {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.advanced summary {
  cursor: pointer;
  font-weight: 600;
}

.advanced__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: var(--space-4);
  margin: var(--space-4) 0;
}

.form__error {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  background: var(--color-error-bg);
  color: var(--color-error);
  font-size: var(--text-sm);
  white-space: pre-line;
}
</style>
