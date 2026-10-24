<script setup lang="ts">
/* Um campo do formulário de template; o tipo do parâmetro (text, path, paths, dir...) decide o controle. */
import { computed, ref } from 'vue'
import type { TemplateParam, TemplateParamValue } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { baseName } from '@/lib/format'
import { parseList } from '@/lib/projects'
import FileBrowserDialog, { type BrowseMode } from './FileBrowserDialog.vue'

const props = defineProps<{ name: string; param: TemplateParam }>()
const value = defineModel<TemplateParamValue | undefined>({ default: undefined })

const browserOpen = ref(false)
const fieldId = computed(() => `param-${props.name}`)
const label = computed(() => (props.param.required ? `${props.name} *` : props.name))

const browseMode = computed<BrowseMode>(() =>
  props.param.type === 'paths' ? 'files' : props.param.type === 'dir' ? 'dir' : 'file',
)
const isPathLike = computed(() => ['path', 'paths', 'dir'].includes(props.param.type))
const paths = computed(() => (Array.isArray(value.value) ? value.value : []))

function onPicked(picked: string[]): void {
  value.value = props.param.type === 'paths' ? picked : (picked[0] ?? '')
}

function removePath(index: number): void {
  value.value = paths.value.filter((_, position) => position !== index)
}

const text = computed(() => (typeof value.value === 'string' ? value.value : ''))

function onText(event: Event): void {
  value.value = (event.target as HTMLInputElement).value
}

function onToggle(event: Event): void {
  value.value = (event.target as HTMLInputElement).checked
}

// o texto digitado fica à parte da lista: reescrever "a," como ["a"] apagaria a vírgula na hora
const listText = ref(Array.isArray(value.value) ? value.value.join(', ') : '')

function onList(event: Event): void {
  listText.value = (event.target as HTMLInputElement).value
  value.value = parseList(listText.value)
}

function onNumber(event: Event): void {
  const text = (event.target as HTMLInputElement).value
  value.value = text === '' ? undefined : Number(text)
}
</script>

<template>
  <div class="field">
    <template v-if="param.type === 'bool'">
      <label class="check">
        <input :id="fieldId" type="checkbox" :checked="value === true" @change="onToggle" />
        {{ label }}
      </label>
    </template>

    <template v-else>
      <label :for="fieldId">{{ label }}</label>

      <input
        v-if="param.type === 'number'"
        :id="fieldId"
        class="input"
        type="number"
        step="any"
        :value="typeof value === 'number' ? value : ''"
        @input="onNumber"
      />

      <input
        v-else-if="param.type === 'list'"
        :id="fieldId"
        class="input"
        type="text"
        placeholder="separe por vírgula"
        :value="listText"
        @input="onList"
      />

      <div v-else-if="isPathLike && param.type !== 'paths'" class="field__row">
        <input
          :id="fieldId"
          class="input"
          type="text"
          :placeholder="param.type === 'dir' ? 'Pasta com os arquivos' : 'Caminho do arquivo'"
          :value="text"
          @input="onText"
        />
        <AppButton size="sm" @click="browserOpen = true">
          {{ param.type === 'dir' ? 'Escolher pasta' : 'Escolher' }}
        </AppButton>
      </div>

      <div v-else-if="param.type === 'paths'" class="field__paths">
        <ul v-if="paths.length" class="tags">
          <li v-for="(path, index) in paths" :key="path" class="tag" :title="path">
            {{ baseName(path) }}
            <button type="button" class="tag__remove" :aria-label="`Remover ${baseName(path)}`" @click="removePath(index)">
              <AppIcon name="x" :size="12" />
            </button>
          </li>
        </ul>
        <AppButton size="sm" @click="browserOpen = true">Escolher arquivos</AppButton>
      </div>

      <input v-else :id="fieldId" class="input" type="text" :value="text" @input="onText" />
    </template>

    <p v-if="param.description" class="field-hint">{{ param.description }}</p>

    <FileBrowserDialog v-if="isPathLike" v-model:open="browserOpen" :mode="browseMode" @select="onPicked" />
  </div>
</template>

<style scoped>
.field__row {
  display: flex;
  gap: var(--space-2);
}

.field__paths {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  max-width: 100%;
  padding: 0.2rem 0.4rem 0.2rem 0.7rem;
  border-radius: var(--radius-pill);
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
  font-size: var(--text-xs);
  font-weight: 500;
}

.tag__remove {
  display: grid;
  place-items: center;
  width: 1.1rem;
  height: 1.1rem;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: inherit;
}

.tag__remove:hover {
  background: var(--color-accent-bg);
}
</style>
