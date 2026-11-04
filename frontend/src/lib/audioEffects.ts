/* As contas do bloco "Efeitos de áudio" do painel Filtros, todas puras: qual cadeia a seleção da linha do tempo edita,
   o efeito novo com os padrões do catálogo, e adicionar, remover, mover e ligar sobre a lista da spec. Os efeitos, os
   parâmetros e as faixas vêm do catálogo do servidor (GET /api/audio-effects), nunca de uma cópia escrita aqui. */
import type {
  AudioEffectInfo,
  AudioEffectParam,
  AudioEffectSettings,
  AudioEffectTarget,
  AudioEffectValue,
  CurvePoint,
  TimelineItem,
  TimelineView,
} from '@/api'
import { getPath, setPath } from './editorPaths'
import { displayLabel } from './timeline'

/** Onde mora a cadeia da mistura inteira (o master); as dos itens ficam em `effects` dentro de cada um. */
export const MASTER_LIST_PATH = 'audio.master_effects'

/** A chave do master no catálogo, onde o servidor diz que o master não cresce. */
const MASTER_TARGET_KEY = 'audio.master'

/** A cadeia de efeitos que o painel edita agora. */
export interface EffectChain {
  /** O lugar como o catálogo o escreve (`audio.voiceover.N`): é com ele que se descobre se o Repetir vale ali. */
  targetKey: string
  /** Onde a lista mora na spec (`audio.voiceover.0.effects`). */
  listPath: string
  /** O que está sendo editado, para o cabeçalho ("Voz gravada 1 · entrevista.wav"). */
  title: string
}

/** Uma cadeia para editar, ou um item que não tem som e portanto não tem cadeia. */
export type EffectContext = { kind: 'chain'; chain: EffectChain } | { kind: 'silent' }

/** O item selecionado na linha do tempo, com a trilha dele (o que o store do editor entrega). */
export interface SelectedForEffects {
  trackId: string
  item: Pick<TimelineItem, 'kind' | 'index' | 'label'>
}

export const MASTER_TITLE = 'Master (mistura inteira)'

function chainFor(targetKey: string, listPath: string, title: string, item?: Pick<TimelineItem, 'label'>): EffectContext {
  const label = item ? displayLabel(item.label) : ''
  return { kind: 'chain', chain: { targetKey, listPath, title: label ? `${title} · ${label}` : title } }
}

/**
 * Da seleção ao lugar da cadeia. Sem seleção edita o master. O som do clipe mora em `timeline` e a faixa A1 é só a
 * sombra dele, então escolher um item da A1 edita o clipe da V1 de mesmo índice. Imagem, cartão, texto, gráficos e
 * legendas não têm som: devolvem `silent`.
 */
export function effectContextFor(selected: SelectedForEffects | null, view: Pick<TimelineView, 'tracks'> | null): EffectContext {
  if (!selected) return chainFor(MASTER_TARGET_KEY, MASTER_LIST_PATH, MASTER_TITLE)
  const { trackId, item } = selected
  if (trackId === 'A1') {
    const clip = view?.tracks.find((track) => track.id === 'V1')?.items.find((candidate) => candidate.index === item.index)
    return clip?.kind === 'clip' ? clipChain(clip) : { kind: 'silent' }
  }
  if (trackId === 'V1') return item.kind === 'clip' ? clipChain(item) : { kind: 'silent' }
  if (trackId === 'MUS') return chainFor('audio.music', 'audio.music.effects', 'Música', item)
  if (trackId === 'SFX') return chainFor('audio.generated.N', `audio.generated.${item.index}.effects`, `Som gerado ${item.index + 1}`, item)
  if (trackId === 'NAR') return chainFor('audio.narration.N', `audio.narration.${item.index}.effects`, `Narração ${item.index + 1}`, item)
  if (trackId === 'VO') return chainFor('audio.voiceover.N', `audio.voiceover.${item.index}.effects`, `Voz gravada ${item.index + 1}`, item)
  const externalNumber = /^A(\d+)$/.exec(trackId)?.[1]
  if (externalNumber !== undefined && Number(externalNumber) >= 2) {
    return chainFor('audio.tracks.N', `audio.tracks.${item.index}.effects`, `Faixa de áudio ${trackId}`, item)
  }
  // só o vídeo sobreposto (PiP) tem som entre as camadas V2 em diante; imagem e barra moram na GR
  if (/^V\d+$/.test(trackId) && item.kind === 'video') {
    return chainFor('overlays.N', `overlays.${item.index}.effects`, `Som do PiP ${trackId}`, item)
  }
  return { kind: 'silent' }
}

function clipChain(clip: Pick<TimelineItem, 'index' | 'label'>): EffectContext {
  return chainFor('timeline.N', `timeline.${clip.index}.effects`, `Som do clipe ${clip.index + 1}`, clip)
}

/** O Repetir e os outros que mudam a duração só valem onde o catálogo diz que o item pode crescer. */
export function targetMayGrow(targets: readonly AudioEffectTarget[], targetKey: string): boolean {
  return targets.find((target) => target.target === targetKey)?.may_grow === true
}

/** Os efeitos que o menu "+ Efeito" oferece neste lugar: os que dependem de uma seleção ou de uma curva (Cortar,
 *  Envelope) nascem da edição de onda, não de um clique no menu. Os que trabalham sobre as amostras do item (Redução de
 *  ruído) não valem no master, que roda num grafo ao vivo: `onItem` é falso lá. */
export function effectsFor(effects: readonly AudioEffectInfo[], mayGrow: boolean, onItem = true): AudioEffectInfo[] {
  return effects.filter((info) => !info.needs_selection && (mayGrow || !info.changes_duration) && (onItem || !info.sample_stage))
}

/** O valor de `profile` que não guarda perfil: o trecho mais quieto do próprio item. */
export const AUTO_PROFILE = 'auto'

/** Os nomes dos perfis de ruído que o projeto guarda (`audio.noise_profiles`). */
export function profileNames(spec: unknown): string[] {
  const profiles = getPath(spec, 'audio.noise_profiles')
  return profiles && typeof profiles === 'object' ? Object.keys(profiles as Record<string, unknown>) : []
}

/** O alvo de `edit_project` de uma cadeia, a partir de onde ela mora na spec (`timeline.0.effects` vira `timeline.0`). */
export function targetOfList(listPath: string): string {
  if (listPath === MASTER_LIST_PATH) return MASTER_TARGET_KEY
  return listPath.replace(/\.effects$/, '')
}

/** Um nome livre para o perfil novo (`perfil-1`, `perfil-2`...). */
export function freeProfileName(existing: readonly string[]): string {
  let number = existing.length + 1
  while (existing.includes(`perfil-${number}`)) number += 1
  return `perfil-${number}`
}

/**
 * O efeito novo com os valores que o formulário mostra: o `type` e cada parâmetro com o padrão do catálogo. Fica de
 * fora o parâmetro sem padrão e o `enabled` (omitido vale ligado), para a spec não guardar o que não diz nada.
 */
export function newEffect(info: AudioEffectInfo): AudioEffectSettings {
  const effect: AudioEffectSettings = { type: info.type }
  for (const param of info.parameters) {
    if (param.default === null || param.default === undefined) continue
    // a lista do EQ vai por cópia: o efeito da spec nunca compartilha o array do catálogo
    effect[param.name] = Array.isArray(param.default) ? JSON.parse(JSON.stringify(param.default)) : param.default
  }
  return effect
}

/* ---------- ler um efeito ---------- */

/** A cadeia que a spec tem neste caminho; vazia se ainda não existe. */
export function chainOf(spec: unknown, listPath: string): AudioEffectSettings[] {
  const value = getPath(spec, listPath)
  return Array.isArray(value) ? (value as AudioEffectSettings[]) : []
}

/** O efeito está ligado: o `enabled` omitido vale ligado. */
export function isEnabled(effect: Pick<AudioEffectSettings, 'enabled'>): boolean {
  return effect.enabled !== false
}

/** Os parâmetros que são uma lista do EQ (os controles deslizantes e os pontos da curva), não um campo de formulário. */
export function isListParam(param: Pick<AudioEffectParam, 'kind'>): boolean {
  return param.kind === 'band_gains' || param.kind === 'freq_points'
}

/** O valor do parâmetro como o formulário o mostra: o da spec, ou o padrão do catálogo quando a spec não o tem. */
export function paramValue(effect: AudioEffectSettings, param: Pick<AudioEffectParam, 'name' | 'kind' | 'default'>): AudioEffectValue | null {
  const stored = effect[param.name]
  if (param.kind === 'boolean') return typeof stored === 'boolean' ? stored : param.default === true
  if (isListParam(param)) return Array.isArray(stored) ? (stored as number[] | CurvePoint[]) : Array.isArray(param.default) ? param.default : null
  if (param.kind === 'choice' || param.kind === 'profile') {
    // uma escolha pode ter opções numéricas (a inclinação do passa-alta, 6 a 48 dB por oitava): a spec guarda o número
    if (typeof stored === 'string' || (param.kind === 'choice' && typeof stored === 'number')) return stored
    return typeof param.default === 'string' || typeof param.default === 'number' ? param.default : null
  }
  if (typeof stored === 'number') return stored
  return typeof param.default === 'number' ? param.default : null
}

/**
 * Se o formulário mostra o parâmetro agora: sem `shown_when` sempre; com ele, cada campo citado precisa valer o que a
 * condição pede. O valor de um campo que a spec não guarda é o padrão do catálogo (`siblings`, os parâmetros do mesmo
 * efeito). Serve ao cartão da cadeia e ao formulário do painel Áudio, sem um `if` por tipo de efeito.
 */
export function isParamShown(
  param: Pick<AudioEffectParam, 'shown_when'>,
  values: Record<string, unknown>,
  siblings: readonly AudioEffectParam[] = [],
): boolean {
  const condition = param.shown_when
  if (!condition) return true
  return Object.entries(condition).every(([field, expected]) => {
    const stored = values[field]
    const fallback = siblings.find((sibling) => sibling.name === field)?.default
    return (stored === undefined || stored === null ? fallback : stored) === expected
  })
}

/** O texto da opção escolhida, que é o que o seletor compara (`6` e `"6"` são a mesma opção). */
export function choiceText(value: AudioEffectValue | null | undefined): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

/** O valor que vai para a spec quando se escolhe uma opção: número se as opções do campo são números (o padrão é número). */
export function choiceValue(param: Pick<AudioEffectParam, 'default'>, text: string): string | number {
  return typeof param.default === 'number' ? Number(text) : text
}

/** O valor limitado à faixa do catálogo; o inteiro arredonda antes. Nunca sai valor fora da faixa para a spec. */
export function clampParam(param: Pick<AudioEffectParam, 'kind' | 'minimum' | 'maximum'>, value: number): number {
  let result = param.kind === 'integer' ? Math.round(value) : value
  if (typeof param.minimum === 'number' && result < param.minimum) result = param.minimum
  if (typeof param.maximum === 'number' && result > param.maximum) result = param.maximum
  return result
}

/** O intervalo vale quando o fim vem depois do início (a spec recusa o contrário); null quando está certo. */
export function intervalProblem(start: number | null | undefined, end: number | null | undefined): string | null {
  if (typeof start === 'number' && typeof end === 'number' && end <= start) return 'O fim precisa ser maior que o início.'
  return null
}

/* ---------- mudar a cadeia na spec ---------- */

/** O caminho de um campo do efeito na spec (`timeline.0.effects.1.gain_db`). */
export function effectPath(listPath: string, index: number, field: string): string {
  return `${listPath}.${index}.${field}`
}

/** Acrescenta o efeito ao fim da cadeia, criando a lista se o item ainda não tinha. Devolve a posição dele. */
export function addEffectIn(spec: Record<string, unknown>, listPath: string, effect: AudioEffectSettings): number {
  const list = getPath(spec, listPath)
  if (Array.isArray(list)) {
    list.push(effect)
    return list.length - 1
  }
  setPath(spec, listPath, [effect])
  return 0
}

/** Tira o efeito da cadeia. Ao esvaziar, a chave some da spec: projeto sem efeito fica igual ao de antes de existirem. */
export function removeEffectIn(spec: Record<string, unknown>, listPath: string, index: number): boolean {
  const list = getPath(spec, listPath)
  if (!Array.isArray(list) || index < 0 || index >= list.length) return false
  list.splice(index, 1)
  if (list.length === 0) setPath(spec, listPath, undefined)
  return true
}

/** Leva o efeito de `from` para `to`, empurrando os do meio. Falso quando algum dos lugares não existe ou não muda nada. */
export function moveEffectIn(spec: Record<string, unknown>, listPath: string, from: number, to: number): boolean {
  const list = getPath(spec, listPath)
  if (!Array.isArray(list) || from === to) return false
  if (from < 0 || from >= list.length || to < 0 || to >= list.length) return false
  const [moved] = list.splice(from, 1)
  list.splice(to, 0, moved)
  return true
}

/** Liga ou desliga (bypass) sem apagar o efeito. Ligar tira a chave, porque o omitido já vale ligado. */
export function setEnabledIn(spec: Record<string, unknown>, listPath: string, index: number, enabled: boolean): boolean {
  const list = getPath(spec, listPath)
  const effect = Array.isArray(list) ? (list[index] as AudioEffectSettings | undefined) : undefined
  if (!effect) return false
  if (enabled) delete effect.enabled
  else effect.enabled = false
  return true
}

/** Grava um parâmetro (ou o início e o fim do intervalo); `undefined` apaga a chave e vale o padrão do servidor. */
export function setEffectFieldIn(spec: Record<string, unknown>, listPath: string, index: number, field: string, value: unknown): boolean {
  const list = getPath(spec, listPath)
  if (!Array.isArray(list) || !list[index]) return false
  setPath(spec, effectPath(listPath, index, field), value)
  return true
}
