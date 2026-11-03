<script setup lang="ts">
/* Mandar o roteiro para a fila de narrações: ela narra em segundo plano, um roteiro por vez, sem prender a tela, e
   aguenta textos muito maiores que uma narração direta. Aqui se escolhe o que a fila pede além do próprio roteiro. */
import { ref, watch } from 'vue'
import type { QueueAudioFormat } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppInput from '@/components/ui/AppInput.vue'
import SegmentedControl, { type SegmentOption } from '@/components/ui/SegmentedControl.vue'
import type { QueueChoices } from '@/stores/narration'

defineProps<{
  /** O envio está em andamento. */
  busy: boolean
  /** Quantos caracteres o roteiro tem, para a pessoa saber o que está mandando. */
  characters: number
}>()

const emit = defineEmits<{ send: [choices: QueueChoices] }>()
const open = defineModel<boolean>('open', { default: false })

const FORMATS: SegmentOption<QueueAudioFormat>[] = [
  { value: 'wav', label: 'WAV' },
  { value: 'mp3', label: 'MP3' },
]

const title = ref('')
const format = ref<QueueAudioFormat>('wav')
const draft = ref(false)

// cada vez que o diálogo abre, o título volta em branco: ele é de um roteiro só
watch(open, (isOpen) => {
  if (isOpen) title.value = ''
})

function send(): void {
  emit('send', { title: title.value, format: format.value, draft: draft.value })
}
</script>

<template>
  <AppDialog
    v-model:open="open"
    title="Mandar para a fila"
    description="A fila narra em segundo plano, um roteiro por vez, sem travar a tela. Serve para roteiro longo ou para vários de uma vez."
  >
    <form id="send-to-queue-form" class="form" @submit.prevent="send">
      <p class="form__size">O roteiro tem {{ characters.toLocaleString('pt-BR') }} caracteres.</p>
      <AppInput v-model="title" label="Título do item (opcional)" placeholder="Nome da pasta de saída" :disabled="busy" />
      <SegmentedControl v-model="format" :options="FORMATS" label="Formato do áudio" />
      <AppCheckbox
        v-model="draft"
        label="Rascunho"
        hint="8 passos no OmniVoice, metade do tempo, mais áspero. Bom para ouvir o ritmo antes da versão final."
        :disabled="busy"
      />
    </form>

    <template #footer>
      <AppButton @click="open = false">Cancelar</AppButton>
      <AppButton variant="primary" type="submit" form="send-to-queue-form" :loading="busy">Mandar para a fila</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.form__size {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}
</style>
