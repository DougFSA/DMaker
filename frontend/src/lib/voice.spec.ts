import { describe, expect, it } from 'vitest'
import type { VoiceProfile } from '@/api'
import {
  brandOptions,
  cloneMissing,
  designRequest,
  extensionForMime,
  isRemovable,
  languageLabel,
  previewStatus,
  recordingAdvice,
  voiceDetails,
  voiceKindLabel,
  voiceOptionLabel,
  type DesignFormState,
} from './voice'

const LANGUAGES = [
  { value: 'pt', label: 'Português' },
  { value: 'en', label: 'Inglês' },
]

function voice(overrides: Partial<VoiceProfile> = {}): VoiceProfile {
  return {
    id: 'ana',
    name: 'Ana',
    kind: 'clone',
    engine: 'omnivoice',
    preset: null,
    language: 'pt',
    brand: null,
    instruct: null,
    reference: null,
    reference_text: null,
    created: '2026-10-29',
    ...overrides,
  }
}

describe('recordingAdvice', () => {
  it('avalia a duração da gravação em quatro faixas e a tampa', () => {
    const levels = [1, 4, 6, 12, 20].map((seconds) => recordingAdvice(seconds).level)
    expect(levels).toEqual(['bad', 'ok', 'good', 'ok', 'bad'])
  })

  it('diz o que fazer em cada faixa', () => {
    expect(recordingAdvice(1).text).toContain('pelo menos 5 segundos')
    expect(recordingAdvice(4).text).toContain('Quase lá')
    expect(recordingAdvice(6).text).toContain('Ótimo')
    expect(recordingAdvice(12).text).toContain('já bastam')
    expect(recordingAdvice(20).text).toBe('Só os primeiros 15 segundos serão usados.')
  })

  it('os limites de 5 s e de 8 s ainda contam como a faixa boa', () => {
    expect(recordingAdvice(5).level).toBe('good')
    expect(recordingAdvice(8).level).toBe('good')
    expect(recordingAdvice(15).level).toBe('ok')
  })
})

describe('extensionForMime', () => {
  it('escolhe a extensão pelo tipo que o MediaRecorder usou', () => {
    expect(['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg', 'audio/wav'].map(extensionForMime)).toEqual([
      'webm',
      'm4a',
      'ogg',
      'wav',
    ])
  })

  it('tipo vazio ou desconhecido cai em webm', () => {
    expect([extensionForMime(''), extensionForMime(null), extensionForMime(undefined), extensionForMime('audio/x')]).toEqual(
      ['webm', 'webm', 'webm', 'webm'],
    )
  })
})

describe('rótulos da biblioteca', () => {
  it('traduz o tipo da voz', () => {
    expect(['clone', 'design', 'preset'].map((kind) => voiceKindLabel(kind as VoiceProfile['kind']))).toEqual([
      'clonada',
      'desenhada',
      'pronta',
    ])
  })

  it('a opção de seletor leva o tipo entre parênteses', () => {
    expect(voiceOptionLabel(voice())).toBe('Ana (clonada)')
  })

  it('o idioma sai pelo nome; um código desconhecido volta como está', () => {
    expect(languageLabel('en', LANGUAGES)).toBe('Inglês')
    expect(languageLabel('ja', LANGUAGES)).toBe('ja')
  })

  it('os detalhes juntam só o que existe', () => {
    expect(voiceDetails(voice(), LANGUAGES)).toBe('Português · omnivoice')
    expect(voiceDetails(voice({ brand: 'medlycare', instruct: 'female, low pitch' }), LANGUAGES)).toBe(
      'Português · medlycare · omnivoice · female, low pitch',
    )
  })

  it('o nome da marca vem do brand.json e, sem nome, da pasta', () => {
    expect(brandOptions([{ key: 'medlycare', name: 'MedlyCare' }, { key: 'pascom', name: '' }])).toEqual([
      { value: 'medlycare', label: 'MedlyCare' },
      { value: 'pascom', label: 'pascom' },
    ])
  })

  it('só as vozes prontas não podem ser removidas', () => {
    expect(isRemovable({ kind: 'clone' })).toBe(true)
    expect(isRemovable({ kind: 'design' })).toBe(true)
    expect(isRemovable({ kind: 'preset' })).toBe(false)
  })
})

describe('previewStatus', () => {
  it('sem amostra a linha fica vazia', () => {
    expect(previewStatus(undefined, 1000)).toEqual({ text: '', failed: false })
  })

  it('mostra o relógio e a etapa enquanto a amostra é gerada', () => {
    const preview = { startedAtMs: 1000, label: '', error: '' }
    expect(previewStatus(preview, 8000)).toEqual({ text: 'Gerando amostra... 0:07', failed: false })
    expect(previewStatus({ ...preview, label: 'fala 1 de 1' }, 66000).text).toBe(
      'Gerando amostra... 1:05 · fala 1 de 1',
    )
  })

  it('o relógio nunca fica negativo', () => {
    expect(previewStatus({ startedAtMs: 5000, label: '', error: '' }, 1000).text).toBe('Gerando amostra... 0:00')
  })

  it('a falha vira a mensagem do erro', () => {
    expect(previewStatus({ startedAtMs: 0, label: '', error: 'Modelo ausente' }, 9000)).toEqual({
      text: 'Não consegui gerar a amostra: Modelo ausente',
      failed: true,
    })
  })
})

describe('cloneMissing', () => {
  it('lista o que falta, na ordem do formulário', () => {
    expect(cloneMissing({ name: '', hasReference: false, consent: false })).toEqual([
      'dar um nome à voz',
      'enviar um arquivo ou gravar pelo microfone',
      'marcar a permissão do dono da voz',
    ])
  })

  it('só a caixa de permissão faltando já impede clonar', () => {
    expect(cloneMissing({ name: 'Ana', hasReference: true, consent: false })).toEqual([
      'marcar a permissão do dono da voz',
    ])
  })

  it('nome só com espaços não vale', () => {
    expect(cloneMissing({ name: '   ', hasReference: true, consent: true })).toEqual(['dar um nome à voz'])
  })

  it('com tudo preenchido não falta nada', () => {
    expect(cloneMissing({ name: 'Ana', hasReference: true, consent: true })).toEqual([])
  })
})

describe('designRequest', () => {
  const blank: DesignFormState = {
    name: '  Narradora  ',
    gender: '',
    age: '',
    pitch: '',
    accent: '',
    language: 'pt',
    brand: '',
    whisper: false,
    instruct: '   ',
  }

  it('campo em branco vira null e o nome perde os espaços das pontas', () => {
    expect(designRequest(blank)).toEqual({
      name: 'Narradora',
      gender: null,
      age: null,
      pitch: null,
      accent: null,
      whisper: false,
      instruct: null,
      brand: null,
      language: 'pt',
    })
  })

  it('leva o que foi escolhido, inclusive sussurrada e a descrição livre', () => {
    const request = designRequest({
      ...blank,
      gender: 'female',
      age: 'middle-aged',
      pitch: 'low pitch',
      accent: 'british accent',
      brand: 'medlycare',
      whisper: true,
      instruct: ' female, low pitch ',
    })
    expect(request).toMatchObject({
      gender: 'female',
      age: 'middle-aged',
      pitch: 'low pitch',
      accent: 'british accent',
      brand: 'medlycare',
      whisper: true,
      instruct: 'female, low pitch',
    })
  })
})
