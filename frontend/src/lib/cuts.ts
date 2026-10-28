import type { CutIntensity, CutItem, CutReport } from '@/api'
import type { BadgeTone } from '@/components/ui/AppBadge.vue'
import { baseName, formatClock } from './format'

export const INTENSITIES: Array<{ value: CutIntensity; label: string; hint: string }> = [
  { value: 'suave', label: 'Suave', hint: 'Só as pausas longas.' },
  { value: 'normal', label: 'Normal', hint: 'Pausas e vícios de fala (hã, é isolado, tipo, né no fim da frase).' },
  { value: 'agressiva', label: 'Agressiva', hint: 'Também os falsos começos e as frases repetidas: fica a última tomada.' },
]

const REASON_NAMES: Record<string, [string, string]> = {
  silence: ['pausa', 'pausas'],
  filler: ['vício', 'vícios'],
  repetition: ['repetição', 'repetições'],
}

const REASON_TONES: Record<string, BadgeTone> = {
  silence: 'neutral',
  filler: 'warning',
  repetition: 'info',
}

export function reasonTone(reason: CutItem['reason']): BadgeTone {
  return REASON_TONES[reason] ?? 'neutral'
}

/** "14 pausas, 7 vícios, 1 repetição": só o que ainda está aplicado, na ordem pausa, vício, repetição. */
export function reasonCounts(counts: Record<string, number>): string {
  const parts: string[] = []
  for (const [reason, [one, many]] of Object.entries(REASON_NAMES)) {
    const total = counts[reason] ?? 0
    if (total > 0) parts.push(`${total} ${total === 1 ? one : many}`)
  }
  return parts.join(', ')
}

/** "2:00 para 1:28 (27% a menos)": o resumo do tamanho do corte. */
export function cutsSummary(report: CutReport): string {
  const percent = Math.round(report.removed_percent)
  return `${formatClock(report.duration_before_s)} para ${formatClock(report.duration_after_s)} (${percent}% a menos)`
}

/** Instante na gravação original com décimos de segundo: "01:23.4". */
export function formatCutTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const rest = (seconds % 60).toFixed(1).padStart(4, '0')
  return `${String(minutes).padStart(2, '0')}:${rest}`
}

/** Nome sugerido para o projeto de um arquivo: o nome sem a extensão, mais "-corte". */
export function defaultCutName(path: string): string {
  const stem = baseName(path).replace(/\.[^.]+$/, '')
  return stem ? `${stem}-corte` : ''
}
