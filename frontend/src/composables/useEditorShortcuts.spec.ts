import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { projectSpec, timelineView } from '@/test/editorFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { useEditorStore } from '@/stores/editor'
import { useEditorPanelsStore } from '@/stores/editorPanels'
import { useKeymapStore } from '@/stores/keymap'
import { usePlayerStore, useScheduler } from '@/stores/player'
import { useTimelineStore } from '@/stores/timeline'
import { useToastsStore } from '@/stores/toasts'
import { useEditorShortcuts, useShortcutHandler } from './useEditorShortcuts'

const Host = defineComponent({
  setup() {
    useEditorShortcuts()
    return () => null
  },
})

let wrapper: VueWrapper | null = null
let opened: OpenedEditor

async function mountShortcuts() {
  const view = timelineView() // dois trechos de 3 s, 30 fps
  opened = await openEditor(projectSpec(), {
    'POST /api/projects/demo/timeline': () => view,
    'POST /api/projects/demo/edit': () => ({ spec: projectSpec(), timeline: view }),
  })
  wrapper = await mountEditorPart(Host, opened)
  return wrapper
}

/** Aperta uma tecla como o navegador: o evento nasce no elemento com o foco e sobe até a janela. */
function press(init: KeyboardEventInit, target: EventTarget = document.body): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init })
  target.dispatchEvent(event)
  return event
}

const edits = () => opened.fetch.to('POST /api/projects/demo/edit')
const toastTitles = () => useToastsStore().items.map((toast) => toast.title)

beforeEach(() => {
  window.localStorage.clear()
  // o relógio do player não anda sozinho: os testes só conferem a velocidade pedida
  useScheduler({ now: () => 0, request: () => 1, cancel: () => undefined })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  useScheduler()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('reprodução', () => {
  it('Espaço toca e pausa, e K pausa', async () => {
    await mountShortcuts()
    const player = usePlayerStore()
    expect(press({ key: ' ' }).defaultPrevented).toBe(true)
    expect(player.playing).toBe(true)
    press({ key: ' ' })
    expect(player.playing).toBe(false)
    press({ key: 'l' })
    press({ key: 'k' })
    expect(player.rate).toBe(0)
  })

  it('J, K e L voltam, param e avançam, e repetir dobra a velocidade (as mesmas teclas que o painel do player tinha)', async () => {
    await mountShortcuts()
    const player = usePlayerStore()
    press({ key: 'l' })
    expect(player.rate).toBe(1)
    press({ key: 'L' })
    expect(player.rate).toBe(2)
    press({ key: 'j' })
    expect(player.rate).toBe(-1)
    press({ key: 'k' })
    expect(player.rate).toBe(0)
  })

  it('segurar a tecla (repetição automática) não continua dobrando a velocidade', async () => {
    await mountShortcuts()
    const player = usePlayerStore()
    press({ key: 'l' })
    press({ key: 'l', repeat: true })
    press({ key: 'l', repeat: true })
    expect(player.rate).toBe(1)
  })

  it('cada tecla age uma vez só (o painel do player não tem mais ouvinte próprio)', async () => {
    await mountShortcuts()
    const player = usePlayerStore()
    press({ key: 'l' })
    press({ key: 'l' })
    // duas teclas L = 2x; com um ouvinte duplicado seriam 8x
    expect(player.rate).toBe(2)
  })
})

describe('navegação', () => {
  it('Home e End vão ao começo e ao fim; as setas andam um quadro; Page Up e Down andam um segundo', async () => {
    await mountShortcuts()
    const editor = useEditorStore()
    press({ key: 'End' })
    expect(editor.playhead).toBe(6)
    press({ key: 'Home' })
    expect(editor.playhead).toBe(0)
    press({ key: 'ArrowRight' })
    expect(editor.playhead).toBeCloseTo(1 / 30, 9)
    press({ key: 'ArrowLeft' })
    expect(editor.playhead).toBe(0)
    press({ key: 'PageDown' })
    expect(editor.playhead).toBe(1)
    press({ key: 'PageDown' })
    press({ key: 'PageUp' })
    expect(editor.playhead).toBe(1)
  })

  it('Alt e as setas pulam para a emenda anterior ou seguinte da V1', async () => {
    await mountShortcuts()
    const editor = useEditorStore()
    press({ key: 'ArrowRight', altKey: true })
    expect(editor.playhead).toBe(3)
    press({ key: 'ArrowRight', altKey: true })
    expect(editor.playhead).toBe(6)
    press({ key: 'ArrowLeft', altKey: true })
    expect(editor.playhead).toBe(3)
  })

  it('andar quadro a quadro para o vídeo que estava tocando', async () => {
    await mountShortcuts()
    const player = usePlayerStore()
    press({ key: 'l' })
    press({ key: 'ArrowRight' })
    expect(player.playing).toBe(false)
  })
})

describe('edição', () => {
  it('S corta o trecho sob o cursor, e sem trecho avisa', async () => {
    await mountShortcuts()
    useEditorStore().setPlayhead(4.5)
    press({ key: 's' })
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'split', index: 1, at: 1.5 } })
    useEditorStore().setPlayhead(3)
    press({ key: 's' })
    await flushPromises()
    expect(toastTitles()).toContain('Posicione o cursor dentro do trecho para cortar.')
  })

  it('X e Delete removem o selecionado; Z faz o lift; Ctrl+D duplica', async () => {
    await mountShortcuts()
    const editor = useEditorStore()
    editor.select(['V1:1'])
    press({ key: 'x' })
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'remove', index: 1 } })
    editor.select(['V1:0'])
    press({ key: 'Delete' })
    await flushPromises()
    expect(edits()[1]?.body).toMatchObject({ op: { type: 'remove', index: 0 } })
    editor.select(['V1:0'])
    press({ key: 'z' })
    await flushPromises()
    expect(edits()[2]?.body).toMatchObject({ op: { type: 'remove', index: 0 } })
    editor.select(['V1:0'])
    press({ key: 'd', ctrlKey: true })
    await flushPromises()
    expect(edits()[3]?.body).toMatchObject({ op: { type: 'duplicate', index: 0 } })
  })

  it('remover vários trechos manda do maior índice ao menor e vale um passo só do desfazer', async () => {
    await mountShortcuts()
    const editor = useEditorStore()
    editor.select(['V1:0', 'V1:1'])
    press({ key: 'x' })
    await flushPromises()
    expect(edits().map((call) => (call.body as { op: unknown }).op)).toEqual([
      { type: 'remove', index: 1 },
      { type: 'remove', index: 0 },
    ])
    editor.undo()
    expect(editor.canUndo).toBe(false)
  })

  it('I e O aparam a entrada e a saída até o cursor', async () => {
    await mountShortcuts()
    const editor = useEditorStore()
    editor.select(['V1:1'])
    editor.setPlayhead(4)
    press({ key: 'i' })
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'trim', index: 1, side: 'in', delta: 1 } })
    press({ key: 'o' })
    await flushPromises()
    expect(edits()[1]?.body).toMatchObject({ op: { type: 'trim', index: 1, side: 'out', delta: -2 } })
  })

  it('Ctrl+A seleciona os trechos da V1 e Esc limpa a seleção', async () => {
    await mountShortcuts()
    const editor = useEditorStore()
    press({ key: 'a', ctrlKey: true })
    expect(editor.selection).toEqual(['V1:0', 'V1:1'])
    press({ key: 'Escape' })
    expect(editor.selection).toEqual([])
  })

  it('Ctrl+Z desfaz, Ctrl+Y e Ctrl+Shift+Z refazem', async () => {
    await mountShortcuts()
    const editor = useEditorStore()
    editor.setField('output.quality', 'draft')
    press({ key: 'z', ctrlKey: true })
    expect(editor.get('output.quality')).toBe('high')
    press({ key: 'y', ctrlKey: true })
    expect(editor.get('output.quality')).toBe('draft')
    press({ key: 'z', ctrlKey: true })
    press({ key: 'Z', ctrlKey: true, shiftKey: true })
    expect(editor.get('output.quality')).toBe('draft')
  })

  it('Ctrl+L, Ctrl+M e Ctrl+H agem na trilha do item selecionado e avisam se ela não tem o controle', async () => {
    await mountShortcuts()
    const editor = useEditorStore()
    editor.select(['V1:0'])
    press({ key: 'l', ctrlKey: true })
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'set_field', path: 'tracks.V1.locked', value: true } })
    press({ key: 'm', ctrlKey: true })
    press({ key: 'h', ctrlKey: true })
    await flushPromises()
    expect(edits()).toHaveLength(1)
    expect(toastTitles().filter((title) => title === 'A trilha V1 não tem esse controle.')).toHaveLength(2)
  })

  it('sem item selecionado, a trilha é a que está sob o mouse', async () => {
    await mountShortcuts()
    useTimelineStore().hoverTrackId = 'V1'
    press({ key: 'l', ctrlKey: true })
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { path: 'tracks.V1.locked' } })
    useTimelineStore().hoverTrackId = null
    press({ key: 'l', ctrlKey: true })
    await flushPromises()
    expect(toastTitles()).toContain('Selecione um item ou passe o mouse sobre uma trilha.')
  })
})

describe('visualização e geral', () => {
  it('= e - dão zoom, 0 ajusta, Ctrl+P liga e desliga o encaixe, Ctrl+R o rótulo de ripple', async () => {
    await mountShortcuts()
    const timeline = useTimelineStore()
    press({ key: '=' })
    expect(timeline.pxPerSec).toBeCloseTo(78, 9)
    press({ key: '-' })
    expect(timeline.pxPerSec).toBeCloseTo(60, 9)
    press({ key: '0' })
    expect(timeline.pxPerSec).not.toBe(60)
    expect(press({ key: 'p', ctrlKey: true }).defaultPrevented).toBe(true)
    expect(timeline.snapEnabled).toBe(false)
    press({ key: 'r', ctrlKey: true })
    expect(timeline.rippleAlways).toBe(true)
  })

  it('Ctrl+S salva o projeto, sem a página do navegador salvar a si mesma', async () => {
    await mountShortcuts()
    useEditorStore().setField('output.quality', 'draft')
    expect(press({ key: 's', ctrlKey: true }).defaultPrevented).toBe(true)
    await flushPromises()
    expect(opened.fetch.to('PUT /api/projects/demo')).toHaveLength(1)
  })

  it('o Ctrl+S salva até com o foco num campo de texto', async () => {
    await mountShortcuts()
    useEditorStore().setField('output.quality', 'draft')
    const field = document.createElement('textarea')
    document.body.appendChild(field)
    press({ key: 's', ctrlKey: true }, field)
    await flushPromises()
    expect(opened.fetch.to('PUT /api/projects/demo')).toHaveLength(1)
  })

  it('a tecla ? abre a janela de atalhos', async () => {
    await mountShortcuts()
    press({ key: '?', shiftKey: true })
    expect(useKeymapStore().dialogOpen).toBe(true)
  })
})

describe('quando as teclas não valem', () => {
  it('num campo de texto nenhum atalho age (digitar um L não toca o vídeo)', async () => {
    await mountShortcuts()
    const field = document.createElement('input')
    document.body.appendChild(field)
    const event = press({ key: 'l' }, field)
    expect(event.defaultPrevented).toBe(false)
    expect(usePlayerStore().rate).toBe(0)
    // o Ctrl+Z num campo é do campo (desfazer o texto), não da spec
    useEditorStore().setField('output.quality', 'draft')
    press({ key: 'z', ctrlKey: true }, field)
    expect(useEditorStore().get('output.quality')).toBe('draft')
  })

  it('dentro de uma janela, as teclas são da janela', async () => {
    await mountShortcuts()
    const dialog = document.createElement('div')
    dialog.setAttribute('role', 'dialog')
    const inner = document.createElement('button')
    dialog.appendChild(inner)
    document.body.appendChild(dialog)
    press({ key: 'l' }, inner)
    expect(usePlayerStore().rate).toBe(0)
  })

  it('o Espaço num botão aperta o botão em vez de tocar o vídeo', async () => {
    await mountShortcuts()
    const button = document.createElement('button')
    document.body.appendChild(button)
    expect(press({ key: ' ' }, button).defaultPrevented).toBe(false)
    expect(usePlayerStore().playing).toBe(false)
  })

  it('tecla sem atalho passa em branco, e evento já tratado por outro é respeitado', async () => {
    await mountShortcuts()
    expect(press({ key: 'F9' }).defaultPrevented).toBe(false)
    const handled = new KeyboardEvent('keydown', { key: 'l', bubbles: true, cancelable: true })
    handled.preventDefault()
    document.body.dispatchEvent(handled)
    expect(usePlayerStore().rate).toBe(0)
  })

  it('só um modificador, ou a composição de um acento, não dispara nada', async () => {
    await mountShortcuts()
    press({ key: 'Control', ctrlKey: true })
    press({ key: 'l', isComposing: true })
    expect(usePlayerStore().rate).toBe(0)
  })

  it('sem projeto pronto (aberto sem ser aberto, ou com erro), o teclado fica quieto', async () => {
    await mountShortcuts()
    useEditorStore().close()
    expect(press({ key: ' ' }).defaultPrevented).toBe(false)
    expect(usePlayerStore().playing).toBe(false)
  })

  it('ao sair da tela os ouvintes saem junto', async () => {
    await mountShortcuts()
    wrapper?.unmount()
    wrapper = null
    expect(press({ key: 'l' }).defaultPrevented).toBe(false)
    expect(usePlayerStore().rate).toBe(0)
  })
})

describe('teclas trocadas e comandos de fora', () => {
  it('a tecla nova vale na hora e a antiga deixa de valer', async () => {
    await mountShortcuts()
    useKeymapStore().setBinding('split', 'b')
    useEditorStore().setPlayhead(4.5)
    press({ key: 's' })
    await flushPromises()
    expect(edits()).toHaveLength(0)
    press({ key: 'b' })
    await flushPromises()
    expect(edits()).toHaveLength(1)
  })

  it('o A e o V, sem o painel Mídia, pedem um arquivo no painel de mídia', async () => {
    await mountShortcuts()
    press({ key: 'a' })
    press({ key: 'v' })
    expect(toastTitles().filter((title) => title === 'Selecione um arquivo no painel de mídia.')).toHaveLength(2)
  })

  it('com o painel Mídia oculto (botão M), o aviso do A e do V diz para mostrá-lo', async () => {
    await mountShortcuts()
    useEditorPanelsStore().setHidden('media', true)
    press({ key: 'a' })
    expect(toastTitles()).toContain('O painel Mídia está oculto: mostre-o com o botão M e selecione um arquivo.')
    expect(toastTitles()).not.toContain('Selecione um arquivo no painel de mídia.')
  })

  it('o painel Mídia registra o comando e ele vale no lugar do aviso, até o painel sair', async () => {
    await mountShortcuts()
    const run = vi.fn()
    const Media = defineComponent({
      setup() {
        useShortcutHandler('media_append', run)
        return () => null
      },
    })
    const media = await mountEditorPart(Media, opened)
    const event = press({ key: 'a' })
    expect(run).toHaveBeenCalledTimes(1)
    expect(event.defaultPrevented).toBe(true)
    expect(toastTitles()).not.toContain('Selecione um arquivo no painel de mídia.')
    media.unmount()
    press({ key: 'a' })
    expect(run).toHaveBeenCalledTimes(1)
    expect(toastTitles()).toContain('Selecione um arquivo no painel de mídia.')
  })
})

describe('sair da página com mudança não salva', () => {
  it('o aviso do navegador só vale com mudança não salva', async () => {
    await mountShortcuts()
    const clean = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(clean)
    expect(clean.defaultPrevented).toBe(false)
    useEditorStore().setField('output.quality', 'draft')
    const dirty = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(dirty)
    expect(dirty.defaultPrevented).toBe(true)
  })
})
