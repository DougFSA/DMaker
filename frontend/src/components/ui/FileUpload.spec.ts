import { mount, type VueWrapper } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import FileUpload from './FileUpload.vue'

function file(name: string, type = '', size = 5): File {
  return new File(['x'.repeat(size)], name, { type, lastModified: 1 })
}

/** O jsdom não deixa atribuir `files` ao input; define a propriedade como o navegador faria ao escolher. */
async function pick(wrapper: VueWrapper, files: File[]) {
  const input = wrapper.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: files, configurable: true })
  await input.trigger('change')
}

async function drop(wrapper: VueWrapper, files: File[]) {
  await wrapper.find('.upload__zone').trigger('drop', { dataTransfer: { files } })
}

let wrapper: VueWrapper

/** O v-model é do pai: aqui o próprio teste devolve o valor novo ao componente. */
function mountUpload(props: Record<string, unknown> = {}): VueWrapper {
  return mount(FileUpload, {
    props: {
      label: 'Roteiro',
      modelValue: [],
      'onUpdate:modelValue': (value: File[]) => wrapper.setProps({ modelValue: value }),
      ...props,
    },
  })
}

describe('FileUpload', () => {
  it('a área tem o nome do campo e o input respeita o filtro e a quantidade', () => {
    wrapper = mountUpload({ accept: '.txt,.md', multiple: true })
    expect(wrapper.find('[role="group"]').attributes('aria-labelledby')).toBe(wrapper.find('.field-label').attributes('id'))
    const input = wrapper.find('input[type="file"]')
    expect(input.attributes('accept')).toBe('.txt,.md')
    expect(input.attributes('multiple')).toBeDefined()
    expect(wrapper.find('button').text()).toBe('Escolher arquivos')
  })

  it('o botão abre o seletor de arquivos', async () => {
    wrapper = mountUpload()
    let opened = 0
    wrapper.find('input[type="file"]').element.addEventListener('click', () => (opened += 1))
    await wrapper.find('button').trigger('click')
    expect(opened).toBe(1)
  })

  it('escolher um arquivo avisa a seleção e mostra o nome e o tamanho', async () => {
    wrapper = mountUpload()
    const chosen = file('livro.txt', 'text/plain', 2048)
    await pick(wrapper, [chosen])
    expect(wrapper.emitted('select')).toEqual([[[chosen]]])
    expect(wrapper.find('.upload__name').text()).toBe('livro.txt')
    expect(wrapper.find('.upload__size').text()).toBe('2 KB')
  })

  it('arrastar e soltar funciona como escolher', async () => {
    wrapper = mountUpload()
    const dropped = file('voz.wav', 'audio/wav')
    await drop(wrapper, [dropped])
    expect(wrapper.emitted('select')).toEqual([[[dropped]]])
  })

  it('o destaque de arrastar liga ao entrar e some ao sair ou soltar', async () => {
    wrapper = mountUpload()
    const zone = wrapper.find('.upload__zone')
    await zone.trigger('dragenter')
    expect(zone.classes()).toContain('is-dragging')
    await zone.trigger('dragleave')
    expect(zone.classes()).not.toContain('is-dragging')
    await zone.trigger('dragover')
    await drop(wrapper, [])
    expect(zone.classes()).not.toContain('is-dragging')
  })

  it('um arquivo só: o novo troca o anterior', async () => {
    wrapper = mountUpload()
    await pick(wrapper, [file('a.txt')])
    await pick(wrapper, [file('b.txt')])
    expect(wrapper.findAll('.upload__name').map((node) => node.text())).toEqual(['b.txt'])
  })

  it('vários: soma os novos sem repetir e deixa remover um', async () => {
    wrapper = mountUpload({ multiple: true })
    await pick(wrapper, [file('a.txt'), file('b.txt')])
    await pick(wrapper, [file('b.txt'), file('c.txt')])
    expect(wrapper.findAll('.upload__name').map((node) => node.text())).toEqual(['a.txt', 'b.txt', 'c.txt'])
    await wrapper.find('button[aria-label="Remover b.txt"]').trigger('click')
    expect(wrapper.findAll('.upload__name').map((node) => node.text())).toEqual(['a.txt', 'c.txt'])
  })

  it('recusa o tipo fora do filtro, mesmo arrastado, e diz quais são aceitos', async () => {
    wrapper = mountUpload({ accept: '.txt,.md' })
    const wrong = file('planilha.pdf', 'application/pdf')
    await drop(wrapper, [wrong])
    expect(wrapper.emitted('select')).toBeUndefined()
    expect(wrapper.emitted('reject')).toEqual([[[wrong]]])
    const alert = wrapper.find('[role="alert"]')
    expect(alert.text()).toContain('planilha.pdf')
    expect(alert.text()).toContain('.txt,.md')
  })

  it('aceita o que passa no filtro e recusa o resto na mesma soltura', async () => {
    wrapper = mountUpload({ accept: '.txt', multiple: true })
    const good = file('a.txt')
    await drop(wrapper, [good, file('b.pdf')])
    expect(wrapper.emitted('select')).toEqual([[[good]]])
    expect(wrapper.find('[role="alert"]').text()).toContain('b.pdf')
  })

  it('recusa o arquivo maior que o limite', async () => {
    wrapper = mountUpload({ maxBytes: 100 })
    await pick(wrapper, [file('grande.wav', 'audio/wav', 500)])
    expect(wrapper.emitted('select')).toBeUndefined()
    expect(wrapper.find('[role="alert"]').text()).toContain('grande.wav')
    expect(wrapper.find('[role="alert"]').text()).toContain('100 B')
  })

  it('ocupada ou desabilitada, não recebe arquivo', async () => {
    wrapper = mountUpload({ busy: true })
    await drop(wrapper, [file('a.txt')])
    expect(wrapper.emitted('select')).toBeUndefined()
    expect(wrapper.text()).toContain('Enviando')

    wrapper = mountUpload({ disabled: true })
    await drop(wrapper, [file('a.txt')])
    expect(wrapper.emitted('select')).toBeUndefined()
  })

  it('sem a lista, só avisa a escolha', async () => {
    wrapper = mountUpload({ showList: false })
    await pick(wrapper, [file('a.txt')])
    expect(wrapper.find('.upload__files').exists()).toBe(false)
    expect(wrapper.emitted('select')).toHaveLength(1)
  })
})
