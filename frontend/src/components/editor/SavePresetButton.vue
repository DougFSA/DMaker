<script setup lang="ts">
/* O botão "Salvar predefinição" do cartão de um efeito e da janela de efeito: pede um nome e guarda o efeito, com os
   valores que tem agora, no arquivo de predefinições da pessoa (o servidor tira o intervalo e o bypass, que são do item).
   Salvar com um nome que já existe troca a predefinição. Ela passa a aparecer em Predefinições, no menu + Efeito. */
import { computed, ref } from 'vue'
import type { AudioEffectSettings } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppInput from '@/components/ui/AppInput.vue'
import { useAudioEffectsStore } from '@/stores/audioEffects'

const props = defineProps<{
  /** O efeito a guardar, como a spec o escreve; lido na hora de salvar. */
  effect: AudioEffectSettings
  /** O nome sugerido ao abrir (o nome do efeito). */
  suggestion?: string
  size?: 'sm' | 'md'
}>()

const catalog = useAudioEffectsStore()
const open = ref(false)
const name = ref('')
const saving = ref(false)

const existing = computed(() =>
  catalog.presets.some((preset) => preset.origin === 'user' && preset.label.trim().toLowerCase() === name.value.trim().toLowerCase()),
)

function show(): void {
  name.value = props.suggestion ?? ''
  open.value = true
}

async function save(): Promise<void> {
  const label = name.value.trim()
  if (!label || saving.value) return
  saving.value = true
  try {
    const saved = await catalog.savePreset(label, [{ ...props.effect }])
    if (saved) open.value = false
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <span class="save-preset">
    <AppButton :size="size ?? 'sm'" variant="ghost" title="Guardar este efeito com estes valores, para pôr em outros itens" data-save-preset @click="show">
      Salvar predefinição
    </AppButton>
    <AppDialog v-model:open="open" title="Salvar predefinição" description="O efeito fica guardado com este nome e aparece em Predefinições, no menu + Efeito. O intervalo e o bypass não entram." size="sm">
      <form class="save" @submit.prevent="save">
        <AppInput v-model="name" label="Nome" placeholder="Voz de celular limpa" :maxlength="60" data-preset-name />
        <p v-if="existing" class="save__warn" role="status" data-preset-replace>Já existe uma predefinição sua com este nome: salvar a troca.</p>
      </form>
      <template #footer>
        <AppButton @click="open = false">Cancelar</AppButton>
        <AppButton variant="primary" :loading="saving" :disabled="!name.trim()" data-preset-save @click="save">Salvar</AppButton>
      </template>
    </AppDialog>
  </span>
</template>

<style scoped>
.save-preset {
  display: inline-flex;
}

.save {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.save__warn {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-warning);
}
</style>
