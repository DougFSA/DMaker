/* Dados de mentira do editor para os testes: um projeto, a vista dele e o que as rotas do servidor devolvem. */
import type { OutputFile, ProjectDetail, TimelineItem, TimelineTrack, TimelineView } from '@/api'

export function timelineItem(index: number, extra: Partial<TimelineItem> = {}): TimelineItem {
  return {
    id: `V1:${index}`,
    kind: 'clip',
    index,
    label: `trecho ${index}`,
    start: index * 3,
    end: index * 3 + 3,
    in_point: 0,
    out_point: 3,
    src: `clip${index}.mp4`,
    source: null,
    transition: null,
    muted: false,
    extra: {},
    path: null,
    ...extra,
  }
}

export function timelineTrack(id: string, items: TimelineItem[], extra: Partial<TimelineTrack> = {}): TimelineTrack {
  return { id, kind: 'video', label: id, muted: false, hidden: false, locked: false, items, ...extra }
}

export function timelineView(items: TimelineItem[] = [timelineItem(0), timelineItem(1)]): TimelineView {
  return {
    total: items.length * 3,
    fps: 30,
    width: 1080,
    height: 1920,
    tracks: [timelineTrack('V1', items)],
    sources: {},
    warnings: [],
  }
}

/** A spec que o servidor devolve ao abrir um projeto: já com os padrões preenchidos. */
export function projectSpec(): Record<string, unknown> {
  return {
    name: 'demo',
    version: 1,
    output: { preset: 'instagram/reels', encoder: 'x264', quality: 'high', guides: false },
    brand: 'medlycare',
    sources: {},
    timeline: [
      { type: 'clip', src: 'clip0.mp4', start: 0, end: 3, speed: 1, volume: 1, mute: false, fade_in: 0, fade_out: 0 },
      { type: 'card', title: 'Fim', duration: 3, logo: true, motion: 'zoom-in', motion_amount: 0.04 },
    ],
    overlays: [{ type: 'text', text: 'Olá', role: 'title', start: 0 }],
    audio: { voice_gain: 1, normalize: 'two-pass', mute_clips: false },
  }
}

export function outputFile(extra: Partial<OutputFile> = {}): OutputFile {
  return {
    path: 'C:/out/demo__instagram-reels.mp4',
    url: '/api/file?path=C%3A%2Fout%2Fdemo__instagram-reels.mp4',
    name: 'demo__instagram-reels.mp4',
    project: 'demo',
    preset: 'instagram/reels',
    kind: 'final',
    size_mb: 4.2,
    mtime: 1_700_000_000,
    thumbnail: null,
    ...extra,
  }
}

export function projectDetail(extra: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    name: 'demo',
    spec_path: 'C:/projects/demo/spec.json',
    spec: projectSpec() as ProjectDetail['spec'],
    captions_exists: false,
    outputs: [],
    cuts: null,
    ...extra,
  }
}

/** O pedaço do schema que os formulários do teste consultam (as listas e os limites principais). */
export const editorSchema = {
  $defs: {
    Output: {
      properties: {
        preset: { default: 'instagram/reels', type: 'string' },
        fps: { anyOf: [{ exclusiveMinimum: 0, maximum: 120, type: 'number' }, { type: 'null' }], default: null },
        encoder: { default: 'x264', enum: ['x264', 'auto', 'nvenc', 'amf', 'qsv'], type: 'string' },
        quality: { default: 'high', enum: ['max', 'high', 'medium', 'draft'], type: 'string' },
        guides: { default: false, type: 'boolean' },
      },
    },
    ClipSegment: {
      properties: {
        start: { default: 0, minimum: 0, type: 'number' },
        end: { anyOf: [{ minimum: 0, type: 'number' }, { type: 'null' }], default: null },
        speed: { default: 1, exclusiveMinimum: 0, maximum: 8, type: 'number' },
        volume: { default: 1, maximum: 4, minimum: 0, type: 'number' },
        mute: { default: false, type: 'boolean' },
        fade_in: { default: 0, minimum: 0, type: 'number' },
        fade_out: { default: 0, minimum: 0, type: 'number' },
        label: { anyOf: [{ type: 'string' }, { type: 'null' }], default: null },
      },
    },
    ImageSegment: {
      properties: {
        motion: { default: 'zoom-in', enum: ['none', 'zoom-in', 'zoom-out', 'pan-left', 'pan-right'], type: 'string' },
        duration: { default: 3, exclusiveMinimum: 0, type: 'number' },
      },
    },
    CardSegment: {
      properties: {
        title: { default: '', type: 'string' },
        duration: { default: 3, exclusiveMinimum: 0, type: 'number' },
        variant: { anyOf: [{ enum: ['light', 'dark'], type: 'string' }, { type: 'null' }], default: null },
        logo: { default: true, type: 'boolean' },
        motion: { default: 'zoom-in', enum: ['none', 'zoom-in'], type: 'string' },
        motion_amount: { default: 0.04, maximum: 0.3, minimum: 0, type: 'number' },
      },
    },
    Transition: {
      properties: {
        type: { default: 'fade', type: 'string' },
        duration: { default: 0.5, exclusiveMinimum: 0, maximum: 5, type: 'number' },
      },
    },
    Reframe: {
      properties: {
        mode: { default: 'auto', enum: ['auto', 'crop', 'pad', 'blur', 'brand', 'stretch'], type: 'string' },
        focus: { default: [0.5, 0.5], type: 'array' },
      },
    },
    TextOverlay: {
      properties: {
        role: { default: 'title', enum: ['hook', 'title', 'subtitle', 'cta', 'lower-third', 'custom'], type: 'string' },
        position: { anyOf: [{ enum: ['top', 'center', 'bottom'], type: 'string' }, { type: 'null' }], default: null },
        animation: {
          anyOf: [{ enum: ['none', 'fade', 'pop', 'slide-up', 'typewriter'], type: 'string' }, { type: 'null' }],
          default: null,
        },
        start: { default: 0, minimum: 0, type: 'number' },
      },
    },
    Captions: { properties: { model: { default: 'small', type: 'string' }, language: { default: 'pt', type: 'string' } } },
    CaptionStyle: {
      properties: {
        mode: { default: 'karaoke', enum: ['karaoke', 'classic', 'boxed', 'rounded'], type: 'string' },
        max_words: { default: 4, maximum: 12, minimum: 1, type: 'integer' },
      },
    },
    AudioSettings: {
      properties: {
        voice_gain: { default: 1, maximum: 4, minimum: 0, type: 'number' },
        normalize: { default: 'two-pass', enum: ['two-pass', 'fast', 'off'], type: 'string' },
        mute_clips: { default: false, type: 'boolean' },
      },
    },
    Music: {
      properties: {
        volume: { default: 0.18, maximum: 2, minimum: 0, type: 'number' },
        ducking: { default: true, type: 'boolean' },
      },
    },
  },
} as Record<string, unknown>
