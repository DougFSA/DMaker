/* Cliente das personas: cadastro e a prévia da persona falando (persona_routes.py).
   Apagar exige `confirm=true`; a prévia é um job que a tela acompanha pelo SSE. */
import { http, withQuery } from './http'
import type { JobStartResponse } from './types'
import type {
  Persona,
  PersonaCatalog,
  PersonaChanges,
  PersonaDraft,
  PersonaEstimate,
  PersonaUse,
} from './types/personas'

const enc = encodeURIComponent

export const personasApi = {
  /** As personas (as prontas e as do usuário) e o que cada tipo aceita. */
  list: () => http.get<PersonaCatalog>('/api/personas'),
  create: (draft: PersonaDraft) => http.post<Persona>('/api/personas', draft),
  /** Cria a persona realista: o servidor confere a foto (jpg/png, lado menor de 512 px) e a guarda na pasta dela. */
  createRealistic: (name: string, voice: string | null, photo: File) => {
    const form = new FormData()
    form.append('name', name)
    if (voice) form.append('voice', voice)
    form.append('photo', photo, photo.name)
    return http.postForm<Persona>('/api/personas/realistic', form)
  },
  /** Quanto a prévia leva neste computador, antes de começar (nulo nos motores rápidos). */
  previewEstimate: (id: string, phrase: string) =>
    http.get<PersonaEstimate>(withQuery(`/api/personas/${enc(id)}/preview/estimate`, { phrase })),
  update: (id: string, changes: PersonaChanges) => http.put<Persona>(`/api/personas/${enc(id)}`, changes),
  remove: (id: string) => http.delete<{ removed: string }>(`/api/personas/${enc(id)}?confirm=true`),
  /** Põe a persona num projeto: trecho de tela cheia (`segment`) ou sobreposição no canto (`overlay`). */
  use: (id: string, request: PersonaUse) =>
    http.post<{ project: string; placement: string }>(`/api/personas/${enc(id)}/use`, request),
  /** Renderiza uma frase curta com a persona (job); sem frase, a do servidor. */
  preview: (id: string, phrase: string) =>
    http.post<JobStartResponse>(`/api/personas/${enc(id)}/preview`, { phrase }),
}
