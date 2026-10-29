/* O servidor de mentira da tela de Modelos: guarda o inventário (modelos e sobras) e o muda como o de verdade quando a
   tela baixa, apaga ou limpa sobras. Os trabalhos de download ganham um `job_id` e o teste empurra os eventos pelo
   EventSource falso. */
import { vi } from 'vitest'
import type { ModelInventory, ModelLeftover, ModelState, ModelStatus } from '@/api'
import type { ServerCall } from './speechServer'

export function modelStatus(over: Partial<ModelStatus> = {}): ModelStatus {
  return {
    id: 'omnivoice',
    name: 'OmniVoice',
    purpose: 'Fala em mais de 600 idiomas e clona voz.',
    engine: 'omnivoice',
    license: 'Apache-2.0',
    required_by: ['Narração', 'Dublagem'],
    state: 'installed',
    size_bytes: 3_267_869_931,
    size_label: '3,04 GB',
    expected_bytes: 3_267_869_931,
    expected_label: '3,04 GB',
    ...over,
  }
}

/** Os três estados de uma vez, com nomes de mentira: um inteiro, um pela metade e um que nem foi baixado. */
export const DEFAULT_MODELS: ModelStatus[] = [
  modelStatus(),
  modelStatus({
    id: 'demucs-htdemucs',
    name: 'Demucs htdemucs',
    purpose: 'Separa a voz da música e do ruído de fundo.',
    license: 'MIT',
    required_by: ['Isolamento vocal'],
    state: 'partial',
    size_bytes: 41_943_040,
    size_label: '40,0 MB',
    expected_bytes: 84_025_501,
    expected_label: '80,1 MB',
  }),
  modelStatus({
    id: 'audioseal',
    name: 'AudioSeal (marca d\'água)',
    purpose: 'Grava e confere a marca inaudível de voz gerada por IA.',
    license: 'MIT',
    required_by: [],
    state: 'absent',
    size_bytes: 0,
    size_label: '0 B',
    expected_bytes: 93_473_621,
    expected_label: '89,1 MB',
  }),
]

export const LEFTOVER_FILE: ModelLeftover = { path: 'velho/modelo.bin', size_bytes: 2_097_152, size_label: '2,0 MB', is_dir: false }
export const LEFTOVER_DIR: ModelLeftover = { path: 'restos', size_bytes: 1_048_576, size_label: '1,0 MB', is_dir: true }

export interface ModelsServerOptions {
  models?: ModelStatus[]
  leftovers?: ModelLeftover[]
  /** Faz a medição do disco falhar com esta mensagem (500). */
  inventoryError?: string
  /** Faz apagar falhar com esta mensagem (409), como o servidor faz com um download em andamento. */
  removeError?: string
  /** Faz limpar as sobras falhar com esta mensagem (409). */
  pruneError?: string
}

export interface ModelsServer {
  calls: ServerCall[]
  /** O inventário como o servidor o guarda agora; muda quando a tela apaga ou limpa. */
  models: ModelStatus[]
  leftovers: ModelLeftover[]
  /** Faz o servidor medir um estado novo, como se o download tivesse terminado. */
  setState: (modelId: string, state: ModelState) => void
}

function inventoryOf(server: ModelsServer): ModelInventory {
  const left = server.leftovers.reduce((sum, item) => sum + item.size_bytes, 0)
  return {
    models_dir: 'X:/dados-de-teste/cache/models',
    models: server.models,
    leftovers: server.leftovers,
    total_bytes: 4_000_000_000,
    total_label: '3,73 GB',
    leftover_bytes: left,
    leftover_label: left ? `${(left / 1_048_576).toFixed(1).replace('.', ',')} MB` : '0 B',
    disk_free_bytes: 50_000_000_000,
    disk_free_label: '46,57 GB',
  }
}

/** Instala o `fetch` falso e devolve o servidor (as chamadas na ordem e o inventário vivo). */
export function stubModelsServer(options: ModelsServerOptions = {}): ModelsServer {
  const server: ModelsServer = {
    calls: [],
    models: (options.models ?? DEFAULT_MODELS).map((model) => ({ ...model })),
    leftovers: [...(options.leftovers ?? [])],
    setState(modelId, state) {
      this.models = this.models.map((model) =>
        model.id === modelId
          ? {
              ...model,
              state,
              size_bytes: state === 'absent' ? 0 : model.expected_bytes,
              size_label: state === 'absent' ? '0 B' : model.expected_label,
            }
          : model,
      )
    },
  }
  let jobs = 0

  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      const body = init.body ? JSON.parse(String(init.body)) : undefined
      server.calls.push({ method, url, body })
      const reply = (payload: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(payload), { status }))
      const path = url.split('?')[0]!

      if (path === '/api/models' && method === 'GET') {
        return options.inventoryError ? reply({ detail: options.inventoryError }, 500) : reply(inventoryOf(server))
      }
      if (path === '/api/models/prune') {
        if (options.pruneError) return reply({ detail: options.pruneError }, 409)
        const wanted = new Set<string>(body.paths ?? server.leftovers.map((item) => item.path))
        const removed = server.leftovers.filter((item) => wanted.has(item.path))
        server.leftovers = server.leftovers.filter((item) => !wanted.has(item.path))
        const freed = removed.reduce((sum, item) => sum + item.size_bytes, 0)
        return reply({
          removed: { title: `${removed.length} item(ns) que nenhum modelo usa`, paths: removed.map((item) => item.path), freed_bytes: freed, freed_label: `${(freed / 1_048_576).toFixed(1).replace('.', ',')} MB`, stops_working: [], warning: '' },
        })
      }
      const model = /^\/api\/models\/([^/]+)\/(removal|download|remove)$/.exec(path ?? '')
      if (model) {
        const [, id, action] = model
        const found = server.models.find((candidate) => candidate.id === id)
        if (!found) return reply({ detail: `Modelo '${id}' não existe.` }, 404)
        if (action === 'removal') {
          return reply({
            title: found.name,
            paths: [found.id],
            freed_bytes: found.size_bytes,
            freed_label: found.size_label,
            stops_working: found.required_by,
            warning: `Vai apagar ${found.name} e liberar ${found.size_label}. Estas funções deixam de funcionar até o modelo ser baixado de novo: ${found.required_by.join('; ')}.`,
          })
        }
        if (action === 'download') {
          jobs += 1
          return reply({ job_id: `j${jobs}` })
        }
        if (options.removeError) return reply({ detail: options.removeError }, 409)
        server.setState(found.id, 'absent')
        return reply({
          removed: { title: found.name, paths: [found.id], freed_bytes: found.size_bytes, freed_label: found.size_label, stops_working: found.required_by, warning: '' },
        })
      }
      return reply({ detail: `rota sem resposta no teste: ${method} ${url}` }, 404)
    }),
  )
  return server
}
