import type { InfographicInfo, InfographicParam } from '@/api'

/** O valor de um campo do formulário: o que se digita (texto) ou o que se marca (sim ou não). */
export type FieldValue = string | number | boolean

/** Valores que o formulário mostra ao abrir um modelo: o exemplo dele e, no resto, o padrão do esquema. */
export function initialValues(info: InfographicInfo): Record<string, FieldValue> {
  const values: Record<string, FieldValue> = {}
  for (const param of info.params) {
    const start = info.example[param.name] ?? param.default
    if (start !== undefined) values[param.name] = start
  }
  return values
}

/** Texto digitado num campo de número vira número; vazio ou ilegível volta `undefined` (o campo não vai no pedido). */
export function parseNumber(text: string, integer: boolean): number | undefined {
  const cleaned = text.trim().replace(',', '.')
  if (!cleaned) return undefined
  const value = Number(cleaned)
  if (!Number.isFinite(value)) return undefined
  return integer ? Math.round(value) : value
}

/** Os valores do formulário já no formato do pedido: só os campos que têm valor, com o tipo certo. */
export function requestParams(
  info: InfographicInfo,
  values: Record<string, FieldValue | undefined>,
): Record<string, FieldValue> {
  const params: Record<string, FieldValue> = {}
  for (const param of info.params) {
    const value = values[param.name]
    if (value === undefined || value === '') continue
    if (param.type === 'number' || param.type === 'integer') {
      const number = typeof value === 'number' ? value : parseNumber(String(value), param.type === 'integer')
      if (number !== undefined) params[param.name] = number
    } else {
      params[param.name] = value
    }
  }
  return params
}

/** O que está errado em um campo, em português simples, ou `null`. É a mesma regra do esquema no servidor. */
export function fieldProblem(param: InfographicParam, value: FieldValue | undefined): string | null {
  const empty = value === undefined || value === ''
  if (empty) return param.required ? `${param.label}: preencha este campo.` : null
  if (param.type === 'number' || param.type === 'integer') {
    const number = typeof value === 'number' ? value : parseNumber(String(value), false)
    if (number === undefined) return `${param.label}: precisa ser um número.`
    if (param.type === 'integer' && !Number.isInteger(number)) return `${param.label}: precisa ser um número inteiro.`
    if (param.min !== undefined && number < param.min) return `${param.label}: não pode ser menor que ${param.min}.`
    if (param.max !== undefined && number > param.max) return `${param.label}: não pode passar de ${param.max}.`
  }
  if (param.type === 'text' && param.max_length !== undefined && String(value).length > param.max_length) {
    return `${param.label}: no máximo ${param.max_length} caracteres.`
  }
  return null
}

/** Todos os problemas do formulário, por nome de parâmetro. */
export function formProblems(
  info: InfographicInfo,
  values: Record<string, FieldValue | undefined>,
): Record<string, string> {
  const problems: Record<string, string> = {}
  for (const param of info.params) {
    const problem = fieldProblem(param, values[param.name])
    if (problem) problems[param.name] = problem
  }
  return problems
}

/** O trecho de spec pronto para copiar: a composição com o modelo e os parâmetros que diferem do padrão. */
export function specSnippet(info: InfographicInfo, params: Record<string, FieldValue>): string {
  const data: Record<string, FieldValue> = {}
  for (const param of info.params) {
    const value = params[param.name]
    if (value === undefined) continue
    if (param.default !== undefined && value === param.default && !param.required) continue
    data[param.name] = value
  }
  return JSON.stringify({ type: 'html', infographic: info.name, region: 'topo', start: 0, end: 4, data }, null, 2)
}

/** Modelos que combinam com a busca (nome, título ou descrição, sem diferenciar maiúsculas). */
export function filterInfographics(items: InfographicInfo[], query: string): InfographicInfo[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return items
  return items.filter(
    (item) =>
      item.name.toLowerCase().includes(needle) ||
      item.title.toLowerCase().includes(needle) ||
      item.description.toLowerCase().includes(needle),
  )
}
