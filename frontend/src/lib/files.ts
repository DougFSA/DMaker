/* Arquivos na tela: o filtro de tipo do envio, tamanhos legíveis e o download por link programático. */

const decimal = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 })

/** Bytes como "512 B", "3,4 KB", "12,3 MB" ou "1,5 GB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${Math.max(0, Math.round(bytes))} B`
  if (bytes < 1024 ** 2) return `${decimal.format(bytes / 1024)} KB`
  if (bytes < 1024 ** 3) return `${decimal.format(bytes / 1024 ** 2)} MB`
  return `${decimal.format(bytes / 1024 ** 3)} GB`
}

/**
 * O arquivo passa no filtro `accept` do `<input type="file">`? Aceita extensões (".txt"), tipos exatos
 * ("video/mp4") e famílias ("audio/*"), separados por vírgula. Arrastar e soltar ignora o `accept` do input,
 * por isso o envio confere por conta própria.
 */
export function acceptsFile(file: { name: string; type: string }, accept: string): boolean {
  const rules = accept
    .split(',')
    .map((rule) => rule.trim().toLowerCase())
    .filter(Boolean)
  if (rules.length === 0) return true
  const name = file.name.toLowerCase()
  const type = file.type.toLowerCase()
  return rules.some((rule) => {
    if (rule.startsWith('.')) return name.endsWith(rule)
    if (rule.endsWith('/*')) return type.startsWith(rule.slice(0, -1))
    return type === rule
  })
}

export interface FilteredFiles {
  accepted: File[]
  /** Fora do tipo pedido. */
  rejected: File[]
  /** Maiores que o limite de bytes. */
  tooBig: File[]
}

/** Separa o que o envio aceita do que ele recusa, para a tela dizer o motivo de cada recusa. */
export function filterFiles(files: File[], accept: string, maxBytes?: number): FilteredFiles {
  const result: FilteredFiles = { accepted: [], rejected: [], tooBig: [] }
  for (const file of files) {
    if (!acceptsFile(file, accept)) result.rejected.push(file)
    else if (maxBytes !== undefined && file.size > maxBytes) result.tooBig.push(file)
    else result.accepted.push(file)
  }
  return result
}

/** Junta arquivos novos aos já escolhidos sem repetir o mesmo arquivo (nome, tamanho e data iguais). */
export function mergeFiles(current: File[], added: File[]): File[] {
  const key = (file: File) => `${file.name}|${file.size}|${file.lastModified}`
  const seen = new Set(current.map(key))
  const fresh = added.filter((file) => {
    const id = key(file)
    if (seen.has(id)) return false
    seen.add(id)
    return true
  })
  return [...current, ...fresh]
}

/** Acrescenta `t=<token>` ao endereço, para o navegador buscar de novo um arquivo que o servidor regravou no mesmo caminho. */
export function bustCache(url: string, token: string | number): string {
  return `${url}${url.includes('?') ? '&' : '?'}t=${encodeURIComponent(String(token))}`
}

/** Baixa o arquivo do endereço criando um link e clicando nele: serve para URL que só se conhece depois de um job (o .zip das trilhas). */
export function triggerDownload(url: string, filename = ''): void {
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.rel = 'noopener'
  link.hidden = true
  document.body.appendChild(link)
  link.click()
  link.remove()
}
