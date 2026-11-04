<script setup lang="ts">
/* O botão "Salvar a cadeia como macro" do bloco de efeitos: guarda a cadeia INTEIRA do item selecionado com um nome, para
   pôr em outros itens (menu + Efeito, Predefinições e macros) e para tratar uma pasta de arquivos (`dmaker audio macro run`).
   O escopo diz onde ela vale: em qualquer projeto (global) ou só nos da marca deste projeto. O intervalo e o bypass de cada
   efeito não entram (o servidor os tira): eles são do item, e a macro vai para outro. Salvar com o mesmo nome troca a macro. */
import { computed, ref } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppInput from '@/components/ui/AppInput.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import type { MacroScope } from '@/api'
import { useAudioEffectsStore } from '@/stores/audioEffects'
import { useEditorStore } from '@/stores/editor'

const props = defineProps<{
  /** O item de que a cadeia vem, como o servidor o chama (`audio.voiceover.0`, `timeline.2`...). */
  target: string
  /** O nome sugerido ao abrir (o nome do item). */
  suggestion?: string
}>()

const editor = useEditorStore()
const catalog = useAudioEffectsStore()
const open = ref(false)
const name = ref('')
const scope = ref<MacroScope>('global')
const saving = ref(false)

/** A marca do projeto: sem ela não há "da marca" para escolher. */
const brand = computed(() => (editor.get('brand') as string | undefined) ?? '')
const scopes = computed(() => [
  { value: 'global' as const, label: 'Todos os projetos' },
  ...(brand.value ? [{ value: 'brand' as const, label: `Só a marca ${brand.value}` }] : []),
])

const existing = computed(() =>
  catalog.presets.some((preset) => preset.origin === 'user' && preset.label.trim().toLowerCase() === name.value.trim().toLowerCase()),
)

function show(): void {
  editor.flushPendingEdits()
  name.value = props.suggestion ?? ''
  scope.value = 'global'
  open.value = true
}

async function save(): Promise<void> {
  const label = name.value.trim()
  const project = editor.name
  if (!label || !project || saving.value) return
  saving.value = true
  try {
    const saved = await catalog.saveChain(project, editor.spec, props.target, label, scope.value)
    if (saved) open.value = false
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <span class="save-chain">
    <AppButton size="sm" variant="ghost" title="Guardar a cadeia inteira deste item com um nome, para pôr em outros itens ou numa pasta de arquivos" data-save-chain-macro @click="show">
      Salvar a cadeia como macro
    </AppButton>
    <AppDialog
      v-model:open="open"
      title="Salvar a cadeia como macro"
      description="Todos os efeitos deste item, na ordem, ficam guardados com este nome e aparecem em Predefinições e macros, no menu + Efeito. O intervalo e o bypass de cada efeito não entram."
      size="sm"
    >
      <form class="save" @submit.prevent="save">
        <AppInput v-model="name" label="Nome" placeholder="Limpar a voz da série" :maxlength="60" data-macro-name />
        <div class="save__scope">
          <span class="save__label">Onde vale</span>
          <SegmentedControl v-model="scope" :options="scopes" label="Onde a macro vale" data-macro-scope />
          <p v-if="!brand" class="save__hint">Este projeto não tem marca; para uma macro da marca, escolha a marca na seção Saída.</p>
        </div>
        <p v-if="existing" class="save__warn" role="status" data-macro-replace>Já existe uma macro sua com este nome: salvar a troca.</p>
      </form>
      <template #footer>
        <AppButton @click="open = false">Cancelar</AppButton>
        <AppButton variant="primary" :loading="saving" :disabled="!name.trim()" data-macro-save @click="save">Salvar</AppButton>
      </template>
    </AppDialog>
  </span>
</template>

<style scoped>
.save-chain {
  display: inline-flex;
}

.save {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.save__scope {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  align-items: flex-start;
}

.save__label {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-soft);
}

.save__hint,
.save__warn {
  margin: 0;
  font-size: var(--text-sm);
}

.save__hint {
  color: var(--color-text-muted);
}

.save__warn {
  color: var(--color-warning);
}
</style>
