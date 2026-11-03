/* A escolha do modelo e do esforço de uma conversa: nomes, selos, aviso de memória e as regras de troca (funções puras). */
import type { AgentCapability, AgentMemory, AgentMode, AgentModel } from '@/api'
import { formatSizeMb } from './format'

const BYTES_PER_MB = 1024 * 1024

export const MODE_LABELS: Record<AgentMode, string> = {
  operate: 'Operar o DMaker',
  free: 'Conversa livre',
}

export const MODE_HINTS: Record<AgentMode, string> = {
  operate: 'O agente usa as ferramentas do DMaker para editar o seu vídeo.',
  free: 'Só conversa, sem ferramentas e sem mexer nos seus projetos.',
}

const CAPABILITY_LABELS: Record<string, string> = {
  vision: 'Imagem',
  tools: 'Ferramentas',
  thinking: 'Raciocínio',
}

/** Os selos que a tela mostra, na ordem do servidor; capacidade desconhecida não vira selo. */
export function capabilityLabels(capabilities: AgentCapability[]): string[] {
  return capabilities.map((capability) => CAPABILITY_LABELS[capability]).filter((label): label is string => !!label)
}

/** "12,8 GB" para os bytes de um modelo ou da memória; nulo (motor que não informa) fica vazio. */
export function formatBytes(bytes: number | null | undefined): string {
  return bytes === null || bytes === undefined ? '' : formatSizeMb(bytes / BYTES_PER_MB)
}

/** Dois nomes são o mesmo modelo? A tag ":latest" é opcional, como no servidor. */
export function sameModel(first: string, second: string): boolean {
  const base = (name: string) => (name.endsWith(':latest') ? name.slice(0, -':latest'.length) : name)
  return base(first) === base(second)
}

export function findModel(models: AgentModel[] | undefined, name: string): AgentModel | undefined {
  return models?.find((model) => sameModel(model.name, name))
}

/** A ordem do seletor: o modelo padrão primeiro e o que não cabe na memória por último (a ordem do servidor se mantém no resto). */
export function sortModels(models: AgentModel[], defaultName: string): AgentModel[] {
  const rank = (model: AgentModel) => (sameModel(model.name, defaultName) ? 0 : model.fit === 'too_big' ? 2 : 1)
  return models
    .map((model, index) => ({ model, index }))
    .sort((a, b) => rank(a.model) - rank(b.model) || a.index - b.index)
    .map((entry) => entry.model)
}

/**
 * O modelo usa ferramentas? Capacidade desconhecida (o motor compatível com a OpenAI não informa) conta como sim: só o
 * modelo cujas capacidades são conhecidas e não incluem "tools" não opera o DMaker.
 */
export function usesTools(model: AgentModel | undefined): boolean {
  return !model || model.capabilities.length === 0 || model.capabilities.includes('tools')
}

/**
 * O modelo lê imagem? Capacidade desconhecida (o motor compatível com a OpenAI não informa) conta como sim, e o servidor
 * é quem recusa se for o caso; só o modelo de capacidades conhecidas e sem "vision" não lê.
 */
export function readsImages(model: AgentModel | undefined): boolean {
  return !model || model.capabilities.length === 0 || model.capabilities.includes('vision')
}

/** Os modelos da lista que de fato têm o selo de imagem, na ordem do servidor. */
export function imageModels(models: AgentModel[]): AgentModel[] {
  return models.filter((model) => model.capabilities.includes('vision'))
}

/** O modelo não serve ao modo escolhido? Só o "Operar o DMaker" precisa de ferramentas; a Conversa livre aceita qualquer um. */
export function cannotOperate(model: AgentModel | undefined, mode: AgentMode): boolean {
  return mode === 'operate' && !usesTools(model)
}

/** O aviso do modelo sem ferramentas numa conversa que opera o DMaker; vazio quando está tudo certo. É o texto do servidor. */
export function toolsNotice(model: AgentModel | undefined, mode: AgentMode): string {
  if (!model || !cannotOperate(model, mode)) return ''
  return `O modelo ${model.name} não usa ferramentas. Para operar o DMaker, escolha um modelo com ferramentas; para conversar com ele, use a Conversa livre.`
}

/** O texto da opção do seletor: nome, tamanho e o que a pessoa precisa saber antes de escolher. */
export function modelOptionLabel(model: AgentModel, mode: AgentMode = 'free'): string {
  const parts = [model.name]
  const size = formatBytes(model.size)
  if (size) parts.push(size)
  if (model.loaded) parts.push('carregado')
  if (cannotOperate(model, mode)) parts.push('não opera o DMaker')
  if (model.fit === 'too_big') parts.push('não cabe na memória')
  else if (model.fit === 'tight') parts.push('memória apertada')
  return parts.join(' · ')
}

export interface MemoryNotice {
  tone: 'warning' | 'error'
  text: string
}

/**
 * O aviso de memória do modelo escolhido, ou nada quando cabe. "Apertado" só avisa (a memória livre varia muito e
 * o modelo costuma rodar); "não cabe" vale uma confirmação antes de enviar.
 */
export function memoryNotice(model: AgentModel | undefined, memory: AgentMemory | null): MemoryNotice | null {
  if (!model) return null
  if (model.fit === 'too_big') {
    const sizes = [formatBytes(model.size) && `o modelo tem ${formatBytes(model.size)}`, memory && `o computador tem ${formatBytes(memory.total)} de memória`]
      .filter(Boolean)
      .join(' e ')
    return {
      tone: 'error',
      text: `Não cabe na memória${sizes ? ` (${sizes})` : ''}. A resposta vai ficar muito lenta ou travar o computador.`,
    }
  }
  if (model.fit === 'tight') {
    return { tone: 'warning', text: 'Memória apertada: o modelo cabe, mas sobra pouco. Se ficar lento, feche outros programas.' }
  }
  return null
}

/** Só o modelo maior que a memória inteira pede confirmação; o apertado envia direto. */
export function needsMemoryConfirmation(model: AgentModel | undefined): boolean {
  return model?.fit === 'too_big'
}

/** O esforço que sobra depois de trocar de modelo: o nível some quando o modelo novo não o tem (o servidor faz o mesmo). */
export function effortAfterModelChange(effort: string | null, model: AgentModel | undefined): string | null {
  if (!effort || !model) return effort
  return model.effort_levels.some((level) => level.value === effort) ? effort : null
}

/** O texto da escolha "sem escolher": o nível que o modelo usa sozinho. */
export function defaultEffortLabel(model: AgentModel | undefined): string {
  const level = model?.effort_levels.find((item) => item.value === model.default_effort)
  return level ? `Padrão do modelo (${level.label})` : 'Padrão do modelo'
}
