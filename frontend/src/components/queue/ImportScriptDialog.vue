<script setup lang="ts">
/* Importar um roteiro de arquivo (.txt, .md ou .docx) para a fila: o servidor divide em capítulos pelos títulos e a
   fila narra em segundo plano. Aqui se escolhe o arquivo, o título, o formato e se é rascunho; a voz, o idioma e a
   velocidade são os que a Narração tem escolhidos, e o diálogo diz quais são. */
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import type { QueueAudioFormat } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppInput from '@/components/ui/AppInput.vue'
import FileUpload from '@/components/ui/FileUpload.vue'
import SegmentedControl, { type SegmentOption } from '@/components/ui/SegmentedControl.vue'
import { MAX_SCRIPT_BYTES, SCRIPT_ACCEPT } from '@/lib/queue'
import type { ImportChoices } from '@/stores/queue'

defineProps<{
  /** O envio está em andamento. */
  busy: boolean
  /** Voz, idioma e velocidade que valem para o roteiro, já em frase. */
  narratedWith: string
}>()

const emit = defineEmits<{ send: [file: File, choices: ImportChoices] }>()
const open = defineModel<boolean>('open', { default: false })

const FORMATS: SegmentOption<QueueAudioFormat>[] = [
  { value: 'wav', label: 'WAV' },
  { value: 'mp3', label: 'MP3' },
]

const files = ref<File[]>([])
const title = ref('')
const format = ref<QueueAudioFormat>('wav')
const draft = ref(false)

const file = computed(() => files.value[0] ?? null)

// o arquivo e o título são de um roteiro só: cada vez que o diálogo abre, voltam em branco
watch(open, (isOpen) => {
  if (isOpen) {
    files.value = []
    title.value = ''
  }
})

function send(): void {
  if (file.value) emit('send', file.value, { title: title.value, format: format.value, draft: draft.value })
}
</script>

<template>
  <AppDialog
    v-model:open="open"
    title="Importar roteiro"
    description="O arquivo é dividido em capítulos pelos títulos e narrado em segundo plano, um item por vez."
  >
    <form id="import-script-form" class="form" @submit.prevent="send">
      <FileUpload
        v-model="files"
        label="Roteiro"
        :accept="SCRIPT_ACCEPT"
        :max-bytes="MAX_SCRIPT_BYTES"
        :busy="busy"
        hint="Arquivos .txt, .md ou .docx, de até 20 MB."
      />
      <AppInput v-model="title" label="Título do item (opcional)" placeholder="Nome da pasta de saída" :disabled="busy" />
      <SegmentedControl v-model="format" :options="FORMATS" label="Formato do áudio" />
      <AppCheckbox
        v-model="draft"
        label="Rascunho"
        hint="8 passos no OmniVoice, metade do tempo, mais áspero. Bom para ouvir o ritmo antes da versão final."
        :disabled="busy"
      />
      <p class="form__voice">
        <strong>Narra com:</strong> {{ narratedWith }}.
        <RouterLink to="/voz/narracao" @click="open = false">Mudar na Narração</RouterLink>
      </p>
    </form>

    <template #footer>
      <AppButton @click="open = false">Cancelar</AppButton>
      <AppButton variant="primary" type="submit" form="import-script-form" :loading="busy" :disabled="!file">
        Mandar para a fila
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

.form__voice {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
  overflow-wrap: anywhere;
}
</style>
