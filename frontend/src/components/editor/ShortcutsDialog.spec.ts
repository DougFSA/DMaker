import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { KEYMAP_STORAGE_KEY } from '@/lib/keymap'
import { useKeymapStore } from '@/stores/keymap'
import ShortcutsDialog from './ShortcutsDialog.vue'

let wrapper: VueWrapper | null = null

beforeEach(() => {
  window.localStorage.clear()
  setActivePinia(createPinia())
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

async function openDialog() {
  const keymap = useKeymapStore()
  wrapper = mount(ShortcutsDialog, { attachTo: document.body })
  keymap.openDialog()
  await flushPromises()
  return keymap
}

const keyButton = (id: string) => document.body.querySelector<HTMLButtonElement>(`[data-shortcut="${id}"]`)
const footerButton = (label: string) =>
  Array.from(document.body.querySelectorAll<HTMLButtonElement>('button')).find((node) => node.textContent?.trim() === label)

/** Aperta uma tecla na janela, como o navegador faz; devolve se alguém a deixou passar (não impediu o padrão). */
function press(init: KeyboardEventInit): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init })
  window.dispatchEvent(event)
  return event
}

describe('a janela de atalhos', () => {
  it('só aparece depois de aberta, com o título e a explicação', async () => {
    const keymap = useKeymapStore()
    wrapper = mount(ShortcutsDialog, { attachTo: document.body })
    await flushPromises()
    expect(document.body.querySelector('[role="dialog"]')).toBeNull()
    keymap.openDialog()
    await flushPromises()
    const dialog = document.body.querySelector('[role="dialog"]')
    expect(dialog?.textContent).toContain('Atalhos de teclado')
    expect(dialog?.textContent).toContain('Clique numa tecla para trocá-la')
  })

  it('lista os 34 atalhos em seis categorias, cada um com a tecla', async () => {
    await openDialog()
    expect(document.body.querySelectorAll('[data-shortcut]')).toHaveLength(34)
    const titles = Array.from(document.body.querySelectorAll('h3')).map((heading) => heading.textContent)
    expect(titles).toEqual(['Reprodução', 'Navegação', 'Edição', 'Mídia', 'Visualização', 'Geral'])
    expect(keyButton('play_pause')?.textContent?.trim()).toBe('Espaço')
    expect(keyButton('remove_ripple')?.textContent?.trim()).toBe('X ou Del')
    expect(keyButton('redo')?.textContent?.trim()).toBe('Ctrl + Y ou Ctrl + Shift + Z')
  })

  it('o texto da janela não usa travessão (regra da marca)', async () => {
    await openDialog()
    expect(document.body.querySelector('[role="dialog"]')?.textContent).not.toMatch(/[—–]/)
  })
})

describe('trocar uma tecla', () => {
  it('clicar numa tecla espera a próxima; a combinação apertada vira o atalho e fica guardada', async () => {
    const keymap = await openDialog()
    keyButton('split')?.click()
    await flushPromises()
    expect(keyButton('split')?.textContent?.trim()).toBe('Pressione uma tecla...')
    const event = press({ key: 'b' })
    await flushPromises()
    expect(event.defaultPrevented).toBe(true)
    expect(keyButton('split')?.textContent?.trim()).toBe('B')
    expect(keymap.byCombo.get('b')).toEqual(['split'])
    expect(JSON.parse(window.localStorage.getItem(KEYMAP_STORAGE_KEY) ?? '{}')).toEqual({ split: ['b'] })
  })

  it('a tecla da captura não chega aos outros ouvintes (não aciona nada)', async () => {
    await openDialog()
    const other = vi.fn()
    window.addEventListener('keydown', other)
    keyButton('split')?.click()
    await flushPromises()
    press({ key: 'k' })
    expect(other).not.toHaveBeenCalled()
    // fora da captura a tecla passa normalmente
    press({ key: 'k' })
    expect(other).toHaveBeenCalledTimes(1)
    window.removeEventListener('keydown', other)
  })

  it('combinações com Ctrl e Shift são capturadas inteiras', async () => {
    const keymap = await openDialog()
    keyButton('undo')?.click()
    await flushPromises()
    press({ key: 'Z', ctrlKey: true, shiftKey: true })
    await flushPromises()
    expect(keymap.byCombo.get('Ctrl+Shift+z')).toContain('undo')
  })

  it('segurar só um modificador ainda é montar a combinação', async () => {
    const keymap = await openDialog()
    keyButton('undo')?.click()
    await flushPromises()
    press({ key: 'Control', ctrlKey: true })
    expect(keyButton('undo')?.textContent?.trim()).toBe('Pressione uma tecla...')
    press({ key: 'u', ctrlKey: true })
    await flushPromises()
    expect(keymap.byCombo.get('Ctrl+u')).toEqual(['undo'])
  })

  it('o Esc cancela a captura sem trocar nada e sem fechar a janela', async () => {
    const keymap = await openDialog()
    keyButton('split')?.click()
    await flushPromises()
    press({ key: 'Escape' })
    await flushPromises()
    expect(keymap.byCombo.get('s')).toEqual(['split'])
    expect(keymap.dialogOpen).toBe(true)
    expect(keyButton('split')?.textContent?.trim()).toBe('S')
  })

  it('trocar para a tecla de outro atalho avisa, mas deixa trocar: os dois passam a usá-la', async () => {
    const keymap = await openDialog()
    keyButton('split')?.click()
    await flushPromises()
    press({ key: 'k' })
    await flushPromises()
    const notice = document.body.querySelector('[role="status"]')?.textContent ?? ''
    expect(notice).toContain('“K” já era o atalho de “Pausar”')
    expect(notice).toContain('Agora os dois usam essa tecla')
    expect(keymap.byCombo.get('k')).toEqual(['pause', 'split'])
  })

  it('escolher a mesma tecla de antes não gera aviso', async () => {
    await openDialog()
    keyButton('split')?.click()
    await flushPromises()
    press({ key: 's' })
    await flushPromises()
    expect(document.body.querySelector('[role="status"]')).toBeNull()
  })
})

describe('restaurar padrões', () => {
  it('fica desligado enquanto nada foi trocado e, ao trocar, volta tudo ao padrão', async () => {
    const keymap = await openDialog()
    expect(footerButton('Restaurar padrões')?.disabled).toBe(true)
    keymap.setBinding('split', 'b')
    await flushPromises()
    expect(footerButton('Restaurar padrões')?.disabled).toBe(false)
    footerButton('Restaurar padrões')?.click()
    await flushPromises()
    expect(keymap.byCombo.get('s')).toEqual(['split'])
    expect(keyButton('split')?.textContent?.trim()).toBe('S')
    expect(window.localStorage.getItem(KEYMAP_STORAGE_KEY)).toBeNull()
  })

  it('o botão Fechar fecha a janela, e fechar no meio da captura a cancela', async () => {
    const keymap = await openDialog()
    keyButton('split')?.click()
    await flushPromises()
    footerButton('Fechar')?.click()
    await flushPromises()
    expect(keymap.dialogOpen).toBe(false)
    // sem a captura, apertar uma tecla não troca nada
    press({ key: 'b' })
    expect(keymap.byCombo.get('s')).toEqual(['split'])
  })
})
