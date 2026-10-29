/* Leitura e escrita da spec por caminho ("timeline.0.reframe.focus.1"), e a poda dos campos vazios antes de
   mandar a spec ao servidor. Funções puras sobre JSON, sem rede e sem Vue. */

/** Chaves que nunca são seguidas num caminho: caminho vindo de campo digitado não pode mexer no protótipo. */
const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype'])

type Container = Record<string, unknown> | unknown[]

function isIndexKey(part: string): boolean {
  return part !== '' && !Number.isNaN(Number(part))
}

function keyOf(part: string): string | number {
  return isIndexKey(part) ? Number(part) : part
}

function isContainer(value: unknown): value is Container {
  return value !== null && typeof value === 'object'
}

/** O valor em `path` (índices de lista são números no caminho), ou `undefined` se algum trecho não existe. */
export function getPath(root: unknown, path: string): unknown {
  let current: unknown = root
  for (const part of path.split('.')) {
    if (!isContainer(current)) return undefined
    if (FORBIDDEN_KEYS.has(part)) return undefined
    current = (current as Record<string | number, unknown>)[keyOf(part)]
  }
  return current
}

/**
 * Escreve `value` em `root` seguindo o caminho e cria os objetos e listas que faltam pelo meio (a próxima parte
 * ser um número decide se o contêiner é uma lista). `undefined` remove a chave (ou o item da lista), que é como
 * um campo limpo volta a valer o padrão do servidor.
 */
export function setPath(root: Record<string, unknown>, path: string, value: unknown): void {
  const parts = path.split('.')
  if (parts.some((part) => FORBIDDEN_KEYS.has(part))) return
  let current: Container = root
  for (let i = 0; i < parts.length - 1; i += 1) {
    const key = keyOf(parts[i] as string)
    const holder = current as Record<string | number, unknown>
    if (!isContainer(holder[key])) holder[key] = isIndexKey(parts[i + 1] as string) ? [] : {}
    current = holder[key] as Container
  }
  const last = keyOf(parts[parts.length - 1] as string)
  if (value === undefined) {
    if (Array.isArray(current)) {
      if (typeof last === 'number' && last < current.length) current.splice(last, 1)
    } else {
      delete (current as Record<string, unknown>)[last as string]
    }
  } else {
    ;(current as Record<string | number, unknown>)[last] = value
  }
}

/**
 * Tira os campos vazios (`undefined`, `null` e texto vazio) e os objetos que ficam vazios depois disso; listas
 * ficam como estão, mesmo vazias, porque `overlays: []` quer dizer algo. Não altera o que recebe: devolve uma cópia.
 */
export function pruneEmpty<T>(value: T): T {
  if (Array.isArray(value)) return value.map((item) => pruneEmpty(item)) as T
  if (isContainer(value)) {
    const out: Record<string, unknown> = {}
    for (const [key, raw] of Object.entries(value)) {
      if (raw === undefined || raw === null || raw === '') continue
      const cleaned = pruneEmpty(raw)
      if (isContainer(cleaned) && !Array.isArray(cleaned) && Object.keys(cleaned).length === 0) continue
      out[key] = cleaned
    }
    return out as T
  }
  return value
}

/** Cópia profunda por JSON: a spec é só JSON, e assim sai do proxy reativo sem levar o Vue junto. */
export function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}
