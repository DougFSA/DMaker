import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type FixSpeechResult, type SpeechWord, type WordsResult } from '@/api'
import type { PickedMedia } from '@/components/media/MediaPicker.vue'
import type { MediaEntry } from '@/lib/media'
import { rangeProblem, type WordSelection } from '@/lib/speech'
import { useWorkspaceStore } from './workspace'
import { createJobRun } from './jobRun'

/** A transcrição de um arquivo, com tudo o que a correção precisa saber dele (o seletor de arquivo pode mudar depois). */
export interface Transcript {
  path: string
  name: string
  entry: MediaEntry | null
  /** O projeto de onde o arquivo veio, para "Usar no projeto". */
  project: string | null
  words: SpeechWord[]
  pauseSeconds: number
}

/** O resultado da correção e o arquivo de que ele saiu. */
export interface FixOutcome extends FixSpeechResult {
  sourceName: string
  entry: MediaEntry | null
  project: string | null
  stamp: number
}

/** Corrigir fala: transcrever, escolher o trecho e trocar o que é dito. Fica aqui porque a transcrição demora. */
export const useFixSpeechStore = defineStore('speechFix', () => {
  const workspace = useWorkspaceStore()

  const media = ref<PickedMedia | null>(null)
  const from = ref<number | null>(null)
  const to = ref<number | null>(null)
  const transcript = ref<Transcript | null>(null)
  const selection = ref<WordSelection | null>(null)
  const text = ref('')
  const voice = ref('')
  const saveVoiceAs = ref('')
  const expand = ref(true)
  const transcription = createJobRun<WordsResult>()
  const correction = createJobRun<FixSpeechResult>()
  const outcome = ref<FixOutcome | null>(null)

  const rangeError = computed(() => rangeProblem(from.value, to.value))
  const busy = computed(() => transcription.running || correction.running)
  const canTranscribe = computed(() => !!media.value && !rangeError.value && !busy.value)
  const canCorrect = computed(() => !!transcript.value && !!selection.value && text.value.trim() !== '' && !busy.value)

  /** O projeto de onde veio o arquivo escolhido: o aberto no momento, quando o arquivo é da mídia do projeto. */
  function projectOf(source: PickedMedia): string | null {
    return source.origin === 'project' ? workspace.currentProject : null
  }

  async function transcribe(): Promise<void> {
    const source = media.value
    if (!source || rangeError.value || busy.value) return
    const result = await transcription.run(() => api.speech.words({ path: source.path, start: from.value, end: to.value }))
    if (!result) return
    transcript.value = {
      path: source.path,
      name: source.name,
      entry: source.entry,
      project: projectOf(source),
      words: result.words,
      pauseSeconds: result.pause_seconds,
    }
    selection.value = null
  }

  async function correct(): Promise<void> {
    const base = transcript.value
    const picked = selection.value
    const wanted = text.value.trim()
    if (!base || !picked || !wanted || busy.value) return
    outcome.value = null
    const result = await correction.run(() =>
      api.speech.fix({
        path: base.path,
        text: wanted,
        start: picked.start,
        end: picked.end,
        voice: voice.value || null,
        save_voice: saveVoiceAs.value.trim() || null,
        expand: expand.value,
      }),
    )
    if (result) {
      outcome.value = { ...result, sourceName: base.name, entry: base.entry, project: base.project, stamp: Date.now() }
    }
  }

  return {
    media,
    from,
    to,
    transcript,
    selection,
    text,
    voice,
    saveVoiceAs,
    expand,
    transcription,
    correction,
    outcome,
    rangeError,
    canTranscribe,
    canCorrect,
    transcribe,
    correct,
  }
})
