/* O painel Avançado da conversa: as opções do modelo (contexto, temperatura, semente) e o que está carregado na
   memória (funções puras). Os limites são os que o servidor confere (PATCH da conversa), para a tela avisar antes. */
import type { AgentLoadedModel, AgentModel, AgentOptions } from '@/api'
import { formatBytes } from './agentModels'

/** O contexto mínimo que o servidor aceita, em tokens. */
export const MIN_CONTEXT = 512
export const MAX_TEMPERATURE = 2

/** Aviso do contexto: mais tokens pedem mais memória, e o Ollama recarrega o modelo quando o valor muda. */
export const CONTEXT_WARNING =
  'Contexto maior pede mais memória. Trocar o valor faz o modelo recarregar, o que pode levar alguns minutos.'

const tokens = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 })

/** O maior contexto que o modelo aceita, em tokens; `null` quando o servidor não informa. */
export function contextMax(model: AgentModel | undefined): number | null {
  return model?.context_length ?? null
}

/** Por que o valor do contexto não serve, ou vazio quando serve (ou quando não há valor: vale o padrão). */
export function contextProblem(value: number | null, model: AgentModel | undefined): string {
  if (value === null) return ''
  if (!Number.isInteger(value)) return 'O contexto é um número inteiro de tokens.'
  if (value < MIN_CONTEXT) return `O contexto mínimo é ${tokens.format(MIN_CONTEXT)} tokens.`
  const max = contextMax(model)
  if (max !== null && value > max) return `Este modelo vai até ${tokens.format(max)} tokens.`
  return ''
}

export function temperatureProblem(value: number | null): string {
  if (value === null) return ''
  return value < 0 || value > MAX_TEMPERATURE ? `A temperatura vai de 0 a ${MAX_TEMPERATURE}.` : ''
}

export function seedProblem(value: number | null): string {
  if (value === null) return ''
  return Number.isInteger(value) ? '' : 'A semente é um número inteiro.'
}

export interface OptionValues {
  num_ctx: number | null
  temperature: number | null
  seed: number | null
}

/** Só as opções com valor: o que fica vazio volta ao padrão do ambiente. */
export function optionsFrom(values: OptionValues): AgentOptions {
  const options: AgentOptions = {}
  if (values.num_ctx !== null) options.num_ctx = values.num_ctx
  if (values.temperature !== null) options.temperature = values.temperature
  if (values.seed !== null) options.seed = values.seed
  return options
}

export function valuesOf(options: AgentOptions): OptionValues {
  return { num_ctx: options.num_ctx ?? null, temperature: options.temperature ?? null, seed: options.seed ?? null }
}

export function hasOptions(options: AgentOptions): boolean {
  const values = valuesOf(options)
  return values.num_ctx !== null || values.temperature !== null || values.seed !== null
}

export function sameOptions(first: AgentOptions, second: AgentOptions): boolean {
  const a = valuesOf(first)
  const b = valuesOf(second)
  return a.num_ctx === b.num_ctx && a.temperature === b.temperature && a.seed === b.seed
}

/** Quando o Ollama descarrega o modelo sozinho, como "15:35"; vazio se o servidor não disse ou disse algo ilegível. */
export function expiryTime(iso: string | null): string {
  if (!iso) return ''
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return ''
  return when.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
}

/** "gpt-oss:20b · 9,4 GB na memória · contexto 16.384": o que a pessoa quer saber do modelo carregado. */
export function loadedLabel(model: AgentLoadedModel): string {
  const parts = [model.name, `${formatBytes(model.size)} na memória`]
  if (model.context_length !== null) parts.push(`contexto ${tokens.format(model.context_length)}`)
  return parts.join(' · ')
}
