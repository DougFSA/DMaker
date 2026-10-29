<script setup lang="ts">
/* Clonar uma voz a partir de uma gravação: um arquivo ou o microfone, mais nome, idioma e marca. O botão só
   habilita com a permissão do dono da voz marcada. Depois de clonar, a voz nova já fica escolhida para o roteiro. */
import { computed, ref, watch } from 'vue'
import { errorMessage, type VoiceOption } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import AppTextarea from '@/components/ui/AppTextarea.vue'
import FileUpload from '@/components/ui/FileUpload.vue'
import SegmentedControl, { type SegmentOption } from '@/components/ui/SegmentedControl.vue'
import VoiceRecorder from '@/components/voice/VoiceRecorder.vue'
import type { Recording } from '@/lib/microphone'
import { cloneMissing, MAX_REFERENCE_BYTES, REFERENCE_ACCEPT } from '@/lib/voice'
import { useToastsStore } from '@/stores/toasts'
import { useVoiceStore } from '@/stores/voice'

defineProps<{ languages: VoiceOption[]; brands: VoiceOption[] }>()

type Source = 'file' | 'mic'
const SOURCES: SegmentOption<Source>[] = [
  { value: 'file', label: 'Enviar arquivo' },
  { value: 'mic', label: 'Gravar pelo microfone' },
]

const voices = useVoiceStore()
const toasts = useToastsStore()

const name = ref('')
const source = ref<Source>('file')
const files = ref<File[]>([])
const recording = ref<Recording | null>(null)
const recorder = ref<InstanceType<typeof VoiceRecorder> | null>(null)
const referenceText = ref('')
const language = ref('pt')
const brand = ref('')
const consent = ref(false)
const busy = ref(false)

/** O áudio que vai no pedido: o arquivo escolhido ou a gravação, conforme a origem marcada. */
const reference = computed(() => {
  if (source.value === 'mic') {
    return recording.value ? { audio: recording.value.blob, filename: recording.value.filename } : null
  }
  const file = files.value[0]
  return file ? { audio: file, filename: file.name } : null
})

const missing = computed(() =>
  cloneMissing({ name: name.value, hasReference: reference.value !== null, consent: consent.value }),
)
const canSubmit = computed(() => missing.value.length === 0 && !busy.value)
const buttonLabel = computed(() => {
  if (!busy.value) return 'Clonar voz'
  return referenceText.value.trim() ? 'Clonando...' : 'Clonando e transcrevendo...'
})

// trocar para o arquivo com o microfone aberto para a gravação (e a guarda): nada grava escondido
watch(source, (current) => {
  if (current === 'file') recorder.value?.stop()
})

function reset(): void {
  name.value = ''
  files.value = []
  recording.value = null
  referenceText.value = ''
  consent.value = false
}

async function submit(): Promise<void> {
  const audio = reference.value
  if (!audio || !canSubmit.value) return
  busy.value = true
  try {
    const profile = await voices.clone({
      name: name.value.trim(),
      audio: audio.audio,
      filename: audio.filename,
      reference_text: referenceText.value.trim() || null,
      brand: brand.value || null,
      language: language.value,
    })
    toasts.push({ tone: 'success', title: `Voz "${profile.name}" clonada`, description: 'Já está escolhida para o roteiro.' })
    reset()
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não consegui clonar a voz', description: errorMessage(error) })
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form class="clone" novalidate @submit.prevent="submit">
    <p class="notice">
      Clone apenas vozes que você tem permissão do dono para usar. Grave ou envie de 5 a 8 segundos de fala limpa, sem
      música ao fundo.
    </p>

    <AppInput v-model="name" label="Nome da voz" placeholder="Ex.: Locutora da clínica" required />

    <SegmentedControl v-model="source" :options="SOURCES" label="De onde vem a gravação" />

    <FileUpload
      v-show="source === 'file'"
      v-model="files"
      label="Arquivo de áudio ou vídeo"
      :accept="REFERENCE_ACCEPT"
      :max-bytes="MAX_REFERENCE_BYTES"
      :disabled="busy"
    />
    <VoiceRecorder v-show="source === 'mic'" ref="recorder" v-model="recording" />

    <AppTextarea
      v-model="referenceText"
      label="O que está sendo dito na gravação (opcional)"
      :rows="2"
      placeholder="Se ficar vazio, o Whisper transcreve a gravação."
      :disabled="busy"
    />

    <div class="clone__pair">
      <AppSelect v-model="language" label="Idioma" :options="languages" :disabled="busy" />
      <AppSelect
        v-model="brand"
        label="Marca"
        :options="brands"
        placeholder="Sem marca (serve para qualquer uma)"
        :disabled="busy"
      />
    </div>

    <AppCheckbox v-model="consent" label="Tenho permissão do dono desta voz para cloná-la" :disabled="busy" />

    <div class="clone__submit">
      <AppButton type="submit" variant="primary" :disabled="!canSubmit" :loading="busy">{{ buttonLabel }}</AppButton>
      <p v-if="missing.length && !busy" class="clone__missing">Para clonar falta: {{ missing.join(', ') }}.</p>
    </div>
  </form>
</template>

<style scoped>
.clone {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.notice {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  background: var(--color-warning-bg);
  font-size: var(--text-sm);
  color: var(--color-text);
}

.clone__pair {
  display: grid;
  /* 16rem: cabe a opção mais longa da marca ("Sem marca (serve para qualquer uma)") sem cortar */
  grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
  gap: var(--space-4);
}

.clone__submit {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3) var(--space-4);
}

.clone__missing {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
</style>
