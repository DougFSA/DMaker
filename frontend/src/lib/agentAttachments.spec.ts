import { describe, expect, it } from 'vitest'
import { ApiError } from '@/api'
import type { AgentModel } from '@/api'
import { GEMMA, GPT_OSS, QWEN, imageAttachment, mediaAttachment, textAttachment } from '@/test/agentServer'
import {
  ATTACHMENT_ACCEPT,
  MAX_ATTACHMENTS,
  attachmentKindOf,
  attachmentOnlyMessage,
  attachmentWarnings,
  cardDetail,
  cardOfAttachment,
  cardOfSummary,
  cutNote,
  failedCard,
  kindLabel,
  splitPicked,
  suggestedModelsOf,
  uploadingCard,
} from './agentAttachments'

const cards = (...attachments: Parameters<typeof cardOfAttachment>[0][]) => attachments.map(cardOfAttachment)

/** Um modelo que lê imagem e usa ferramentas: hoje não existe um instalado, mas a regra do modo Operar precisa dele. */
const SEER: AgentModel = { ...GEMMA, name: 'visao:7b', capabilities: ['vision', 'tools'] }

describe('tipo do arquivo pelo nome', () => {
  it('reconhece imagem, planilha, documento e vídeo ou áudio, sem diferenciar maiúsculas', () => {
    expect(attachmentKindOf('foto.PNG')).toBe('image')
    expect(attachmentKindOf('foto.jpeg')).toBe('image')
    expect(attachmentKindOf('semana.xlsx')).toBe('sheet')
    expect(attachmentKindOf('roteiro.docx')).toBe('text')
    expect(attachmentKindOf('contrato.pdf')).toBe('text')
    expect(attachmentKindOf('legenda.srt')).toBe('text')
    expect(attachmentKindOf('aula.mp4')).toBe('media')
    expect(attachmentKindOf('trilha.wav')).toBe('media')
  })

  it('uma extensão que o servidor não conhece fica sem tipo, e arquivo sem extensão também', () => {
    expect(attachmentKindOf('programa.exe')).toBeNull()
    expect(attachmentKindOf('LEIAME')).toBeNull()
  })

  it('o filtro do seletor lista todas as extensões que o servidor aceita', () => {
    const extensions = ATTACHMENT_ACCEPT.split(',')
    for (const name of ['a.png', 'a.jpg', 'a.webp', 'a.csv', 'a.xlsx', 'a.txt', 'a.md', 'a.srt', 'a.docx', 'a.pdf', 'a.mp4', 'a.mp3']) {
      expect(extensions).toContain(name.slice(name.indexOf('.')))
    }
  })
})

describe('a ficha', () => {
  it('vem do anexo do servidor, do resumo da mensagem enviada e do arquivo que ainda sobe', () => {
    expect(cardOfAttachment(textAttachment({ chars: 800, total_chars: 5000, truncated: true }))).toMatchObject({
      key: 'a1',
      state: 'ready',
      kind: 'text',
      id: 'a1',
      chars: 800,
      totalChars: 5000,
      truncated: true,
    })
    expect(cardOfSummary({ id: 'a9', kind: 'image', name: 'foto.png', size: 10 })).toMatchObject({ state: 'ready', kind: 'image', chars: null, truncated: false })
    expect(uploadingCard('k1', { name: 'aula.mp4', size: 3 })).toMatchObject({ key: 'k1', state: 'uploading', kind: 'media', id: null })
  })

  it('a ficha que falhou guarda o motivo', () => {
    const failed = failedCard(uploadingCard('k1', { name: 'a.exe', size: 1 }), 'Formato desconhecido.')
    expect(failed).toMatchObject({ state: 'error', error: 'Formato desconhecido.', kind: null })
  })

  it('diz o tipo e o tamanho, e separa vídeo de áudio', () => {
    expect(kindLabel({ kind: 'media', name: 'aula.mp4' })).toBe('Vídeo')
    expect(kindLabel({ kind: 'media', name: 'voz.mp3' })).toBe('Áudio')
    expect(kindLabel({ kind: null, name: 'x.exe' })).toBe('Arquivo')
    expect(cardDetail(cardOfAttachment(textAttachment({ size: 2048 })))).toBe('Documento · 2 KB')
    expect(cardDetail(cardOfAttachment(imageAttachment({ size: 100 })))).toBe('Imagem · 100 B')
  })

  it('avisa o corte do texto com os números do servidor, e fica calada quando o texto cabe inteiro', () => {
    const cut = cardOfAttachment(textAttachment({ chars: 12400, total_chars: 38000, truncated: true }))
    expect(cutNote(cut)).toBe('cortado: 12.400 de 38.000 caracteres')
    expect(cutNote(cardOfAttachment(textAttachment()))).toBe('')
    expect(cutNote(cardOfAttachment(imageAttachment()))).toBe('')
  })
})

describe('mensagem só com anexo', () => {
  it('o servidor exige texto: um anexo é "o anexo", vários são "os anexos", e sem anexo não há texto', () => {
    expect(attachmentOnlyMessage(1)).toBe('Veja o anexo.')
    expect(attachmentOnlyMessage(3)).toBe('Veja os anexos.')
    expect(attachmentOnlyMessage(0)).toBe('')
  })
})

describe('o que a tela recusa ao escolher', () => {
  const named = (...names: string[]) => names.map((name) => ({ name }))

  it('aceita tudo o que cabe', () => {
    const { accepted, notices } = splitPicked(named('a.png', 'b.docx'), 'operate', 8)
    expect(accepted).toHaveLength(2)
    expect(notices).toEqual([])
  })

  it('recusa mais de 8 anexos antes do servidor e diz quais ficaram de fora', () => {
    const files = named(...Array.from({ length: 10 }, (_, index) => `f${index}.txt`))
    const { accepted, notices } = splitPicked(files, 'operate', MAX_ATTACHMENTS)
    expect(accepted).toHaveLength(8)
    expect(notices).toEqual(['Uma mensagem leva no máximo 8 anexos. Não anexei: f8.txt, f9.txt.'])
  })

  it('conta o que já está anexado: com 7 na mensagem, só 1 mais cabe', () => {
    const { accepted, notices } = splitPicked(named('a.txt', 'b.txt'), 'operate', 1)
    expect(accepted.map((file) => file.name)).toEqual(['a.txt'])
    expect(notices[0]).toContain('b.txt')
  })

  it('sem vaga nenhuma, nada entra', () => {
    expect(splitPicked(named('a.txt'), 'operate', 0).accepted).toEqual([])
  })

  it('vídeo e áudio numa Conversa livre não entram, e o resto do que foi escolhido segue', () => {
    const { accepted, notices } = splitPicked(named('aula.mp4', 'nota.txt', 'voz.mp3'), 'free', 8)
    expect(accepted.map((file) => file.name)).toEqual(['nota.txt'])
    expect(notices).toHaveLength(1)
    expect(notices[0]).toContain('aula.mp4, voz.mp3')
    expect(notices[0]).toContain('modo Operar o DMaker')
  })

  it('o mesmo vídeo no modo Operar entra', () => {
    expect(splitPicked(named('aula.mp4'), 'operate', 8).accepted).toHaveLength(1)
  })
})

describe('os avisos de antes de enviar', () => {
  const installed = [GPT_OSS, GEMMA, QWEN]

  it('sem anexo nenhum não há aviso', () => {
    expect(attachmentWarnings([], 'free', GPT_OSS, installed)).toEqual([])
  })

  it('imagem para um modelo que não lê imagem, na Conversa livre, sugere os modelos da lista que leem', () => {
    const [warning] = attachmentWarnings(cards(imageAttachment()), 'free', GPT_OSS, installed)
    expect(warning).toMatchObject({ code: 'image_without_vision', models: ['gemma3:4b'] })
    expect(warning!.text).toBe('O modelo gpt-oss:20b não lê imagem. Escolha um modelo com o selo Imagem: gemma3:4b.')
  })

  it('no modo Operar sugere só quem lê imagem e usa ferramentas', () => {
    const [warning] = attachmentWarnings(cards(imageAttachment()), 'operate', GPT_OSS, [GPT_OSS, GEMMA, SEER])
    expect(warning!.models).toEqual(['visao:7b'])
  })

  it('no modo Operar sem nenhum modelo que leia imagem e opere, diz isso e aponta a Conversa livre', () => {
    const [warning] = attachmentWarnings(cards(imageAttachment()), 'operate', GPT_OSS, installed)
    expect(warning!.models).toEqual([])
    expect(warning!.text).toContain('nenhum modelo instalado lê imagem e opera o DMaker')
    expect(warning!.text).toContain('abra uma Conversa livre com um modelo de imagem (gemma3:4b)')
  })

  it('sem nenhum modelo com visão, diz que não há nenhum instalado', () => {
    const [warning] = attachmentWarnings(cards(imageAttachment()), 'free', GPT_OSS, [GPT_OSS, QWEN])
    expect(warning!.models).toEqual([])
    expect(warning!.text).toBe('O modelo gpt-oss:20b não lê imagem, e nenhum modelo instalado lê imagem. Instale um com o selo Imagem no Ollama para usar este anexo.')
  })

  it('o modelo que lê imagem, o de capacidades desconhecidas e o que ainda não está na lista não geram aviso', () => {
    expect(attachmentWarnings(cards(imageAttachment()), 'free', GEMMA, installed)).toEqual([])
    expect(attachmentWarnings(cards(imageAttachment()), 'free', { ...GPT_OSS, capabilities: [] }, installed)).toEqual([])
    expect(attachmentWarnings(cards(imageAttachment()), 'free', undefined, installed)).toEqual([])
  })

  it('um texto ou uma planilha não pedem visão', () => {
    expect(attachmentWarnings(cards(textAttachment()), 'free', GPT_OSS, installed)).toEqual([])
  })

  it('vídeo ou áudio numa Conversa livre avisa que ali o arquivo não é usado e que é o modo Operar que trabalha com ele', () => {
    const [warning] = attachmentWarnings(cards(mediaAttachment()), 'free', GPT_OSS, installed)
    expect(warning).toMatchObject({ code: 'media_in_free_chat', models: [] })
    expect(warning!.text).toContain('não é usado')
    expect(warning!.text).toContain('modo Operar o DMaker que trabalha com ele')
  })

  it('o mesmo vídeo no modo Operar não gera aviso', () => {
    expect(attachmentWarnings(cards(mediaAttachment()), 'operate', GPT_OSS, installed)).toEqual([])
  })

  it('só as fichas que já estão no servidor contam: a que sobe ou falhou não segura o envio', () => {
    const list = [uploadingCard('k1', { name: 'foto.png', size: 1 }), failedCard(uploadingCard('k2', { name: 'foto2.png', size: 1 }), 'erro')]
    expect(attachmentWarnings(list, 'free', GPT_OSS, installed)).toEqual([])
  })

  it('imagem e vídeo juntos numa Conversa livre geram os dois avisos', () => {
    const warnings = attachmentWarnings(cards(imageAttachment(), mediaAttachment()), 'free', GPT_OSS, installed)
    expect(warnings.map((warning) => warning.code)).toEqual(['image_without_vision', 'media_in_free_chat'])
  })
})

describe('a recusa de imagem do servidor', () => {
  it('lê os modelos sugeridos do corpo cru do 422', () => {
    const failure = new ApiError(422, 'O modelo gpt-oss:20b não aceita imagens.', {
      detail: 'O modelo gpt-oss:20b não aceita imagens.',
      error: 'O modelo gpt-oss:20b não aceita imagens.',
      suggested_models: ['gemma3:4b'],
    })
    expect(suggestedModelsOf(failure)).toEqual(['gemma3:4b'])
  })

  it('qualquer outro erro não sugere modelo nenhum', () => {
    expect(suggestedModelsOf(new ApiError(500, 'falhou', { detail: 'falhou' }))).toEqual([])
    expect(suggestedModelsOf(new Error('x'))).toEqual([])
    expect(suggestedModelsOf(null)).toEqual([])
    expect(suggestedModelsOf({ detail: { suggested_models: 'gemma3:4b' } })).toEqual([])
  })
})
