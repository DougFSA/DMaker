import { flushPromises, mount, RouterLinkStub, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ImportScriptDialog from './ImportScriptDialog.vue'

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

async function mountDialog(props: { open?: boolean; busy?: boolean; narratedWith?: string } = {}) {
  wrapper = mount(ImportScriptDialog, {
    props: { open: true, busy: false, narratedWith: 'Dora (feminina) · Português · velocidade 1,00x', ...props },
    global: { stubs: { RouterLink: RouterLinkStub } },
    attachTo: document.body,
  })
  // o diálogo se desenha no portal um instante depois de montar
  await flushPromises()
  return wrapper
}

/** O diálogo mora num portal fora do componente. */
const dialog = () => document.body.querySelector('[role="dialog"]') as HTMLElement
const button = (label: string) =>
  [...dialog().querySelectorAll('button')].find((node) => node.textContent?.trim() === label) as HTMLButtonElement

function script(name = 'curso.docx', size = 12): File {
  return new File(['x'.repeat(size)], name, { lastModified: 1 })
}

/** O jsdom não deixa atribuir `files` ao input; define a propriedade como o navegador faria ao escolher. */
async function pick(files: File[]) {
  const input = dialog().querySelector('input[type="file"]') as HTMLInputElement
  Object.defineProperty(input, 'files', { value: files, configurable: true })
  input.dispatchEvent(new Event('change'))
  await flushPromises()
}

const submit = () => (dialog().querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit', { cancelable: true }))

describe('ImportScriptDialog', () => {
  it('explica o que a fila faz e com que voz o roteiro será narrado', async () => {
    await mountDialog()
    expect(dialog().textContent).toContain('dividido em capítulos pelos títulos')
    expect(dialog().textContent).toContain('Narra com: Dora (feminina) · Português · velocidade 1,00x.')
  })

  it('o link leva à Narração, onde a voz se muda', async () => {
    await mountDialog()
    const link = wrapper!.findComponent(RouterLinkStub)
    expect(link.props('to')).toBe('/voz/narracao')
  })

  it('o seletor aceita só .txt, .md e .docx', async () => {
    await mountDialog()
    expect(dialog().querySelector('input[type="file"]')?.getAttribute('accept')).toBe('.txt,.md,.docx')
  })

  it('sem arquivo, o botão de mandar fica parado', async () => {
    await mountDialog()
    expect(button('Mandar para a fila').getAttribute('disabled')).not.toBeNull()
  })

  it('com o arquivo escolhido, manda com o formato WAV e sem rascunho, a menos que a pessoa mude', async () => {
    const mounted = await mountDialog()
    const roteiro = script()
    await pick([roteiro])
    expect(button('Mandar para a fila').getAttribute('disabled')).toBeNull()
    submit()
    expect(mounted.emitted('send')).toEqual([[roteiro, { title: '', format: 'wav', draft: false }]])
  })

  it('manda o título, o formato e o rascunho escolhidos', async () => {
    const mounted = await mountDialog()
    const roteiro = script('manual.md')
    await pick([roteiro])
    const title = dialog().querySelector('input[type="text"]') as HTMLInputElement
    title.value = 'Manual do usuário'
    title.dispatchEvent(new Event('input'))
    button('MP3').click()
    ;(dialog().querySelector('input[type="checkbox"]') as HTMLInputElement).click()
    await mounted.vm.$nextTick()
    submit()
    expect(mounted.emitted('send')).toEqual([[roteiro, { title: 'Manual do usuário', format: 'mp3', draft: true }]])
  })

  it('recusa um arquivo de outro tipo e não deixa mandar', async () => {
    const mounted = await mountDialog()
    await pick([script('capa.png')])
    expect(dialog().textContent).toContain('Não aceitei capa.png')
    expect(button('Mandar para a fila').getAttribute('disabled')).not.toBeNull()
    submit()
    expect(mounted.emitted('send')).toBeUndefined()
  })

  it('Cancelar fecha o diálogo sem mandar', async () => {
    const mounted = await mountDialog()
    await pick([script()])
    button('Cancelar').click()
    await mounted.vm.$nextTick()
    expect(mounted.emitted('update:open')).toEqual([[false]])
    expect(mounted.emitted('send')).toBeUndefined()
  })

  it('o arquivo e o título de um roteiro não passam para o seguinte', async () => {
    const mounted = await mountDialog()
    await pick([script('primeiro.txt')])
    const title = dialog().querySelector('input[type="text"]') as HTMLInputElement
    title.value = 'Primeiro'
    title.dispatchEvent(new Event('input'))
    await mounted.setProps({ open: false })
    await mounted.setProps({ open: true })
    await flushPromises()
    expect(dialog().textContent).not.toContain('primeiro.txt')
    expect((dialog().querySelector('input[type="text"]') as HTMLInputElement).value).toBe('')
    expect(button('Mandar para a fila').getAttribute('disabled')).not.toBeNull()
  })

  it('enquanto envia, o botão fica em andamento', async () => {
    await mountDialog({ busy: true })
    expect(button('Mandar para a fila').getAttribute('disabled')).not.toBeNull()
    expect(button('Mandar para a fila').getAttribute('aria-busy')).toBe('true')
  })

  it('fechado, não mostra nada', async () => {
    await mountDialog({ open: false })
    expect(document.body.querySelector('[role="dialog"]')).toBeNull()
  })
})
