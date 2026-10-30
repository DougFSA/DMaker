import type { RouteLocationRaw } from 'vue-router'
import { renderResultsFromJob } from './outputs'

/** Para onde o aviso de fim de job leva: o rótulo do botão e a rota. */
export interface JobDestination {
  label: string
  to: RouteLocationRaw
}

export interface FinishedJob {
  description: string
  project: string | null
  result: unknown
}

/** Telas que disparam jobs de áudio, pela descrição que o servidor dá a cada um (o início dela é fixo). */
const SCREENS: Array<{ starts: RegExp; label: string; to: RouteLocationRaw }> = [
  { starts: /^isolar voz/i, label: 'Abrir Isolar voz', to: { name: 'voice-isolate' } },
  { starts: /^(corrigir fala|palavras de)/i, label: 'Abrir Corrigir fala', to: { name: 'voice-fix' } },
  { starts: /^trocar voz/i, label: 'Abrir Trocar voz', to: { name: 'voice-swap' } },
  { starts: /^narração/i, label: 'Abrir Narração', to: { name: 'voice-narration' } },
  { starts: /^prévia da voz/i, label: 'Abrir Vozes', to: { name: 'voice' } },
  { starts: /^dublagem/i, label: 'Abrir Dublagem', to: { name: 'dubbing' } },
  { starts: /^baixar modelo/i, label: 'Abrir Modelos', to: { name: 'models' } },
  { starts: /^agente:/i, label: 'Abrir Agente', to: { name: 'agent' } },
]

/**
 * A tela onde o resultado do job está. Quem gerou vídeo em `output/` (render, preview e exportação) leva às Saídas;
 * job de áudio, de dublagem e de modelo leva à tela que o disparou; os que são de um projeto levam ao projeto.
 * Devolve null quando não há um lugar melhor do que ficar onde a pessoa está.
 */
export function jobDestination(job: FinishedJob): JobDestination | null {
  if (renderResultsFromJob(job.result).length > 0) return { label: 'Ver saídas', to: { name: 'outputs' } }
  const screen = SCREENS.find((candidate) => candidate.starts.test(job.description))
  if (screen) return { label: screen.label, to: screen.to }
  if (job.project) return { label: 'Ver projeto', to: { name: 'project', params: { name: job.project } } }
  return null
}

/** O download de modelo já tem o próprio aviso ("Modelo baixado"), dado pela tela; o aviso global só duplicaria. */
export function announcesItself(job: Pick<FinishedJob, 'description'>): boolean {
  return /^baixar modelo/i.test(job.description)
}
