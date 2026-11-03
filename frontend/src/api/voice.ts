/* Cliente do estúdio de voz: biblioteca, clonar, desenhar, narrar e pronúncia (voice_routes.py). */
import { http, withQuery } from './http'
import type { JobStartResponse } from './types'
import type {
  AddPronunciationRequest,
  CloneVoiceRequest,
  DesignVoiceRequest,
  PronunciationList,
  SpeakRequest,
  VoiceDesignOptions,
  VoiceProfile,
} from './types/voice'

const enc = encodeURIComponent

export const voiceApi = {
  /** A biblioteca de vozes; com `brand`, só as dessa marca e as sem marca. */
  list: (brand?: string | null) => http.get<VoiceProfile[]>(withQuery('/api/voices', { brand })),
  /** Gênero, faixa etária, tom, sotaque e idiomas dos selects de "Desenhar voz". */
  designOptions: () => http.get<VoiceDesignOptions>('/api/voices/design-options'),
  /** Endereço de um áudio de output/ ou cache/voice; `download` pede o arquivo como anexo. */
  audioUrl: (path: string, download = false) =>
    withQuery('/api/voices/audio', { path, download: download ? true : null }),

  /** Clona a voz de uma gravação (arquivo ou microfone). Sem `reference_text`, o servidor transcreve. */
  clone: (request: CloneVoiceRequest) => {
    const form = new FormData()
    form.append('name', request.name)
    form.append('audio', request.audio, request.filename ?? 'gravacao')
    if (request.reference_text) form.append('reference_text', request.reference_text)
    if (request.brand) form.append('brand', request.brand)
    if (request.language) form.append('language', request.language)
    return http.postForm<VoiceProfile>('/api/voices/clone', form)
  },
  /** Cria uma voz a partir de uma descrição (gênero, idade, tom, sotaque ou texto livre). */
  design: (request: DesignVoiceRequest) => http.post<VoiceProfile>('/api/voices/design', request),
  /** Narra o texto num job cancelável; as falas prontas chegam como eventos `utterance` do SSE. */
  speak: (request: SpeakRequest) => http.post<JobStartResponse>('/api/voices/speak', request),
  /** Gera uma amostra curta da voz (job). */
  preview: (voiceId: string) => http.post<JobStartResponse>(`/api/voices/${enc(voiceId)}/preview`),
  remove: (voiceId: string) => http.delete<{ ok: boolean }>(`/api/voices/${enc(voiceId)}`),

  pronunciation: {
    /** Termos que valem para a marca (os dela e os globais); sem `language`, de todos os idiomas. */
    list: (brand?: string | null, language?: string | null) =>
      http.get<PronunciationList>(withQuery('/api/voices/pronunciation', { brand, language })),
    add: (request: AddPronunciationRequest) => http.post<PronunciationList>('/api/voices/pronunciation', request),
    remove: (term: string, brand?: string | null, language?: string | null) =>
      http.delete<PronunciationList>(withQuery('/api/voices/pronunciation', { term, brand, language })),
  },
}
