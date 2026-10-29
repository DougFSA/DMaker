<script setup lang="ts">
/* A aba JSON: a spec inteira como texto. É a saída para tudo que não tem formulário (look, efeitos sonoros, recorte
   de pessoa, composições). "Aplicar" confere o JSON e passa a valer na edição; salvar continua sendo o botão da barra. */
import { computed, ref, useId, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { useEditorStore } from '@/stores/editor'
import { useToastsStore } from '@/stores/toasts'

const editor = useEditorStore()
const toasts = useToastsStore()
const areaId = `json-${useId()}`

const generated = computed(() => (editor.spec ? JSON.stringify(editor.spec, null, 2) : ''))
const draft = ref(generated.value)
// enquanto a pessoa tem texto digitado e ainda não aplicado, mudanças vindas dos formulários não o sobrescrevem
const edited = ref(false)
const error = ref('')

watch(generated, (text) => {
  if (!edited.value) draft.value = text
})

function onInput(event: Event): void {
  draft.value = (event.target as HTMLTextAreaElement).value
  edited.value = true
  error.value = ''
}

function apply(): void {
  let parsed: unknown
  try {
    parsed = JSON.parse(draft.value)
  } catch (failure) {
    error.value = `JSON inválido: ${failure instanceof Error ? failure.message : String(failure)}`
    return
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    error.value = 'JSON inválido: a spec precisa ser um objeto.'
    return
  }
  editor.replaceSpec(parsed as Record<string, unknown>)
  edited.value = false
  error.value = ''
  draft.value = generated.value
  toasts.push({ tone: 'success', title: 'JSON aplicado', description: 'Salve o projeto para gravar a mudança.' })
}

function discard(): void {
  edited.value = false
  error.value = ''
  draft.value = generated.value
}
</script>

<template>
  <div class="json">
    <div v-if="editor.specErrors.length" class="invalid" role="alert">
      <p class="invalid__title">
        <AppIcon name="alert" :size="18" />
        A spec deste projeto não passa na validação. Corrija o texto abaixo, aplique e salve.
      </p>
      <ul>
        <li v-for="line in editor.specErrors" :key="line">{{ line }}</li>
      </ul>
    </div>

    <label :for="areaId" class="visually-hidden">Spec do projeto em JSON</label>
    <textarea
      :id="areaId"
      class="input json__area"
      :value="draft"
      spellcheck="false"
      autocomplete="off"
      rows="24"
      :aria-invalid="error ? 'true' : undefined"
      @input="onInput"
    />
    <p v-if="error" class="json__error" role="alert">{{ error }}</p>

    <div class="json__actions">
      <AppButton variant="primary" :disabled="!edited" @click="apply">Aplicar</AppButton>
      <AppButton v-if="edited" variant="ghost" @click="discard">Descartar o texto digitado</AppButton>
      <span class="json__hint">
        Aplicar atualiza o formulário e a linha do tempo. Para gravar no projeto, use Salvar na barra de cima.
      </span>
    </div>
  </div>
</template>

<style scoped>
.json {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.json__area {
  min-height: 24rem;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.5;
  tab-size: 2;
  white-space: pre;
  overflow: auto;
  resize: vertical;
}

.json__area[aria-invalid='true'] {
  border-color: var(--color-error);
}

.json__error {
  font-size: var(--text-sm);
  color: var(--color-error);
}

.json__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.json__hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.invalid {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-error);
  border-radius: var(--radius-md);
  background: var(--color-error-bg);
  font-size: var(--text-sm);
}

.invalid__title {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  font-weight: 600;
  color: var(--color-error);
}

.invalid ul {
  margin: var(--space-2) 0 0;
  padding-left: var(--space-5);
  overflow-wrap: anywhere;
}
</style>
