/* Cliente das rotas de áudio: enviar arquivo, isolar voz, achar palavras, corrigir fala e trocar voz
   (speech_routes.py). Tudo, menos o envio, é um job: a resposta traz só o `job_id`. */
import { http, withQuery } from './http'
import type { JobStartResponse } from './types'
import type { ConvertVoiceRequest, FixSpeechRequest, IsolateRequest, SpeechUpload, WordsRequest } from './types/speech'

export const speechApi = {
  /** Envia um vídeo ou áudio; o servidor guarda em cache/uploads e devolve o caminho para as outras rotas. */
  upload: (file: Blob, filename?: string) => {
    const form = new FormData()
    form.append('file', file, filename ?? (file instanceof File ? file.name : 'arquivo'))
    return http.postForm<SpeechUpload>('/api/speech/upload', form)
  },
  /** Separa a voz do fundo (música e ruído) de um arquivo ou de um trecho dele. */
  isolate: (request: IsolateRequest) => http.post<JobStartResponse>('/api/speech/isolate', request),
  /** Transcreve com o tempo de cada palavra, para a pessoa clicar no trecho a corrigir. */
  words: (request: WordsRequest) => http.post<JobStartResponse>('/api/speech/words', request),
  /** Troca uma palavra ou frase dita errado, na voz do próprio falante. */
  fix: (request: FixSpeechRequest) => http.post<JobStartResponse>('/api/speech/fix', request),
  /** Troca a voz da gravação (ou de um trecho) por uma voz da biblioteca. */
  convert: (request: ConvertVoiceRequest) => http.post<JobStartResponse>('/api/speech/convert', request),
  /** Endereço para tocar uma mídia qualquer que a interface pode servir (a original de um A/B, por exemplo). */
  fileUrl: (path: string) => withQuery('/api/file', { path }),
}
