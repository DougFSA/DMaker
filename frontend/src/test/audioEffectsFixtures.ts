/* O catálogo de efeitos de áudio de mentira dos testes: o mesmo formato do `GET /api/audio-effects` (catalog_payload),
   com os cinco efeitos básicos, os campos comuns e os lugares onde a cadeia pode ficar. */
import type { AudioEffectCatalog, AudioEffectParam } from '@/api'

function param(extra: Partial<AudioEffectParam> & Pick<AudioEffectParam, 'name' | 'label' | 'kind'>): AudioEffectParam {
  return { unit: '', default: null, minimum: null, maximum: null, hint: '', options: [], ...extra }
}

export function audioEffectCatalog(): AudioEffectCatalog {
  return {
    effects: [
      {
        type: 'amplify',
        label: 'Amplificar',
        audacity_name: 'Amplify',
        summary: 'Muda o volume por um ganho em dB, com a opção de não deixar o som clipar.',
        changes_duration: false,
        parameters: [
          param({
            name: 'gain_db',
            label: 'Amplificação',
            kind: 'number',
            unit: 'dB',
            default: 0,
            minimum: -100,
            maximum: 100,
            hint: 'Ganho em dB: positivo sobe o volume, negativo desce.',
          }),
          param({ name: 'prevent_clipping', label: 'Não deixar clipar', kind: 'boolean', default: false, hint: 'Limita o ganho.' }),
        ],
      },
      {
        type: 'normalize',
        label: 'Normalizar',
        audacity_name: 'Normalize',
        summary: 'Ajusta o volume para o pico chegar ao alvo.',
        changes_duration: false,
        parameters: [
          param({ name: 'peak_db', label: 'Pico alvo', kind: 'number', unit: 'dBFS', default: -1, minimum: -100, maximum: 0 }),
          param({ name: 'remove_dc', label: 'Remover deslocamento DC', kind: 'boolean', default: true }),
          param({ name: 'stereo_independent', label: 'Canais independentes', kind: 'boolean', default: false }),
        ],
      },
      { type: 'invert', label: 'Inverter', audacity_name: 'Invert', summary: 'Inverte a fase da onda.', changes_duration: false, parameters: [] },
      { type: 'reverse', label: 'Reverter', audacity_name: 'Reverse', summary: 'Toca o trecho de trás para a frente.', changes_duration: false, parameters: [] },
      {
        type: 'repeat',
        label: 'Repetir',
        audacity_name: 'Repeat',
        summary: 'Repete o trecho em sequência. Aumenta a duração: só vale em voz gravada e em música.',
        changes_duration: true,
        parameters: [param({ name: 'times', label: 'Vezes que toca', kind: 'integer', default: 2, minimum: 1, maximum: 100 })],
      },
    ],
    common: [
      param({ name: 'enabled', label: 'Ligado', kind: 'boolean', default: true }),
      param({ name: 'start', label: 'Início do intervalo', kind: 'number', unit: 's', minimum: 0, hint: 'Vazio: do começo do item.' }),
      param({ name: 'end', label: 'Fim do intervalo', kind: 'number', unit: 's', minimum: 0, hint: 'Vazio: até o fim do item.' }),
    ],
    targets: [
      { target: 'timeline.N', label: 'Som do clipe (N: posição do trecho)', may_grow: false },
      { target: 'overlays.N', label: 'Áudio de um PiP (N: posição da sobreposição)', may_grow: false },
      { target: 'audio.voiceover.N', label: 'Voz gravada', may_grow: true },
      { target: 'audio.narration.N', label: 'Narração sintetizada', may_grow: false },
      { target: 'audio.music', label: 'Música', may_grow: true },
      { target: 'audio.tracks.N', label: 'Faixa externa sincronizada', may_grow: false },
      { target: 'audio.master', label: 'Mistura inteira, antes da normalização final', may_grow: false },
    ],
  }
}
