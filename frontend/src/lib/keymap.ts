/* A tabela de atalhos do editor (o padrão é o de ilhas de edição como o Shotcut): os 34 atalhos, a combinação de
   teclas que cada evento representa, as trocas que a pessoa salvou e quando o teclado deve ficar quieto. Tudo puro,
   sem tocar no navegador; quem escuta o teclado é `useEditorShortcuts`. */

export type ShortcutCategory = 'reproducao' | 'navegacao' | 'edicao' | 'midia' | 'visualizacao' | 'geral'

export type ShortcutId =
  | 'play_pause'
  | 'pause'
  | 'play_reverse'
  | 'play_forward'
  | 'step_back'
  | 'step_forward'
  | 'prev_edit'
  | 'next_edit'
  | 'go_start'
  | 'go_end'
  | 'back_1s'
  | 'forward_1s'
  | 'split'
  | 'remove_ripple'
  | 'lift'
  | 'trim_in'
  | 'trim_out'
  | 'undo'
  | 'redo'
  | 'save'
  | 'duplicate'
  | 'select_all'
  | 'zoom_in'
  | 'zoom_out'
  | 'zoom_fit'
  | 'toggle_snap'
  | 'toggle_ripple'
  | 'clear_selection'
  | 'show_shortcuts'
  | 'media_append'
  | 'media_insert'
  | 'track_mute'
  | 'track_hide'
  | 'track_lock'

export interface ShortcutDef {
  id: ShortcutId
  label: string
  /** As combinações que disparam a ação ("Ctrl+Shift+z"); a primeira é a principal. */
  keys: string[]
  category: ShortcutCategory
}

export const SHORTCUT_CATEGORIES: Array<{ id: ShortcutCategory; label: string }> = [
  { id: 'reproducao', label: 'Reprodução' },
  { id: 'navegacao', label: 'Navegação' },
  { id: 'edicao', label: 'Edição' },
  { id: 'midia', label: 'Mídia' },
  { id: 'visualizacao', label: 'Visualização' },
  { id: 'geral', label: 'Geral' },
]

/** O padrão. A ordem aqui é a ordem em que a janela de atalhos lista cada categoria. */
export const SHORTCUT_DEFAULTS: readonly ShortcutDef[] = [
  { id: 'play_pause', label: 'Reproduzir ou pausar', keys: ['Space'], category: 'reproducao' },
  { id: 'pause', label: 'Pausar', keys: ['k'], category: 'reproducao' },
  { id: 'play_reverse', label: 'Retroceder (repetir acelera 2x, 4x, 8x)', keys: ['j'], category: 'reproducao' },
  { id: 'play_forward', label: 'Avançar (repetir acelera 2x, 4x, 8x)', keys: ['l'], category: 'reproducao' },
  { id: 'step_back', label: 'Um quadro para trás', keys: ['ArrowLeft'], category: 'navegacao' },
  { id: 'step_forward', label: 'Um quadro para frente', keys: ['ArrowRight'], category: 'navegacao' },
  { id: 'prev_edit', label: 'Edição anterior', keys: ['Alt+ArrowLeft'], category: 'navegacao' },
  { id: 'next_edit', label: 'Próxima edição', keys: ['Alt+ArrowRight'], category: 'navegacao' },
  { id: 'go_start', label: 'Ir ao início', keys: ['Home'], category: 'navegacao' },
  { id: 'go_end', label: 'Ir ao fim', keys: ['End'], category: 'navegacao' },
  { id: 'back_1s', label: 'Voltar 1 segundo', keys: ['PageUp'], category: 'navegacao' },
  { id: 'forward_1s', label: 'Avançar 1 segundo', keys: ['PageDown'], category: 'navegacao' },
  { id: 'split', label: 'Cortar no cursor', keys: ['s'], category: 'edicao' },
  { id: 'remove_ripple', label: 'Remover (ripple)', keys: ['x', 'Delete'], category: 'edicao' },
  { id: 'lift', label: 'Lift (remover sem deixar lacuna na V1)', keys: ['z'], category: 'edicao' },
  { id: 'trim_in', label: 'Aparar entrada até o cursor', keys: ['i'], category: 'edicao' },
  { id: 'trim_out', label: 'Aparar saída até o cursor', keys: ['o'], category: 'edicao' },
  { id: 'undo', label: 'Desfazer', keys: ['Ctrl+z'], category: 'geral' },
  { id: 'redo', label: 'Refazer', keys: ['Ctrl+y', 'Ctrl+Shift+z'], category: 'geral' },
  { id: 'save', label: 'Salvar', keys: ['Ctrl+s'], category: 'geral' },
  { id: 'duplicate', label: 'Duplicar', keys: ['Ctrl+d'], category: 'edicao' },
  { id: 'select_all', label: 'Selecionar tudo', keys: ['Ctrl+a'], category: 'edicao' },
  { id: 'zoom_in', label: 'Aproximar', keys: ['='], category: 'visualizacao' },
  { id: 'zoom_out', label: 'Afastar', keys: ['-'], category: 'visualizacao' },
  { id: 'zoom_fit', label: 'Ajustar à janela', keys: ['0'], category: 'visualizacao' },
  { id: 'toggle_snap', label: 'Alternar encaixe (snap)', keys: ['Ctrl+p'], category: 'visualizacao' },
  { id: 'toggle_ripple', label: 'Alternar rótulo de ripple', keys: ['Ctrl+r'], category: 'edicao' },
  { id: 'clear_selection', label: 'Limpar seleção', keys: ['Escape'], category: 'geral' },
  { id: 'show_shortcuts', label: 'Mostrar atalhos', keys: ['?'], category: 'geral' },
  { id: 'media_append', label: 'Acrescentar a mídia selecionada no fim da V1', keys: ['a'], category: 'midia' },
  { id: 'media_insert', label: 'Inserir a mídia selecionada no cursor', keys: ['v'], category: 'midia' },
  { id: 'track_mute', label: 'Mudo na trilha atual', keys: ['Ctrl+m'], category: 'edicao' },
  { id: 'track_hide', label: 'Ocultar a trilha atual', keys: ['Ctrl+h'], category: 'edicao' },
  { id: 'track_lock', label: 'Bloquear a trilha atual', keys: ['Ctrl+l'], category: 'edicao' },
]

/** A chave do navegador onde as trocas ficam: a mesma da interface clássica, no mesmo formato (id para combinações). */
export const KEYMAP_STORAGE_KEY = 'dmaker.keymap'

export type KeymapOverrides = Partial<Record<ShortcutId, string[]>>

const MODIFIER_KEYS = new Set(['Control', 'Alt', 'Shift', 'Meta', 'AltGraph', 'CapsLock'])

/** A tecla é só um modificador (a pessoa ainda está montando a combinação). */
export function isModifierKey(key: string): boolean {
  return MODIFIER_KEYS.has(key)
}

/**
 * A combinação canônica de um evento de teclado ("Ctrl+Alt+Shift+tecla"), na mesma forma da tabela, para as duas
 * sempre coincidirem. Cmd no Mac vale como Ctrl. O Shift só entra com letras e teclas de nome (setas, Home...):
 * num caractere como "?" ou "+" ele já está no próprio caractere, e contá-lo de novo impediria o "?" de casar.
 */
export function comboFromEvent(event: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey'>): string {
  let key = event.key === ' ' ? 'Space' : event.key
  if (key.length === 1) key = key.toLowerCase()
  const parts: string[] = []
  if (event.ctrlKey || event.metaKey) parts.push('Ctrl')
  if (event.altKey) parts.push('Alt')
  const carriesShift = key.length === 1 && key.toUpperCase() === key.toLowerCase()
  if (event.shiftKey && !carriesShift) parts.push('Shift')
  parts.push(key)
  return parts.join('+')
}

/** A tabela padrão com as trocas salvas por cima (uma combinação por posição: a principal e as alternativas). */
export function mergeKeymap(overrides: KeymapOverrides): ShortcutDef[] {
  return SHORTCUT_DEFAULTS.map((entry) => {
    const custom = overrides[entry.id]
    return { ...entry, keys: Array.isArray(custom) && custom.length > 0 ? [...custom] : [...entry.keys] }
  })
}

/** Lê o que foi salvo no navegador; texto quebrado ou de outro formato vira "nenhuma troca". */
export function parseOverrides(raw: string | null): KeymapOverrides {
  if (!raw) return {}
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const known = new Set<string>(SHORTCUT_DEFAULTS.map((entry) => entry.id))
    const clean: KeymapOverrides = {}
    for (const [id, keys] of Object.entries(parsed)) {
      if (!known.has(id) || !Array.isArray(keys)) continue
      const combos = keys.filter((combo): combo is string => typeof combo === 'string' && combo !== '')
      if (combos.length > 0) clean[id as ShortcutId] = combos
    }
    return clean
  } catch {
    return {}
  }
}

/** O índice combinação para ações (uma tecla pode servir a mais de uma ação, se a pessoa assim quis). */
export function comboIndex(entries: readonly ShortcutDef[]): Map<string, ShortcutId[]> {
  const index = new Map<string, ShortcutId[]>()
  for (const entry of entries) {
    for (const combo of entry.keys) {
      const ids = index.get(combo)
      if (ids) ids.push(entry.id)
      else index.set(combo, [entry.id])
    }
  }
  return index
}

/** Outro atalho que já usa esta combinação (para avisar ao trocar); o próprio atalho em edição não conta. */
export function findConflict(entries: readonly ShortcutDef[], combo: string, exceptId: ShortcutId): ShortcutDef | null {
  return entries.find((entry) => entry.id !== exceptId && entry.keys.includes(combo)) ?? null
}

/** Troca a combinação da posição `index` (0 é a principal) do atalho `id`; devolve as trocas novas, sem mexer nas antigas. */
export function withBinding(
  overrides: KeymapOverrides,
  entries: readonly ShortcutDef[],
  id: ShortcutId,
  index: number,
  combo: string,
): KeymapOverrides {
  const entry = entries.find((candidate) => candidate.id === id)
  if (!entry) return overrides
  const keys = [...entry.keys]
  keys[index] = combo
  return { ...overrides, [id]: keys }
}

const KEY_NAMES: Record<string, string> = {
  Space: 'Espaço',
  ArrowLeft: '←',
  ArrowRight: '→',
  ArrowUp: '↑',
  ArrowDown: '↓',
  Escape: 'Esc',
  Delete: 'Del',
  PageUp: 'Page Up',
  PageDown: 'Page Down',
}

/** O texto de uma combinação para a tela: "Ctrl+Shift+z" vira "Ctrl + Shift + Z"; as teclas de nome ganham o nome em português. */
export function comboLabel(combo: string): string {
  return combo
    .split('+')
    .map((part) => KEY_NAMES[part] ?? (part.length === 1 ? part.toUpperCase() : part))
    .join(' + ')
}

/** O texto de uma lista de combinações: "X ou Del". */
export function keyLabel(keys: readonly string[]): string {
  return keys.map(comboLabel).join(' ou ')
}

/* ---------- quando o teclado fica quieto ---------- */

const TYPING_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT'])
/** Dentro destes o teclado é do componente (diálogo, menu, lista, controle deslizante): o editor não atravessa. */
const OWNS_KEYBOARD =
  '[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"], [role="slider"], [role="combobox"], [role="tablist"], [role="radiogroup"]'
/** Nestes, Espaço e Enter ativam o próprio controle em vez de tocar o vídeo. */
const ACTIVATES_ON_SPACE = 'button, a[href], summary, [role="button"], [role="tab"], [role="switch"], [role="checkbox"], [role="menuitem"]'

/** O foco está num campo onde as teclas viram texto. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return TYPING_TAGS.has(target.tagName) || target.isContentEditable === true
}

/**
 * O editor deve deixar a tecla passar? Sim quando o foco está num diálogo, menu, lista ou controle deslizante (que
 * usam o teclado), quando a pessoa está digitando (a menos que a ação valha mesmo digitando, como o Ctrl+S) e,
 * para o Espaço, quando o foco está num botão (o Espaço o aperta).
 */
export function keyBelongsToTarget(target: EventTarget | null, combo: string, worksWhileTyping = false): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.closest(OWNS_KEYBOARD)) return true
  if (isTypingTarget(target)) return !worksWhileTyping
  return combo === 'Space' && target.closest(ACTIVATES_ON_SPACE) !== null
}

/** As ações que funcionam mesmo com o foco num campo de texto: salvar não pode esperar a pessoa sair do campo. */
export const WORKS_WHILE_TYPING: ReadonlySet<ShortcutId> = new Set<ShortcutId>(['save'])
