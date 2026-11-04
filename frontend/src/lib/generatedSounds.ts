/* Os sons gerados na interface (`audio.generated`): a lista da spec, o som novo a partir do catálogo, o menu por família
   e as operações que o arrasto na trilha SFX e o "Bipar a seleção" mandam. Funções puras sobre a spec; a validação de
   verdade é do servidor, que completa os padrões de `params`. */
import type { AudioEffectParam, AudioEffectValue, AudioGeneratorInfo, EditOperation, GeneratedSoundSettings } from '@/api'
import { clampParam } from './audioEffects'
import { getPath, setPath } from './editorPaths'
import { roundSeconds } from './timeline'

export const GENERATED_PATH = 'audio.generated'
/** A trilha da linha do tempo onde os sons gerados aparecem: o barramento dos efeitos sonoros. */
export const GENERATED_TRACK = 'SFX'
/** O alvo da cadeia de efeitos de um som gerado, como o catálogo dos efeitos o escreve. */
export const GENERATED_EFFECT_TARGET = 'audio.generated.N'

/** O nome de cada família de geradores no menu. */
export const FAMILY_NAMES: Record<string, string> = {
  tons: 'Tons',
  ruído: 'Ruído',
  telefonia: 'Telefonia',
  instrumentos: 'Instrumentos',
  ritmo: 'Ritmo',
  dados: 'Dados',
}

/** A duração do bipe de censura sem palavra marcada e o menor som que a interface cria. */
export const MIN_SOUND_SECONDS = 0.01
export const MAX_SOUND_SECONDS = 600

/** Os sons gerados que a spec tem; vazia se ainda não há nenhum. */
export function generatedList(spec: unknown): GeneratedSoundSettings[] {
  const value = getPath(spec, GENERATED_PATH)
  return Array.isArray(value) ? (value as GeneratedSoundSettings[]) : []
}

/** O som novo: o gerador com os padrões dele (o servidor completa os parâmetros) e a duração que ele pede. */
export function newSound(info: Pick<AudioGeneratorInfo, 'type' | 'default_duration'>, start = 0): GeneratedSoundSettings {
  return { generator: info.type, params: {}, start: roundSeconds(Math.max(start, 0)), duration: info.default_duration }
}

/** Acrescenta o som à spec. Devolve a posição dele. */
export function addGeneratedIn(spec: Record<string, unknown>, sound: GeneratedSoundSettings): number {
  const list = getPath(spec, GENERATED_PATH)
  if (Array.isArray(list)) {
    list.push(sound)
    return list.length - 1
  }
  setPath(spec, GENERATED_PATH, [sound])
  return 0
}

/** Tira o som. Ao esvaziar, a chave some da spec: projeto sem som gerado fica igual ao de antes de existirem. */
export function removeGeneratedIn(spec: Record<string, unknown>, index: number): boolean {
  const list = getPath(spec, GENERATED_PATH)
  if (!Array.isArray(list) || index < 0 || index >= list.length) return false
  list.splice(index, 1)
  if (list.length === 0) setPath(spec, GENERATED_PATH, undefined)
  return true
}

/** O valor de um parâmetro como o formulário o mostra: o da spec, ou o padrão do catálogo quando a spec não o tem. */
export function soundParamValue(sound: Pick<GeneratedSoundSettings, 'params'>, param: Pick<AudioEffectParam, 'name' | 'default'>): AudioEffectValue | null {
  const stored = sound.params?.[param.name]
  return stored !== undefined ? stored : (param.default as AudioEffectValue | null)
}

/** O número limitado à faixa do parâmetro (o servidor recusa fora dela). */
export const clampSoundParam = clampParam

/** O menu do "+ Gerar som": os geradores agrupados por família, na ordem em que o catálogo os lista. */
export function groupByFamily(generators: readonly AudioGeneratorInfo[]): Array<{ family: string; label: string; items: AudioGeneratorInfo[] }> {
  const groups = new Map<string, AudioGeneratorInfo[]>()
  for (const info of generators) {
    const list = groups.get(info.family) ?? []
    list.push(info)
    groups.set(info.family, list)
  }
  return [...groups].map(([family, items]) => ({ family, label: FAMILY_NAMES[family] ?? family, items }))
}

/** O item da trilha SFX é um som gerado. */
export const isGeneratedItem = (trackId: string): boolean => trackId === GENERATED_TRACK

/** Mover (ou aparar) um som gerado na trilha: o `generated_set` com o início e, quando a borda de saída mexeu, a duração. */
export function generatedMoveOperation(index: number, start: number, duration?: number): EditOperation {
  return {
    type: 'generated_set',
    index,
    start: roundSeconds(start),
    ...(duration === undefined ? {} : { duration: roundSeconds(Math.max(duration, MIN_SOUND_SECONDS)) }),
  }
}

/** O bipe de censura sobre um intervalo de um item (tempos da linha do tempo): silencia o item e põe o Tom de 1 kHz. */
export function censorBeepOperation(target: string, start: number, end: number): EditOperation {
  return { type: 'censor_beep', target, start, end }
}
