/* A gravação com hora marcada (o Timer Record do Audacity): início, duração ou fim. A conta é pura: dado o "agora" e o que a
   pessoa preencheu, diz quando começar e quando parar, ou por que o pedido não faz sentido. A gravação roda na aba, que
   precisa ficar aberta até o fim; a tela avisa isso. */

/** O que a pessoa preencheu. Instantes são `Date` (hora local); a duração é em segundos. */
export interface ScheduleInput {
  /** Quando começar; vazio começa agora. */
  startAt?: Date | null
  /** Quando parar. */
  endAt?: Date | null
  /** Por quanto tempo gravar, em segundos. */
  durationSeconds?: number | null
}

export interface ResolvedSchedule {
  /** Milissegundos de espera até começar (0 começa agora). */
  waitMs: number
  /** Quanto gravar, em segundos, a partir do início; nulo grava até a pessoa parar. */
  durationSeconds: number | null
}

export type ScheduleResult = { ok: true; schedule: ResolvedSchedule } | { ok: false; message: string }

/** O maior tempo que uma gravação agendada aceita: um dia, o bastante para uma live ou um culto. */
export const MAX_SCHEDULE_SECONDS = 24 * 3600

/**
 * Resolve o pedido. Aceita início + duração, início + fim, só a duração (começa agora) ou só o fim (começa agora e para
 * nele). Início no passado é recusado, porque seria começar já sem a pessoa perceber; com início e fim, a duração é a
 * diferença.
 */
export function resolveSchedule(input: ScheduleInput, now: Date): ScheduleResult {
  const start = input.startAt ?? null
  const end = input.endAt ?? null
  const duration = input.durationSeconds ?? null
  if (start && start.getTime() < now.getTime() - 60_000) {
    return { ok: false, message: 'O início marcado já passou. Escolha uma hora que ainda não chegou.' }
  }
  const begin = start && start.getTime() > now.getTime() ? start : now
  const waitMs = Math.max(begin.getTime() - now.getTime(), 0)
  let seconds: number | null = null
  if (end) {
    seconds = (end.getTime() - begin.getTime()) / 1000
    if (seconds <= 0) return { ok: false, message: 'O fim precisa ser depois do início.' }
    if (duration !== null && Math.abs(duration - seconds) > 1) {
      return { ok: false, message: 'Preencha a duração ou o fim, não os dois com valores diferentes.' }
    }
  } else if (duration !== null) {
    if (!Number.isFinite(duration) || duration <= 0) return { ok: false, message: 'A duração precisa ser maior que zero.' }
    seconds = duration
  }
  if (seconds !== null && seconds > MAX_SCHEDULE_SECONDS) {
    return { ok: false, message: 'A gravação agendada vai até 24 horas.' }
  }
  return { ok: true, schedule: { waitMs, durationSeconds: seconds } }
}

/** O texto "hh:mm:ss" (ou "mm:ss") de uma contagem em segundos, para o relógio da tela. */
export function clockText(totalSeconds: number): string {
  const whole = Math.max(0, Math.floor(totalSeconds))
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  const seconds = whole % 60
  const two = (value: number) => String(value).padStart(2, '0')
  return hours > 0 ? `${hours}:${two(minutes)}:${two(seconds)}` : `${two(minutes)}:${two(seconds)}`
}

/** Um `Date` a partir do valor de um `<input type="datetime-local">` ("2026-11-04T19:30"); vazio ou inválido, nulo. */
export function parseLocalDateTime(value: string): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}
