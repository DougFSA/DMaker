import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PreviewAudioStatus, TimelineView } from '@/api'
import { projectSpec, timelineItem, timelineTrack } from '@/test/editorFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { MIX_POLL_MS } from '@/stores/playerMedia'
import { usePlayerStore } from '@/stores/player'
import { usePlayerMediaStore } from '@/stores/playerMedia'
import PlayerPanel from './PlayerPanel.vue'

/* O projeto do critério de aceite, em miniatura: duas câmeras mudas (a segunda com um arquivo ausente), a mesa
   com sincronia, a música e um PiP. Os itens são os que o servidor manda. */
function sessionView(extra: { missingClip?: boolean } = {}): TimelineView {
  const clip0 = timelineItem(0, { id: 'V1-0', start: 0, end: 6, path: 'C:/cam1.mp4', extra: {} })
  const clip1 = timelineItem(1, { id: 'V1-1', start: 6, end: 12, path: 'C:/cam2.mp4', missing: !!extra.missingClip, extra: {} })
  const audio = (id: string, start: number, end: number, extraItem: Parameters<typeof timelineItem>[1]) =>
    timelineItem(0, { id, start, end, ...extraItem })
  return {
    total: 12,
    fps: 30,
    width: 1080,
    height: 1920,
    warnings: extra.missingClip ? ['Fonte não encontrada: C:/cam2.mp4'] : [],
    sources: {},
    tracks: [
      timelineTrack('V2', [timelineItem(0, { id: 'V2-0', kind: 'video', start: 0, end: 12, path: 'C:/webcam.mp4', extra: { position: 'bottom-right' } })]),
      timelineTrack('V1', [clip0, clip1]),
      timelineTrack(
        'A1',
        [audio('A1-0', 0, 6, { kind: 'clip-audio', path: 'C:/cam1.mp4', muted: true, extra: { speed: 1 } })],
        { kind: 'audio' },
      ),
      timelineTrack(
        'A2',
        [audio('A2-0-0', 0, 12, { kind: 'track', source: 'mesa', path: 'C:/mesa.wav', in_point: 5, extra: { offset: 0, speed: 1, volume: 0.5 } })],
        { kind: 'audio' },
      ),
      timelineTrack(
        'MUS',
        [audio('MUS-0', 0, 12, { kind: 'music', path: 'C:/musica.mp3', in_point: 0, extra: { loop: true, volume: 0.3 } })],
        { kind: 'audio' },
      ),
    ],
  }
}

function status(extra: Partial<PreviewAudioStatus> = {}): PreviewAudioStatus {
  return { state: 'ready', key: 'k1', url: '/api/file?path=mix.m4a', duration_s: 12, warnings: [], error: null, label: '', percent: 0, ...extra }
}

const THEME = { colors: { text: '#ffffff' }, font: 'Poppins', logos: {}, no_dash: true }

let wrapper: VueWrapper | null = null
let opened: OpenedEditor

async function mountPlayer(routes: Record<string, unknown> = {}, view: TimelineView = sessionView()) {
  opened = await openEditor(projectSpec(), {
    'POST /api/projects/demo/timeline': () => view,
    'GET /api/projects/demo/theme': THEME,
    'GET /api/projects/demo/proxies': [],
    'POST /api/projects/demo/preview-audio': status(),
    ...routes,
  })
  wrapper = await mountEditorPart(PlayerPanel, opened, {}, true)
  await vi.advanceTimersByTimeAsync(0)
  await flushPromises()
  return wrapper
}

const audioElements = () => [...document.querySelectorAll<HTMLAudioElement>('audio')]
const videoElements = () => [...document.querySelectorAll<HTMLVideoElement>('video')]

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  // o jsdom não toca mídia: play e pause só anotam se o elemento está tocando, para o teste conferir `paused`
  const playing = new WeakSet<HTMLMediaElement>()
  vi.spyOn(HTMLMediaElement.prototype, 'paused', 'get').mockImplementation(function (this: HTMLMediaElement) {
    return !playing.has(this)
  })
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (this: HTMLMediaElement) {
    playing.add(this)
    return Promise.resolve()
  })
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (this: HTMLMediaElement) {
    playing.delete(this)
  })
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => undefined)
  window.localStorage.clear()
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('o painel do player', () => {
  it('mostra o palco na proporção do formato, o transporte e o timecode', async () => {
    const panel = await mountPlayer()
    const stage = panel.find('.stage')
    expect(stage.attributes('style')).toContain(`--ratio: ${1080 / 1920}`)
    expect(panel.find('[aria-label="Transporte do player"]').exists()).toBe(true)
    expect(panel.find('.transport__timecode').text()).toBe('00:00:00:00')
    expect(panel.find('.transport__total').text()).toBe('/ 00:00:12:00')
    for (const name of ['Ir ao início', 'Quadro anterior', 'Tocar', 'Próximo quadro', 'Ir ao fim', 'Voltar (J)', 'Parar (K)', 'Avançar (L)']) {
      expect(panel.find(`button[aria-label="${name}"]`).exists(), name).toBe(true)
    }
  })

  it('sem a linha do tempo calculada não há o que mostrar ainda', async () => {
    const panel = await mountPlayer({ 'POST /api/projects/demo/timeline': () => Promise.reject(new Error('x')) })
    await flushPromises()
    expect(panel.text()).toContain('Sem prévia ainda')
  })

  it('todo vídeo do palco é mudo, o do trecho e o do PiP', async () => {
    await mountPlayer()
    const videos = videoElements()
    expect(videos.length).toBeGreaterThanOrEqual(2) // o trecho, o próximo corte e o PiP
    expect(videos.every((video) => video.muted)).toBe(true)
    expect(videos.some((video) => video.src.includes(encodeURIComponent('C:/cam1.mp4')))).toBe(true)
    expect(videos.some((video) => video.src.includes(encodeURIComponent('C:/webcam.mp4')))).toBe(true)
  })

  it('o vídeo do próximo corte já está carregado mas escondido', async () => {
    await mountPlayer()
    const next = videoElements().find((video) => video.src.includes(encodeURIComponent('C:/cam2.mp4')))
    expect(next).toBeDefined()
    expect(next?.style.display).toBe('none')
    expect(next?.getAttribute('preload')).toBe('metadata')
  })

  it('o trecho com arquivo ausente abre marcado, sem vídeo', async () => {
    const panel = await mountPlayer({}, sessionView({ missingClip: true }))
    opened.store.setPlayhead(7)
    await flushPromises()
    expect(panel.find('.missing').text()).toContain('Fonte não encontrada')
    expect(panel.find('.missing').text()).toContain('cam2.mp4')
    expect(videoElements().some((video) => video.src.includes(encodeURIComponent('C:/cam2.mp4')))).toBe(false)
    // o aviso do servidor também aparece
    expect(panel.text()).toContain('Fonte não encontrada: C:/cam2.mp4')
  })
})

describe('o som', () => {
  it('com a mixagem pronta há um <audio> só, tocando a mixagem, e nenhum som ao vivo', async () => {
    const panel = await mountPlayer()
    usePlayerStore().play()
    opened.store.setPlayhead(3)
    await flushPromises()
    const audios = audioElements()
    expect(audios).toHaveLength(1)
    expect(audios[0]?.dataset.player).toBe('mix')
    expect(audios[0]?.getAttribute('src')).toBe('/api/file?path=mix.m4a')
    expect(audios[0]?.muted).toBe(false)
    expect(audios[0]?.paused).toBe(false) // a mixagem toca
    expect(videoElements().every((video) => video.muted)).toBe(true) // e nenhum vídeo tem som
    expect(panel.find('.player').attributes('data-sound')).toBe('mix')
    expect(panel.text()).toContain('Áudio da mixagem')
    expect(panel.text()).not.toContain('Áudio aproximado:')
  })

  it('o <audio> da mixagem anda com o cursor e com o volume do player', async () => {
    await mountPlayer()
    const player = usePlayerStore()
    player.setVolume(0.4)
    player.play()
    opened.store.setPlayhead(4.5)
    await flushPromises()
    const mix = audioElements()[0]!
    expect(mix.currentTime).toBe(4.5)
    expect(mix.volume).toBe(0.4)
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled()
  })

  it('enquanto a mixagem é feita o som é ao vivo, por trilha, com o aviso de áudio aproximado', async () => {
    const panel = await mountPlayer({
      'POST /api/projects/demo/preview-audio': status({ state: 'building', url: null, label: 'áudio do trecho 2/3', percent: 20 }),
      'GET /api/projects/demo/preview-audio': status({ state: 'building', url: null }),
    })
    usePlayerStore().play()
    opened.store.setPlayhead(3)
    await flushPromises()

    expect(panel.text()).toContain('Áudio aproximado')
    expect(panel.text()).toContain('áudio do trecho 2/3 (20%)')
    expect(panel.find('.player').attributes('data-sound')).toBe('live')
    const live = audioElements().filter((audio) => audio.dataset.player?.startsWith('live:'))
    // a câmera está em mute: só a mesa e a música soam, cada uma no seu elemento e no ponto dela
    expect(live.map((audio) => audio.dataset.player).sort()).toEqual(['live:A2', 'live:MUS'])
    const mesa = live.find((audio) => audio.dataset.player === 'live:A2')!
    expect(mesa.getAttribute('src')).toContain(encodeURIComponent('C:/mesa.wav'))
    expect(mesa.currentTime).toBe(8) // 5 s no arquivo no início do corte + 3 s tocados
    expect(mesa.volume).toBe(0.5)
    expect(audioElements().find((audio) => audio.dataset.player === 'mix')?.getAttribute('src')).toBeNull()
  })

  it('quando a mixagem fica pronta, o som ao vivo sai de cena e fica um fluxo só', async () => {
    let polls = 0
    const panel = await mountPlayer({
      'POST /api/projects/demo/preview-audio': status({ state: 'building', url: null }),
      'GET /api/projects/demo/preview-audio': () => (++polls < 2 ? status({ state: 'building', url: null }) : status()),
    })
    usePlayerStore().play()
    opened.store.setPlayhead(3)
    await flushPromises()
    expect(audioElements().filter((audio) => audio.dataset.player?.startsWith('live:')).length).toBeGreaterThan(0)

    await vi.advanceTimersByTimeAsync(MIX_POLL_MS * 3)
    await flushPromises()
    opened.store.setPlayhead(3.5)
    await flushPromises()
    expect(usePlayerMediaStore().current).toBe(true)
    const audios = audioElements()
    expect(audios).toHaveLength(1)
    expect(audios[0]?.dataset.player).toBe('mix')
    expect(panel.text()).toContain('Áudio da mixagem')
  })

  it('parado, nenhum áudio toca', async () => {
    await mountPlayer()
    const player = usePlayerStore()
    player.play()
    opened.store.setPlayhead(2)
    await flushPromises()
    expect(audioElements().some((audio) => !audio.paused)).toBe(true)
    player.pause()
    await flushPromises()
    expect(audioElements().every((audio) => audio.paused)).toBe(true)
    expect(videoElements().every((video) => video.paused)).toBe(true)
  })

  it('o que a mixagem deixou de fora aparece como aviso', async () => {
    const panel = await mountPlayer({
      'POST /api/projects/demo/preview-audio': status({ warnings: ['A narração 1 ainda não foi sintetizada e fica fora da prévia.'] }),
    })
    expect(panel.text()).toContain('A narração 1 ainda não foi sintetizada')
  })
})

describe('transporte e teclado', () => {
  it('o botão de tocar alterna entre tocar e pausar', async () => {
    const panel = await mountPlayer()
    await panel.find('button[aria-label="Tocar"]').trigger('click')
    expect(usePlayerStore().playing).toBe(true)
    expect(panel.find('button[aria-label="Pausar"]').exists()).toBe(true)
    await panel.find('button[aria-label="Pausar"]').trigger('click')
    expect(usePlayerStore().playing).toBe(false)
  })

  it('quadro a quadro, início e fim movem o cursor e o timecode', async () => {
    const panel = await mountPlayer()
    await panel.find('button[aria-label="Próximo quadro"]').trigger('click')
    expect(panel.find('.transport__timecode').text()).toBe('00:00:00:01')
    await panel.find('button[aria-label="Ir ao fim"]').trigger('click')
    expect(panel.find('.transport__timecode').text()).toBe('00:00:12:00')
    await panel.find('button[aria-label="Ir ao início"]').trigger('click')
    expect(panel.find('.transport__timecode').text()).toBe('00:00:00:00')
  })

  it('J, K e L voltam, param e avançam, e repetir dobra a velocidade', async () => {
    const panel = await mountPlayer()
    const player = usePlayerStore()
    const press = async (key: string) => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
      await flushPromises()
    }
    await press('l')
    expect(player.rate).toBe(1)
    await press('L')
    expect(player.rate).toBe(2)
    expect(panel.find('.transport__speed').text()).toBe('2x')
    await press('j')
    expect(player.rate).toBe(-1)
    await press('k')
    expect(player.rate).toBe(0)
  })

  it('os atalhos não valem dentro de um campo de texto nem com Ctrl', async () => {
    await mountPlayer()
    const player = usePlayerStore()
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'l', bubbles: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'l', ctrlKey: true, bubbles: true }))
    await flushPromises()
    expect(player.rate).toBe(0)
  })

  it('o volume do player é um controle de 0 a 100%', async () => {
    const panel = await mountPlayer()
    const slider = panel.find('input[type="range"]')
    await slider.setValue('0.5')
    expect(usePlayerStore().volume).toBe(0.5)
    expect(panel.find('.transport__volume output').text()).toBe('50%')
  })

  it('fechar o painel para o relógio e solta os áudios', async () => {
    await mountPlayer()
    usePlayerStore().play()
    opened.store.setPlayhead(2)
    await flushPromises()
    wrapper?.unmount()
    wrapper = null
    expect(usePlayerStore().playing).toBe(false)
    expect(audioElements()).toHaveLength(0)
  })
})
