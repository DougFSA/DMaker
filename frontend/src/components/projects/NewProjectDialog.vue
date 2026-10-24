<script setup lang="ts">
/* Criar projeto: de um template (parâmetros do próprio template) ou do zero (preset, marca e fontes). */
import { computed, ref, watch } from 'vue'
import {
  api,
  errorMessage,
  type NewProjectRequest,
  type TemplateInfo,
  type TemplateParam,
  type TemplateParamValue,
} from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import { buildTemplateParams, defaultParamValues, missingRequiredParams } from '@/lib/projects'
import { useCatalogStore } from '@/stores/catalog'
import TemplateParamField from './TemplateParamField.vue'

const emit = defineEmits<{ created: [name: string] }>()
const open = defineModel<boolean>('open', { default: false })

const catalog = useCatalogStore()

const name = ref('')
const templateName = ref('')
const preset = ref('')
const brand = ref('')
const sources = ref<TemplateParamValue | undefined>([])
const captions = ref(true)
const logo = ref(false)
const values = ref<Record<string, TemplateParamValue | undefined>>({})
const submitting = ref(false)
const failure = ref('')

const sourcesParam: TemplateParam = {
  description: 'Vídeos e imagens do projeto. Pode ficar vazio e ser preenchido depois.',
  type: 'paths',
  default: null,
  required: false,
}

const template = computed<TemplateInfo | null>(
  () => catalog.templates.find((candidate) => candidate.name === templateName.value) ?? null,
)

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

// trocar de template recomeça os campos com os padrões do novo
watch(template, (next) => {
  values.value = next ? defaultParamValues(next) : {}
})

function reset(): void {
  name.value = ''
  templateName.value = ''
  brand.value = ''
  sources.value = []
  captions.value = true
  logo.value = false
  values.value = {}
  failure.value = ''
}

async function submit(): Promise<void> {
  failure.value = ''
  const trimmed = name.value.trim()
  if (!trimmed) {
    failure.value = 'Informe um nome para o projeto.'
    return
  }
  let request: NewProjectRequest
  if (template.value) {
    const missing = missingRequiredParams(template.value, values.value)
    if (missing.length) {
      failure.value = `Preencha: ${missing.join(', ')}.`
      return
    }
    request = {
      name: trimmed,
      template: template.value.name,
      params: buildTemplateParams(template.value, values.value),
    }
  } else {
    request = {
      name: trimmed,
      preset: preset.value,
      brand: brand.value || null,
      sources: Array.isArray(sources.value) ? sources.value : [],
      captions: captions.value,
      logo: logo.value,
    }
  }

  submitting.value = true
  try {
    const created = await api.projects.create(request)
    open.value = false
    reset()
    emit('created', created.name)
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
    title="Novo projeto"
    description="Comece de um modelo pronto ou monte do zero com suas fontes."
    size="lg"
  >
    <form id="new-project-form" class="form" @submit.prevent="submit">
      <div class="field">
        <label for="np-name">Nome do projeto</label>
        <input id="np-name" v-model="name" class="input" type="text" autocomplete="off" placeholder="ex.: reel-lancamento" />
      </div>

      <div class="field">
        <label for="np-template">Modelo</label>
        <select id="np-template" v-model="templateName" class="input">
          <option value="">Do zero (escolher arquivos)</option>
          <option v-for="item in catalog.templates" :key="item.name" :value="item.name">
            {{ item.name }}
          </option>
        </select>
        <p v-if="template?.description" class="field-hint">{{ template.description }}</p>
      </div>

      <template v-if="template">
        <TemplateParamField
          v-for="(param, paramName) in template.params"
          :key="`${template.name}-${paramName}`"
          v-model="values[paramName]"
          :name="String(paramName)"
          :param="param"
        />
      </template>

      <template v-else>
        <div class="form__grid">
          <div class="field">
            <label for="np-preset">Formato</label>
            <select id="np-preset" v-model="preset" class="input">
              <option v-for="item in catalog.presets" :key="item.id" :value="item.id">
                {{ item.platform }} {{ item.name }} ({{ item.id }})
              </option>
            </select>
          </div>
          <div class="field">
            <label for="np-brand">Marca</label>
            <select id="np-brand" v-model="brand" class="input">
              <option value="">Nenhuma</option>
              <option v-for="item in catalog.brands" :key="item.key" :value="item.key">{{ item.name }}</option>
            </select>
          </div>
        </div>
        <TemplateParamField v-model="sources" name="fontes" :param="sourcesParam" />
        <label class="check"><input v-model="captions" type="checkbox" /> Gerar legendas automáticas</label>
        <label class="check"><input v-model="logo" type="checkbox" /> Incluir o logo da marca</label>
      </template>

      <p v-if="failure" class="form__error" role="alert">{{ failure }}</p>
    </form>

    <template #footer>
      <AppButton @click="open = false">Cancelar</AppButton>
      <AppButton variant="primary" type="submit" :loading="submitting" form="new-project-form">
        Criar projeto
      </AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.form__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: var(--space-4);
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
