/* Os atalhos do editor: a tabela em uso (o padrão com as trocas da pessoa por cima), a janela de atalhos e os
   comandos que as outras telas registram (o painel Mídia registra o A e o V). As trocas ficam no navegador,
   na mesma chave e no mesmo formato da interface clássica. */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  comboIndex,
  findConflict,
  isAudioShortcut,
  KEYMAP_STORAGE_KEY,
  keyLabel,
  mergeKeymap,
  parseOverrides,
  ALL_SHORTCUTS,
  AUDIO_SHORTCUT_DEFAULTS,
  withBinding,
  type KeymapOverrides,
  type ShortcutDef,
  type ShortcutId,
} from '@/lib/keymap'
import { readStored, removeStored, writeStored } from '@/lib/storage'

export type ShortcutHandler = (event: KeyboardEvent) => void

export const useKeymapStore = defineStore('keymap', () => {
  const overrides = ref<KeymapOverrides>(parseOverrides(readStored(KEYMAP_STORAGE_KEY)))
  /** A janela de atalhos (o "?") está aberta. */
  const dialogOpen = ref(false)
  // quem registra um comando por fora (o painel Mídia) vive aqui; a cada id cabe um só, o último que chegou
  const registered = ref(new Map<ShortcutId, ShortcutHandler>())

  const entries = computed<ShortcutDef[]>(() => [
    ...mergeKeymap(overrides.value),
    ...mergeKeymap(overrides.value, AUDIO_SHORTCUT_DEFAULTS),
  ])
  // duas tabelas de teclas: a do editor e a do painel Áudio. A mesma tecla pode estar nas duas (Espaço, Ctrl+L...)
  // porque a segunda só vale com o foco dentro do painel (`idsForContext`); por isso cada uma tem o seu índice
  // e o conflito de uma troca só conta dentro da mesma tabela
  const byCombo = computed(() => comboIndex(entries.value.filter((entry) => !isAudioShortcut(entry.id))))
  const audioByCombo = computed(() => comboIndex(entries.value.filter((entry) => isAudioShortcut(entry.id))))
  /** Quantas ações têm ao menos uma tecla trocada pela pessoa. */
  const customCount = computed(() => Object.keys(overrides.value).length)

  function persist(): void {
    if (customCount.value === 0) removeStored(KEYMAP_STORAGE_KEY)
    else writeStored(KEYMAP_STORAGE_KEY, JSON.stringify(overrides.value))
  }

  /** O texto das teclas de uma ação, para os balões dos botões ("S", "X ou Del"). */
  function labelFor(id: ShortcutId): string {
    const entry = entries.value.find((candidate) => candidate.id === id)
    return entry ? keyLabel(entry.keys) : ''
  }

  /** Outra ação que já usa a combinação (a troca não é bloqueada: duas ações na mesma tecla é escolha da pessoa). */
  function conflictFor(combo: string, id: ShortcutId): ShortcutDef | null {
    const sameTable = entries.value.filter((entry) => isAudioShortcut(entry.id) === isAudioShortcut(id))
    return findConflict(sameTable, combo, id)
  }

  /** Troca a combinação principal (ou a alternativa `index`) de uma ação e guarda no navegador. */
  function setBinding(id: ShortcutId, combo: string, index = 0): void {
    overrides.value = withBinding(overrides.value, entries.value, id, index, combo)
    persist()
  }

  /** Volta tudo ao padrão. */
  function reset(): void {
    overrides.value = {}
    persist()
  }

  function isDefault(id: ShortcutId): boolean {
    return overrides.value[id] === undefined
  }

  function openDialog(): void {
    dialogOpen.value = true
  }

  /** Registra o comando de uma ação que não é do editor (o A e o V do painel Mídia); devolve como desregistrar. */
  function register(id: ShortcutId, handler: ShortcutHandler): () => void {
    registered.value = new Map(registered.value).set(id, handler)
    return () => {
      if (registered.value.get(id) !== handler) return
      const next = new Map(registered.value)
      next.delete(id)
      registered.value = next
    }
  }

  return {
    entries,
    byCombo,
    audioByCombo,
    defaults: ALL_SHORTCUTS,
    customCount,
    dialogOpen,
    registered,
    labelFor,
    conflictFor,
    setBinding,
    reset,
    isDefault,
    openDialog,
    register,
  }
})
