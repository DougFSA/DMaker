/* Os anexos da conversa com o agente: que tipo de arquivo é cada um, a ficha que a tela mostra e os avisos de antes de
   enviar (funções puras). Quem decide de verdade é o servidor; a tela só avisa antes, para a pessoa não esperar um
   envio que ele vai recusar. */
import type { AgentAttachment, AgentAttachmentSummary, AgentMode, AgentModel, AttachmentKind } from '@/api'
import { imageModels, readsImages } from './agentModels'
import { formatBytes } from './files'

/** O máximo de anexos numa mensagem; o servidor recusa mais que isso (422). */
export const MAX_ATTACHMENTS = 8

/** As extensões de cada tipo: as mesmas que o servidor classifica (agent/attachments.py), para a tela dar o aviso certo. */
const EXTENSIONS: Record<AttachmentKind, readonly string[]> = {
  image: ['.png', '.jpg', '.jpeg', '.webp'],
  sheet: ['.csv', '.xlsx'],
  text: ['.txt', '.md', '.markdown', '.srt', '.docx', '.pdf'],
  media: [
    '.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v', '.gif', '.bmp', '.tif', '.tiff',
    '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.wma',
  ],
}
const AUDIO_EXTENSIONS = new Set(['.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.wma'])

/** O `accept` do seletor de arquivos: tudo o que o servidor sabe anexar. */
export const ATTACHMENT_ACCEPT = Object.values(EXTENSIONS).flat().join(',')

/** O que o seletor diz quando recusa um arquivo, em vez da lista de extensões. */
export const ATTACHMENT_ACCEPT_LABEL = 'imagem (PNG, JPG, WebP), vídeo, áudio, planilha (CSV, XLSX) e texto (TXT, MD, SRT, DOCX, PDF)'

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot).toLowerCase()
}

/** O tipo do arquivo pelo nome, ou `null` quando o servidor não conhece a extensão (e vai recusar com a lista dos aceitos). */
export function attachmentKindOf(name: string): AttachmentKind | null {
  const extension = extensionOf(name)
  for (const kind of Object.keys(EXTENSIONS) as AttachmentKind[]) {
    if (EXTENSIONS[kind].includes(extension)) return kind
  }
  return null
}

// ---------- a ficha ----------

export type CardState = 'uploading' | 'ready' | 'error'

/** Uma ficha de anexo: o arquivo que está subindo, o que já está no servidor, o que falhou ou o que foi enviado numa mensagem. */
export interface AttachmentCard {
  /** Identifica a ficha na lista; o id do servidor quando ele existe. */
  key: string
  state: CardState
  kind: AttachmentKind | null
  name: string
  size: number
  /** O id no servidor; vazio enquanto sobe ou se falhou. */
  id: string | null
  /** Texto: quantos caracteres vão ao modelo e quantos o arquivo tem. */
  chars: number | null
  totalChars: number | null
  truncated: boolean
  /** O motivo da falha, em português. */
  error: string
}

export function cardOfAttachment(attachment: AgentAttachment): AttachmentCard {
  return {
    key: attachment.id,
    state: 'ready',
    kind: attachment.kind,
    name: attachment.name,
    size: attachment.size,
    id: attachment.id,
    chars: attachment.chars ?? null,
    totalChars: attachment.total_chars ?? null,
    truncated: attachment.truncated === true,
    error: '',
  }
}

/** A ficha de uma mensagem já enviada (o resumo da transcrição). */
export function cardOfSummary(summary: AgentAttachmentSummary): AttachmentCard {
  return {
    key: summary.id,
    state: 'ready',
    kind: summary.kind,
    name: summary.name,
    size: summary.size,
    id: summary.id,
    chars: summary.chars ?? null,
    totalChars: summary.total_chars ?? null,
    truncated: summary.truncated === true,
    error: '',
  }
}

/** O arquivo que acabou de ser escolhido e ainda sobe: o tipo vem do nome. */
export function uploadingCard(key: string, file: { name: string; size: number }): AttachmentCard {
  return {
    key,
    state: 'uploading',
    kind: attachmentKindOf(file.name),
    name: file.name,
    size: file.size,
    id: null,
    chars: null,
    totalChars: null,
    truncated: false,
    error: '',
  }
}

export function failedCard(card: AttachmentCard, error: string): AttachmentCard {
  return { ...card, state: 'error', error }
}

const KIND_LABELS: Record<AttachmentKind, string> = {
  image: 'Imagem',
  media: 'Vídeo',
  sheet: 'Planilha',
  text: 'Documento',
}

/** "Imagem", "Vídeo", "Áudio", "Planilha" ou "Documento"; "Arquivo" enquanto o tipo não se conhece. */
export function kindLabel(card: Pick<AttachmentCard, 'kind' | 'name'>): string {
  if (!card.kind) return 'Arquivo'
  if (card.kind === 'media' && AUDIO_EXTENSIONS.has(extensionOf(card.name))) return 'Áudio'
  return KIND_LABELS[card.kind]
}

const integer = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 })

/** "cortado: 12.400 de 38.000 caracteres" quando o texto não cabe no contexto do modelo; vazio quando vai inteiro. */
export function cutNote(card: Pick<AttachmentCard, 'truncated' | 'chars' | 'totalChars'>): string {
  if (!card.truncated || card.totalChars === null) return ''
  return `cortado: ${integer.format(card.chars ?? 0)} de ${integer.format(card.totalChars)} caracteres`
}

/** "Documento · 20 KB": o tipo e o tamanho que a ficha mostra. */
export function cardDetail(card: AttachmentCard): string {
  return [kindLabel(card), formatBytes(card.size)].join(' · ')
}

/** O texto da mensagem que só leva anexo: o servidor exige ao menos uma palavra. */
export function attachmentOnlyMessage(count: number): string {
  if (count <= 0) return ''
  return count === 1 ? 'Veja o anexo.' : 'Veja os anexos.'
}

// ---------- o que a tela recusa ao escolher ----------

function listNames(names: string[]): string {
  return names.join(', ')
}

/**
 * Separa o que entra do que a tela recusa já na escolha: vídeo e áudio numa Conversa livre (o servidor recusaria, e a
 * conversa nem precisa nascer) e o que passa do máximo de anexos da mensagem. `room` é quantos ainda cabem.
 */
export function splitPicked<T extends { name: string }>(
  files: T[],
  mode: AgentMode,
  room: number,
): { accepted: T[]; notices: string[] } {
  const notices: string[] = []
  let candidates = files
  if (mode === 'free') {
    const media = files.filter((file) => attachmentKindOf(file.name) === 'media')
    if (media.length) {
      candidates = files.filter((file) => !media.includes(file))
      notices.push(
        `Numa Conversa livre, o vídeo ou áudio não é usado (${listNames(media.map((file) => file.name))}): é o modo Operar o DMaker que trabalha com ele.`,
      )
    }
  }
  const fits = Math.max(0, room)
  const accepted = candidates.slice(0, fits)
  const over = candidates.slice(fits)
  if (over.length) {
    notices.push(`Uma mensagem leva no máximo ${MAX_ATTACHMENTS} anexos. Não anexei: ${listNames(over.map((file) => file.name))}.`)
  }
  return { accepted, notices }
}

// ---------- os avisos de antes de enviar ----------

export interface AttachmentWarning {
  code: 'image_without_vision' | 'media_in_free_chat'
  text: string
  /** Os modelos que resolvem, para a pessoa trocar com um clique. */
  models: string[]
}

/** O que vale saber sobre os anexos e não segura o envio. */
export interface AttachmentInfo {
  code: 'image_as_file'
  text: string
}

/** No modo Operar a imagem é também arquivo de trabalho: o modelo que não a enxerga ainda a recebe como caminho. */
export const IMAGE_AS_FILE_TEXT = 'O modelo não vê a imagem, mas pode usá-la no vídeo.'

/** Só a Conversa livre chega aqui: ali a imagem existe para o modelo olhar, então ele precisa enxergar. */
function imageWarning(model: AgentModel, installed: AgentModel[]): AttachmentWarning {
  const seeing = imageModels(installed)
  if (seeing.length) {
    return {
      code: 'image_without_vision',
      text: `O modelo ${model.name} não lê imagem. Escolha um modelo com o selo Imagem: ${seeing.map((item) => item.name).join(', ')}.`,
      models: seeing.map((item) => item.name),
    }
  }
  return {
    code: 'image_without_vision',
    text: `O modelo ${model.name} não lê imagem, e nenhum modelo instalado lê imagem. Instale um com o selo Imagem no Ollama para usar este anexo.`,
    models: [],
  }
}

/**
 * O que impede a mensagem de seguir com estes anexos, como o servidor decidiria: imagem para um modelo que não lê
 * imagem numa Conversa livre e vídeo ou áudio numa Conversa livre. Quem opera o DMaker usa a imagem também como arquivo,
 * então ali o modelo sem visão não é barrado (ver `attachmentInfos`). Só as fichas já no servidor contam. Enquanto houver
 * aviso, o envio fica parado.
 */
export function attachmentWarnings(
  cards: AttachmentCard[],
  mode: AgentMode,
  model: AgentModel | undefined,
  installed: AgentModel[],
): AttachmentWarning[] {
  const ready = cards.filter((card) => card.state === 'ready')
  const warnings: AttachmentWarning[] = []
  if (mode === 'free' && model && !readsImages(model) && ready.some((card) => card.kind === 'image')) {
    warnings.push(imageWarning(model, installed))
  }
  if (mode === 'free' && ready.some((card) => card.kind === 'media')) {
    warnings.push({
      code: 'media_in_free_chat',
      text: 'Numa Conversa livre, o vídeo ou áudio anexado não é usado: é o modo Operar o DMaker que trabalha com ele. Troque o modo ou remova o anexo.',
      models: [],
    })
  }
  return warnings
}

/** O que a pessoa deve saber antes de enviar e que não impede o envio: a imagem anexada a um modelo que não a enxerga, no modo Operar. */
export function attachmentInfos(
  cards: AttachmentCard[],
  mode: AgentMode,
  model: AgentModel | undefined,
): AttachmentInfo[] {
  const hasImage = cards.some((card) => card.state === 'ready' && card.kind === 'image')
  if (mode === 'operate' && model && !readsImages(model) && hasImage) {
    return [{ code: 'image_as_file', text: IMAGE_AS_FILE_TEXT }]
  }
  return []
}

/** Os modelos que o servidor sugeriu ao recusar uma imagem (`suggested_models` no corpo cru do 422). */
export function suggestedModelsOf(failure: unknown): string[] {
  if (!failure || typeof failure !== 'object' || !('detail' in failure)) return []
  const body = (failure as { detail: unknown }).detail
  if (!body || typeof body !== 'object' || !('suggested_models' in body)) return []
  const names = (body as { suggested_models: unknown }).suggested_models
  return Array.isArray(names) ? names.filter((name): name is string => typeof name === 'string') : []
}
