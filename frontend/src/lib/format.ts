/* Formatação de números e datas para a tela, sempre em PT-BR. */

/** Segundos como "1:05" ou "0:07"; acima de uma hora, "1:02:03". */
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  const pad = (value: number) => String(value).padStart(2, '0')
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${minutes}:${pad(secs)}`
}

/** Duração falada: "12 s", "3 min 05 s". */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  if (total < 60) return `${total} s`
  const minutes = Math.floor(total / 60)
  const secs = String(total % 60).padStart(2, '0')
  return `${minutes} min ${secs} s`
}

const decimal = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 })

export function formatSizeMb(megabytes: number): string {
  if (megabytes >= 1024) return `${decimal.format(megabytes / 1024)} GB`
  return `${decimal.format(megabytes)} MB`
}

const dateTime = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

/** Data de modificação vinda do servidor (segundos desde 1970). */
export function formatTimestamp(epochSeconds: number): string {
  return dateTime.format(new Date(epochSeconds * 1000))
}

/** "agora há pouco", "há 5 min", "há 3 h", "há 2 dias"; datas mais antigas viram a data completa. */
export function formatRelative(epochSeconds: number, nowMs: number = Date.now()): string {
  const diff = Math.max(0, Math.round((nowMs - epochSeconds * 1000) / 1000))
  if (diff < 60) return 'agora há pouco'
  if (diff < 3600) return `há ${Math.floor(diff / 60)} min`
  if (diff < 86400) return `há ${Math.floor(diff / 3600)} h`
  if (diff < 86400 * 7) {
    const days = Math.floor(diff / 86400)
    return days === 1 ? 'há 1 dia' : `há ${days} dias`
  }
  return formatTimestamp(epochSeconds)
}

/** Último trecho de um caminho, com / ou \ (o servidor devolve os dois). */
export function baseName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path
}
