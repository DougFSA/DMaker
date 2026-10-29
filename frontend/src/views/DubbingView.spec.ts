import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useConfirmStore } from '@/stores/confirm'
import { useToastsStore } from '@/stores/toasts'
import { DUB_PATH, dubProject, renderResult, stubDubServer, type DubServer } from '@/test/dubServer'
import { FakeEventSource } from '@/test/fetch'
import { mountRoute } from '@/test/routes'
import { buttonLabelled, callsTo, CLIP, PROJECT, press } from '@/test/speechServer'

let server: DubServer

beforeEach(() => {
  localStorage.setItem('dmaker.currentProject', PROJECT)
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  server = stubDubServer({ project: null })
})
afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function mountView() {
  const mounted = await mountRoute('/dublagem')
  await flushPromises()
  return mounted
}

const emitEnd = async (result: unknown, status = 'done', error: string | null = null) => {
  FakeEventSource.latest().emit({ kind: 'end', t: 9, status, error, result })
  await flushPromises()
}

function field(wrapper: VueWrapper, label: string) {
  const owner = wrapper.findAll('label').find((node) => node.text().startsWith(label))
  if (!owner) throw new Error(`campo "${label}" não encontrado`)
  return wrapper.find(`#${owner.attributes('for')}`)
}

const optionsOf = (wrapper: VueWrapper, label: string) => field(wrapper, label).findAll('option').map((option) => option.text())

/** Abre a dublagem salva e devolve a tela com a tabela de falas pronta. */
async function openSaved(project = dubProject()) {
  server = stubDubServer({ project })
  const mounted = await mountView()
  await field(mounted.wrapper, 'Abrir uma dublagem').setValue(DUB_PATH)
  await press(mounted.wrapper, 'Abrir projeto')
  await flushPromises()
  return mounted
}

describe('DubbingView (/dublagem): preparar', () => {
  it('mostra o formulário com os idiomas, as vozes e as dublagens salvas, e já não diz "em construção"', async () => {
    server = stubDubServer({ project: dubProject() })
    const { wrapper } = await mountView()
    expect(wrapper.find('h1').text()).toBe('Dublagem')
    expect(wrapper.text()).not.toContain('em construção')
    expect(optionsOf(wrapper, 'Idioma da fala')).toEqual(['Português', 'Inglês', 'Espanhol'])
    expect((field(wrapper, 'Idioma da fala').element as HTMLSelectElement).value).toBe('pt')
    expect((field(wrapper, 'Dublar para').element as HTMLSelectElement).value).toBe('en')
    expect(optionsOf(wrapper, 'Modo de voz')).toEqual([
      'Uma voz clonada por pessoa (separa quem fala)',
      'Clonar a voz em volta de cada fala',
      'Um só clone para o arquivo todo',
    ])
    expect(optionsOf(wrapper, 'Voz da biblioteca')).toEqual(['Clonar a voz de quem fala (automático)', 'Dora (feminina)', 'Entrevistado (clonada)'])
    expect(optionsOf(wrapper, 'Quando a fala não cabe')).toEqual([
      'Acelerar a voz',
      'Esticar o vídeo (a voz fica natural)',
      'Misto (acelera um pouco e estica o resto)',
    ])
    expect(optionsOf(wrapper, 'Abrir uma dublagem')).toEqual(['Dublagens salvas...', 'entrevista.en.dub.json'])
    expect(optionsOf(wrapper, 'Arquivo')).toContain('entrevista.mp4')
    expect(buttonLabelled(wrapper, 'Preparar (transcrever e traduzir)').attributes('disabled')).toBeUndefined()
    expect(buttonLabelled(wrapper, 'Abrir projeto').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('Falas')
  })

  it('"Quantas pessoas falam" só existe no modo de uma voz por pessoa', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.text()).toContain('Quantas pessoas falam')
    await field(wrapper, 'Modo de voz').setValue('single')
    expect(wrapper.text()).not.toContain('Quantas pessoas falam')
  })

  it('o mesmo idioma nos dois lados trava o botão e diz o motivo', async () => {
    const { wrapper } = await mountView()
    await field(wrapper, 'Dublar para').setValue('pt')
    expect(wrapper.find('[role="alert"]').text()).toBe('O idioma de destino precisa ser diferente do de origem.')
    expect(buttonLabelled(wrapper, 'Preparar (transcrever e traduzir)').attributes('disabled')).toBeDefined()
    await field(wrapper, 'Dublar para').setValue('es')
    expect(buttonLabelled(wrapper, 'Preparar (transcrever e traduzir)').attributes('disabled')).toBeUndefined()
  })

  it('manda todos os campos ao servidor, mostra o andamento e deixa parar o trabalho', async () => {
    const { wrapper } = await mountView()
    await field(wrapper, 'Dublar para').setValue('es')
    await field(wrapper, 'Quantas pessoas falam').setValue('2')
    await field(wrapper, 'Voz da biblioteca').setValue('dora')
    await field(wrapper, 'Voz original por baixo').setValue('18')
    // sem `max`: o navegador não pode barrar o envio de "18", que a tela entende como -18
    expect(field(wrapper, 'Voz original por baixo').attributes('max')).toBeUndefined()
    await field(wrapper, 'Quando a fala não cabe').setValue('misto')
    await field(wrapper, 'Termos que não se traduzem').setValue('DMaker, MedlyCare, dmaker')
    await press(wrapper, 'Preparar (transcrever e traduzir)')
    await flushPromises()

    expect(callsTo(server.calls, 'POST', '/api/dub/prepare')[0]!.body).toEqual({
      path: CLIP,
      source_language: 'pt',
      target_language: 'es',
      speaker_mode: 'per_speaker',
      fit_mode: 'misto',
      num_speakers: 2,
      voice: 'dora',
      keep_original_db: -18,
      glossary: ['DMaker', 'MedlyCare'],
    })
    expect(wrapper.text()).toContain('Na fila...')
    FakeEventSource.latest().emit({ kind: 'progress', t: 1, label: 'Traduzindo a fala 2 de 3', done: 66, total: 100, percent: 66 })
    await flushPromises()
    expect(wrapper.text()).toContain('Traduzindo a fala 2 de 3')
    expect(wrapper.text()).toContain('66%')
    expect(buttonLabelled(wrapper, 'Preparar (transcrever e traduzir)').attributes('disabled')).toBeDefined()

    await press(wrapper, 'Parar')
    await flushPromises()
    expect(callsTo(server.calls, 'POST', '/api/jobs/j1/cancel')).toHaveLength(1)
    await emitEnd(null, 'cancelled')
    expect(wrapper.text()).toContain('Parado a pedido')
    expect(wrapper.text()).not.toContain('Falas')
    expect(buttonLabelled(wrapper, 'Preparar (transcrever e traduzir)').attributes('disabled')).toBeUndefined()
  })

  it('sem escolher modo por pessoa, não manda a quantidade de pessoas', async () => {
    const { wrapper } = await mountView()
    await field(wrapper, 'Quantas pessoas falam').setValue('3')
    await field(wrapper, 'Modo de voz').setValue('per_segment')
    await press(wrapper, 'Preparar (transcrever e traduzir)')
    await flushPromises()
    expect(callsTo(server.calls, 'POST', '/api/dub/prepare')[0]!.body).toMatchObject({
      speaker_mode: 'per_segment',
      num_speakers: null,
      keep_original_db: null,
      voice: null,
      glossary: [],
    })
    await emitEnd(null, 'cancelled')
  })

  it('terminada a preparação, a tabela de falas aparece com o resumo e o formulário reflete o projeto', async () => {
    const { wrapper } = await mountView()
    await press(wrapper, 'Preparar (transcrever e traduzir)')
    await flushPromises()
    await emitEnd(dubProject({ speaker_mode: 'single', fit_mode: 'video', keep_original_db: -20 }))

    expect(wrapper.text()).toContain('3 fala(s), pt para en. Tradução: tradutor-falso.')
    expect((field(wrapper, 'Tradução da fala s1').element as HTMLTextAreaElement).value).toBe('Hello everyone.')
    expect((field(wrapper, 'Tradução da fala s3').element as HTMLTextAreaElement).value).toBe('See you next time.')
    expect(wrapper.text()).toContain('Olá a todos.')
    expect(wrapper.text()).toContain('0,0 a 2,5 s')
    expect((field(wrapper, 'Modo de voz').element as HTMLSelectElement).value).toBe('single')
    expect((field(wrapper, 'Quando a fala não cabe').element as HTMLSelectElement).value).toBe('video')
    expect((field(wrapper, 'Voz original por baixo').element as HTMLInputElement).value).toBe('-20')
    // a fala 2 veio travada
    const locks = wrapper.findAll('tbody input[type="checkbox"]').map((box) => (box.element as HTMLInputElement).checked)
    expect(locks).toEqual([false, true, false])
    // a lista de dublagens salvas é lida de novo
    expect(callsTo(server.calls, 'GET', '/api/dub/projects').length).toBeGreaterThanOrEqual(2)
  })

  it('a preparação que falha mostra o motivo e libera o botão', async () => {
    const { wrapper } = await mountView()
    await press(wrapper, 'Preparar (transcrever e traduzir)')
    await flushPromises()
    await emitEnd(null, 'error', 'RuntimeError: Não consegui falar com o Ollama em http://localhost:11434.\ntraceback')
    expect(wrapper.find('[role="alert"]').text()).toContain('Não consegui falar com o Ollama')
    expect(buttonLabelled(wrapper, 'Preparar (transcrever e traduzir)').attributes('disabled')).toBeUndefined()
  })

  it('a recusa do servidor ao iniciar (arquivo sumiu) aparece e não abre acompanhamento', async () => {
    server = stubDubServer({ startReply: { body: { detail: 'Arquivo não encontrado: D:/m/entrevista.mp4' }, status: 404 } })
    const { wrapper } = await mountView()
    await press(wrapper, 'Preparar (transcrever e traduzir)')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('Arquivo não encontrado')
    expect(FakeEventSource.instances).toHaveLength(0)
  })
})

describe('DubbingView (/dublagem): abrir e revisar', () => {
  it('abre uma dublagem salva pelo caminho dela', async () => {
    const { wrapper } = await openSaved()
    expect(callsTo(server.calls, 'GET', `/api/dub/project?path=${encodeURIComponent(DUB_PATH)}`)).toHaveLength(1)
    expect(wrapper.text()).toContain('3 fala(s), pt para en.')
    expect((field(wrapper, 'Tradução da fala s2').element as HTMLTextAreaElement).value).toBe('Today we talk about video.')
  })

  it('um projeto que o servidor não acha mostra o erro', async () => {
    server = stubDubServer({ project: dubProject() })
    const { wrapper } = await mountView()
    server.project = null
    await field(wrapper, 'Abrir uma dublagem').setValue(DUB_PATH)
    await press(wrapper, 'Abrir projeto')
    await flushPromises()
    expect(wrapper.text()).not.toContain('3 fala(s)')
  })

  it('editar marca "Alterações não salvas" e "Salvar traduções" grava texto, trava e opções', async () => {
    const { wrapper } = await openSaved()
    expect(wrapper.text()).not.toContain('Alterações não salvas')
    await field(wrapper, 'Tradução da fala s1').setValue('  Hi everyone.  ')
    const lock3 = wrapper.findAll('tbody input[type="checkbox"]')[2]!
    await lock3.setValue(true)
    await field(wrapper, 'Voz original por baixo').setValue('12')
    expect(wrapper.text()).toContain('Alterações não salvas')

    await press(wrapper, 'Salvar traduções')
    await flushPromises()
    expect(server.lastSave()).toEqual({
      project: DUB_PATH,
      segments: [
        { id: 's1', text: 'Hi everyone.', locked: false },
        { id: 's2', text: 'Today we talk about video.', locked: true },
        { id: 's3', text: 'See you next time.', locked: true },
      ],
      keep_original_db: -12,
      speaker_mode: 'per_segment',
      fit_mode: 'voz',
      voice: null,
    })
    expect(server.project?.segments[0]!.text).toBe('Hi everyone.')
    expect(wrapper.text()).not.toContain('Alterações não salvas')
    expect((field(wrapper, 'Tradução da fala s1').element as HTMLTextAreaElement).value).toBe('Hi everyone.')
    expect(useToastsStore().items.map((toast) => toast.title)).toContain('Traduções salvas')
  })

  it('o falante é editável quando há mais de uma pessoa e só vai ao servidor se foi escolhido', async () => {
    const people = dubProject({
      speaker_mode: 'per_speaker',
      speakers: ['Falante 1', 'Falante 2'],
      segments: dubProject().segments.map((segment, index) => ({ ...segment, speaker: index === 2 ? null : 'Falante 1' })),
    })
    const { wrapper } = await openSaved(people)
    expect(wrapper.text()).toContain('2 falantes: troque o falante de uma fala')
    expect(optionsOf(wrapper, 'Falante da fala s1')).toEqual(['Falante 1', 'Falante 2'])
    // a fala sem falante tem a opção "Sem falante"
    expect(optionsOf(wrapper, 'Falante da fala s3')).toEqual(['Sem falante', 'Falante 1', 'Falante 2'])

    await field(wrapper, 'Falante da fala s1').setValue('Falante 2')
    await press(wrapper, 'Salvar traduções')
    await flushPromises()
    const speakers = (server.lastSave()!.segments as Array<{ id: string; speaker?: string }>).map((edit) => edit.speaker)
    expect(speakers).toEqual(['Falante 2', 'Falante 1', undefined])
  })

  it('com um falante só, a coluna de falante não aparece', async () => {
    const { wrapper } = await openSaved(dubProject({ speakers: ['Falante 1'] }))
    expect(wrapper.text()).not.toContain('Falante da fala')
    expect(wrapper.findAll('th').map((cell) => cell.text())).toEqual(['Tempo', 'Original', 'Tradução', 'Travar'])
  })

  it('o erro ao salvar aparece na tela e a edição não se perde', async () => {
    server = stubDubServer({ project: dubProject(), saveError: 'Falante "X" não existe no projeto.' })
    const { wrapper } = await mountView()
    await field(wrapper, 'Abrir uma dublagem').setValue(DUB_PATH)
    await press(wrapper, 'Abrir projeto')
    await flushPromises()
    await field(wrapper, 'Tradução da fala s1').setValue('Hi!')
    await press(wrapper, 'Salvar traduções')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('Falante "X" não existe no projeto.')
    expect((field(wrapper, 'Tradução da fala s1').element as HTMLTextAreaElement).value).toBe('Hi!')
    expect(wrapper.text()).toContain('Alterações não salvas')
  })

  it('traduzir de novo pede confirmação, salva antes e troca a tabela pelo que o servidor devolve', async () => {
    const { wrapper } = await openSaved()
    await field(wrapper, 'Tradução da fala s1').setValue('Mine.')
    await press(wrapper, 'Traduzir de novo as destravadas')
    await flushPromises()
    const confirmation = useConfirmStore()
    expect(confirmation.current?.options.title).toBe('Traduzir de novo as falas destravadas?')
    expect(callsTo(server.calls, 'POST', '/api/dub/retranslate')).toHaveLength(0)
    confirmation.answer(true)
    await flushPromises()

    expect(callsTo(server.calls, 'PUT', '/api/dub/project')).toHaveLength(1)
    expect(callsTo(server.calls, 'POST', '/api/dub/retranslate')[0]!.body).toEqual({ project: DUB_PATH })
    const fresh = dubProject()
    fresh.segments[0]!.text = 'Hello, everybody.'
    await emitEnd(fresh)
    expect((field(wrapper, 'Tradução da fala s1').element as HTMLTextAreaElement).value).toBe('Hello, everybody.')
  })

  it('recusar a confirmação não salva nem traduz', async () => {
    const { wrapper } = await openSaved()
    await press(wrapper, 'Traduzir de novo as destravadas')
    await flushPromises()
    useConfirmStore().answer(false)
    await flushPromises()
    expect(callsTo(server.calls, 'PUT', '/api/dub/project')).toHaveLength(0)
    expect(callsTo(server.calls, 'POST', '/api/dub/retranslate')).toHaveLength(0)
  })
})

describe('DubbingView (/dublagem): gerar', () => {
  it('gera em rascunho depois de salvar, mostra "fala i de n" e a situação de cada fala', async () => {
    const { wrapper } = await openSaved()
    await field(wrapper, 'Rascunho').setValue(true)
    await press(wrapper, 'Gerar dublagem')
    await flushPromises()

    expect(callsTo(server.calls, 'PUT', '/api/dub/project')).toHaveLength(1)
    expect(callsTo(server.calls, 'POST', '/api/dub/render')[0]!.body).toEqual({ project: DUB_PATH, draft: true })
    FakeEventSource.latest().emit({ kind: 'progress', t: 1, label: 'Sintetizando a fala 2 de 3', done: 40, total: 100, percent: 40 })
    await flushPromises()
    expect(wrapper.text()).toContain('Sintetizando a fala 2 de 3')
    // enquanto gera, nada mais se mexe
    expect(buttonLabelled(wrapper, 'Salvar traduções').attributes('disabled')).toBeDefined()
    expect(field(wrapper, 'Tradução da fala s1').attributes('disabled')).toBeDefined()

    await emitEnd(renderResult())
    expect(wrapper.text()).toContain('Dublagem pronta')
    expect(wrapper.text()).toContain('2 fala(s) sintetizada(s) agora e 1 reaproveitada(s) do cache, em 8 s.')
    expect(wrapper.text()).toContain('Vídeo esticado em 1 trecho(s), 1,0 s a mais. O vídeo final tem 11,5 s.')
    const rows = wrapper.findAll('tbody tr').map((row) => row.text())
    expect(rows[0]).toContain('cabe')
    expect(rows[0]).toContain('nova')
    expect(rows[1]).toContain('comprimida')
    expect(rows[1]).not.toContain('nova')
    expect(rows[2]).toContain('vídeo esticado 1,25x')
    expect(wrapper.findAll('th').map((cell) => cell.text())).toContain('Situação')
  })

  it('mostra o original e o dublado lado a lado, comparáveis, e baixa o vídeo e a legenda', async () => {
    const clicked: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.getAttribute('href') ?? '')
    })
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
    const { wrapper } = await openSaved()
    await press(wrapper, 'Gerar dublagem')
    await flushPromises()
    await emitEnd(renderResult())

    const [original, dubbed] = wrapper.findAll('video').map((node) => node.element as HTMLVideoElement)
    expect(original!.getAttribute('src')).toBe('/api/file?path=entrevista')
    expect(dubbed!.getAttribute('src')).toContain('/api/voices/audio?path=dublado')
    expect(wrapper.findAll('audio')).toHaveLength(0)

    // "Ouvir o dublado" parte do começo, mesmo que o original esteja adiante (o dublado pode ter outra duração)
    original!.currentTime = 7
    await buttonLabelled(wrapper, 'Ouvir dublado').trigger('click')
    expect(dubbed!.currentTime).toBe(0)

    await press(wrapper, 'Baixar o vídeo dublado')
    await press(wrapper, 'Baixar a legenda (.srt)')
    await flushPromises()
    expect(clicked).toEqual(['/api/voices/audio?path=dublado&download=true', '/api/dub/file?path=legenda&download=true'])
  })

  it('lista os avisos da geração', async () => {
    const { wrapper } = await openSaved()
    await press(wrapper, 'Gerar dublagem')
    await flushPromises()
    await emitEnd(renderResult({ warnings: ['Fala s2: a tradução não coube e foi cortada.'], stretched: [] }))
    expect(wrapper.find('ul[aria-label="Avisos da geração"]').text()).toBe('Fala s2: a tradução não coube e foi cortada.')
  })

  it('a dublagem de um áudio toca em player de áudio', async () => {
    const { wrapper } = await openSaved()
    await press(wrapper, 'Gerar dublagem')
    await flushPromises()
    await emitEnd(renderResult({ output: 'X:/saida/dublagem/podcast.en.wav' }))
    expect(wrapper.findAll('audio')).toHaveLength(2)
    expect(wrapper.findAll('video')).toHaveLength(0)
    expect(buttonLabelled(wrapper, 'Baixar o áudio dublado')).toBeDefined()
  })

  it('a falha ao gerar aparece e as edições continuam na tabela', async () => {
    const { wrapper } = await openSaved()
    await press(wrapper, 'Gerar dublagem')
    await flushPromises()
    await emitEnd(null, 'error', 'FileNotFoundError: Arquivo de origem não encontrado: D:/m/entrevista.mp4\ntraceback')
    expect(wrapper.find('[role="alert"]').text()).toContain('Arquivo de origem não encontrado')
    expect(wrapper.text()).not.toContain('Dublagem pronta')
    expect(buttonLabelled(wrapper, 'Gerar dublagem').attributes('disabled')).toBeUndefined()
  })

  it('parar a geração mostra "Parado a pedido" e libera os botões', async () => {
    const { wrapper } = await openSaved()
    await press(wrapper, 'Gerar dublagem')
    await flushPromises()
    await press(wrapper, 'Parar')
    await flushPromises()
    expect(callsTo(server.calls, 'POST', '/api/jobs/j1/cancel')).toHaveLength(1)
    await emitEnd(null, 'cancelled')
    expect(wrapper.text()).toContain('Parado a pedido')
    expect(buttonLabelled(wrapper, 'Gerar dublagem').attributes('disabled')).toBeUndefined()
  })
})

describe('DubbingView (/dublagem): trilhas', () => {
  it('"Baixar trilhas" salva, gera o .zip e baixa quando fica pronto', async () => {
    const clicked: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.getAttribute('href') ?? '')
    })
    const { wrapper } = await openSaved()
    await press(wrapper, 'Baixar trilhas')
    await flushPromises()

    expect(callsTo(server.calls, 'PUT', '/api/dub/project')).toHaveLength(1)
    expect(callsTo(server.calls, 'POST', '/api/dub/stems')[0]!.body).toEqual({ project: DUB_PATH, draft: false })
    expect(clicked).toEqual([])
    await emitEnd({
      folder: 'X:/saida/dublagem/entrevista.en.trilhas',
      files: ['voz-dublada.wav', 'fundo.wav', 'voz-original.wav'],
      zip: 'X:/saida/dublagem/entrevista.en.trilhas.zip',
      zip_url: '/api/dub/file?path=trilhas&download=true',
      duration: 40,
      original_voice_db: -18,
    })
    expect(clicked).toEqual(['/api/dub/file?path=trilhas&download=true'])
    expect(wrapper.text()).toContain('Trilhas prontas (voz-dublada.wav, fundo.wav, voz-original.wav), cada uma com 40,00 s.')
    expect(wrapper.text()).toContain('usa a voz original a -18 dB')
  })

  it('se as trilhas falham, nada é baixado e o motivo aparece', async () => {
    const clicked: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.getAttribute('href') ?? '')
    })
    const { wrapper } = await openSaved()
    await press(wrapper, 'Baixar trilhas')
    await flushPromises()
    await emitEnd(null, 'error', 'RuntimeError: o modelo de separação não está instalado\ntraceback')
    expect(clicked).toEqual([])
    expect(wrapper.find('[role="alert"]').text()).toContain('o modelo de separação não está instalado')
  })
})

describe('DubbingView (/dublagem): usar no projeto', () => {
  async function dubbed(wrapper: VueWrapper) {
    await press(wrapper, 'Gerar dublagem')
    await flushPromises()
    await emitEnd(renderResult())
  }

  it('depois de preparar um arquivo do projeto, troca o original pelo dublado e salva', async () => {
    const { wrapper } = await mountView()
    server.project = dubProject()
    await press(wrapper, 'Preparar (transcrever e traduzir)')
    await flushPromises()
    await emitEnd(dubProject())
    await dubbed(wrapper)
    expect(buttonLabelled(wrapper, 'Usar no projeto').attributes('disabled')).toBeUndefined()

    await press(wrapper, 'Usar no projeto')
    await flushPromises()
    const output = 'X:/saida/dublagem/entrevista.en.mp4'
    const edits = callsTo(server.calls, 'POST', `/api/projects/${PROJECT}/edit`).map((call) => (call.body as { op: unknown }).op)
    expect(edits).toEqual([
      { type: 'set_field', path: 'timeline.0.src', value: output },
      { type: 'set_field', path: 'overlays.0.src', value: output },
    ])
    expect(callsTo(server.calls, 'PUT', `/api/projects/${PROJECT}`)).toHaveLength(1)
    expect(wrapper.text()).toContain(`Projeto ${PROJECT} atualizado: vídeo dublado em 2 ponto(s).`)
  })

  it('uma dublagem reaberta acha no projeto aberto o arquivo que ela dublou', async () => {
    const { wrapper } = await openSaved()
    await dubbed(wrapper)
    expect(buttonLabelled(wrapper, 'Usar no projeto').attributes('disabled')).toBeUndefined()
    await press(wrapper, 'Usar no projeto')
    await flushPromises()
    expect(callsTo(server.calls, 'PUT', `/api/projects/${PROJECT}`)).toHaveLength(1)
    expect(wrapper.text()).toContain('vídeo dublado em 2 ponto(s)')
  })

  it('se o arquivo dublado não é do projeto aberto, o botão fica desligado e explica', async () => {
    const { wrapper } = await openSaved(dubProject({ source: 'D:/outro/aula.mp4' }))
    await dubbed(wrapper)
    expect(buttonLabelled(wrapper, 'Usar no projeto').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('Para usar no projeto, escolha um arquivo do projeto aberto.')
  })
})

describe('DubbingView (/dublagem): ficar na tela', () => {
  it('o projeto, a edição e o resultado sobrevivem a trocar de tela e voltar', async () => {
    const { wrapper, router } = await openSaved()
    await field(wrapper, 'Tradução da fala s1').setValue('Hi there.')
    await press(wrapper, 'Gerar dublagem')
    await flushPromises()
    await emitEnd(renderResult())

    await router.push('/saidas')
    await flushPromises()
    await router.push('/dublagem')
    await flushPromises()
    expect(wrapper.text()).toContain('Dublagem pronta')
    expect((field(wrapper, 'Tradução da fala s1').element as HTMLTextAreaElement).value).toBe('Hi there.')
  })

  it('o arquivo escolhido para dublar não volta ao primeiro do projeto ao voltar à tela', async () => {
    const SECOND = 'D:/m/aula.mp4'
    server = stubDubServer({ project: null, spec: { name: PROJECT, timeline: [{ type: 'clip', src: CLIP }, { type: 'clip', src: SECOND }] } })
    const { wrapper, router } = await mountView()
    await field(wrapper, 'Arquivo').setValue('project:1')

    await router.push('/saidas')
    await flushPromises()
    await router.push('/dublagem')
    await flushPromises()
    expect((field(wrapper, 'Arquivo').element as HTMLSelectElement).value).toBe('project:1')
    await press(wrapper, 'Preparar (transcrever e traduzir)')
    await flushPromises()
    expect(callsTo(server.calls, 'POST', '/api/dub/prepare')[0]!.body).toMatchObject({ path: SECOND })
    await emitEnd(null, 'cancelled')
  })

  it('um trabalho em andamento continua ao trocar de tela', async () => {
    const { wrapper, router } = await mountView()
    await press(wrapper, 'Preparar (transcrever e traduzir)')
    await flushPromises()
    await router.push('/saidas')
    await flushPromises()
    await router.push('/dublagem')
    await flushPromises()
    expect(wrapper.text()).toContain('Na fila...')
    expect(buttonLabelled(wrapper, 'Preparar (transcrever e traduzir)').attributes('disabled')).toBeDefined()
    await emitEnd(dubProject())
    expect(wrapper.text()).toContain('3 fala(s)')
  })
})
