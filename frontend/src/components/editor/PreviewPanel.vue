<script setup lang="ts">
/* A aba Preview: o vídeo já renderizado do projeto e a conferência dele (relatório de QA, grade de quadros e um
   quadro num instante). Serve para olhar o resultado; o player da edição ao vivo é outro painel. */
import { computed, ref, watch } from 'vue'
import { api, errorMessage, type QaReport } from '@/api'
import QaReportCard from '@/components/projects/QaReportCard.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { bustCache } from '@/lib/files'
import { baseName, formatSizeMb } from '@/lib/format'
import { useCatalogStore } from '@/stores/catalog'
import { useEditorStore } from '@/stores/editor'
import { useToastsStore } from '@/stores/toasts'

const editor = useEditorStore()
const catalog = useCatalogStore()
const toasts = useToastsStore()

const chosen = ref('')
const report = ref<QaReport | null>(null)
const sheetUrl = ref('')
const frameUrl = ref('')
const frameAt = ref<number | null>(0)
const busy = ref<'qa' | 'sheet' | 'frame' | null>(null)

void catalog.load().catch(() => undefined)

const files = computed(() => [...editor.outputs].sort((a, b) => b.mtime - a.mtime))
const current = computed(() => files.value.find((file) => file.path === chosen.value) ?? files.value[0] ?? null)
const options = computed(() =>
  files.value.map((file) => ({
    value: file.path,
    label: `${file.name} · ${file.kind === 'preview' ? 'prévia' : 'final'} · ${formatSizeMb(file.size_mb)}`,
  })),
)
const portrait = computed(() => {
  const preset = catalog.presets.find((item) => item.id === current.value?.preset)
  return preset ? preset.width < preset.height : true
})
const folder = computed(() => current.value?.path.replace(/[\\/][^\\/]*$/, '') ?? '')

// um render novo chegou: o arquivo mais recente volta a ser o mostrado, mesmo que a pessoa tenha escolhido outro antes
watch(
  () => files.value[0]?.path,
  () => {
    chosen.value = ''
  },
)

// outro arquivo, outro resultado: o que foi conferido do anterior não vale para este
watch(
  () => current.value?.path,
  () => {
    report.value = null
    sheetUrl.value = ''
    frameUrl.value = ''
  },
)

async function runQa(): Promise<void> {
  if (!editor.name) return
  busy.value = 'qa'
  try {
    report.value = await api.projects.qa(editor.name, current.value?.path)
  } catch (error) {
    toasts.push({ tone: 'error', title: 'A conferência de qualidade falhou', description: errorMessage(error) })
  } finally {
    busy.value = null
  }
}

async function makeSheet(): Promise<void> {
  if (!current.value) return
  busy.value = 'sheet'
  try {
    const result = await api.editor.qa.sheet({ video: current.value.path })
    sheetUrl.value = result.url ? bustCache(result.url, Date.now()) : ''
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não foi possível montar a grade de quadros', description: errorMessage(error) })
  } finally {
    busy.value = null
  }
}

async function makeFrame(): Promise<void> {
  if (!current.value) return
  busy.value = 'frame'
  try {
    const result = await api.editor.qa.frame({ video: current.value.path, t: frameAt.value ?? 0 })
    frameUrl.value = result.url ? bustCache(result.url, Date.now()) : ''
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não foi possível tirar o quadro', description: errorMessage(error) })
  } finally {
    busy.value = null
  }
}

async function copyFolder(): Promise<void> {
  try {
    await navigator.clipboard.writeText(folder.value)
    toasts.push({ tone: 'success', title: 'Caminho da pasta copiado', description: folder.value })
  } catch {
    toasts.push({ tone: 'info', title: 'Pasta do arquivo', description: folder.value })
  }
}
</script>

<template>
  <div class="preview">
    <EmptyState
      v-if="!current"
      icon="video"
      title="Nenhum vídeo gerado ainda"
      description="Gere uma prévia com o botão Prévia na barra de cima. Ela aparece aqui quando ficar pronta."
    />

    <template v-else>
      <AppSelect
        v-if="files.length > 1"
        label="Arquivo"
        :model-value="current.path"
        :options="options"
        @update:model-value="chosen = $event"
      />

      <div class="preview__grid">
        <figure :class="['video', { 'video--portrait': portrait }]">
          <video :key="current.url ?? current.path" :src="current.url ?? undefined" controls playsinline preload="metadata">
            Seu navegador não consegue tocar este vídeo.
          </video>
          <figcaption>
            <strong>{{ baseName(current.path) }}</strong>
            <span class="meta">
              {{ current.preset ?? 'formato desconhecido' }} · {{ formatSizeMb(current.size_mb) }}
              <AppBadge :tone="current.kind === 'preview' ? 'neutral' : 'accent'">
                {{ current.kind === 'preview' ? 'prévia' : 'final' }}
              </AppBadge>
            </span>
            <span class="folder">
              <code>{{ folder }}</code>
              <AppButton size="sm" variant="ghost" @click="copyFolder">Copiar pasta</AppButton>
            </span>
          </figcaption>
        </figure>

        <div class="checks">
          <h4 class="checks__title">Conferir o vídeo</h4>
          <p v-if="current.kind === 'preview'" class="hint">
            A prévia é menor que a versão final e pode ter só alguns trechos: o relatório pode apontar diferença de
            duração e de resolução que não existe na final.
          </p>
          <div class="checks__buttons">
            <AppButton :loading="busy === 'qa'" :disabled="busy !== null && busy !== 'qa'" @click="runQa">
              Relatório de QA
            </AppButton>
            <AppButton :loading="busy === 'sheet'" :disabled="busy !== null && busy !== 'sheet'" @click="makeSheet">
              Grade de quadros
            </AppButton>
          </div>
          <div class="frame">
            <AppNumberInput v-model="frameAt" label="Quadro em" unit="s" :min="0" :step="0.5" />
            <AppButton :loading="busy === 'frame'" :disabled="busy !== null && busy !== 'frame'" @click="makeFrame">
              Ver o quadro
            </AppButton>
          </div>
        </div>
      </div>

      <QaReportCard v-if="report" :report="report" />
      <img v-if="sheetUrl" class="shot" :src="sheetUrl" alt="Grade de quadros do vídeo" />
      <img v-if="frameUrl" class="shot shot--frame" :src="frameUrl" alt="Quadro do vídeo no instante pedido" />
    </template>
  </div>
</template>

<style scoped>
.preview {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.preview__grid {
  display: grid;
  grid-template-columns: minmax(0, 22rem) minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
}

@media (max-width: 900px) {
  .preview__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.video {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
}

.video video {
  display: block;
  width: 100%;
  max-height: 34rem;
  border-radius: var(--radius-md);
  background: #000;
}

.video--portrait video {
  aspect-ratio: 9 / 16;
}

.video figcaption {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: var(--text-sm);
}

.meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-soft);
}

.folder {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.folder code {
  overflow: hidden;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.checks {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.checks__title {
  font-size: var(--text-md);
}

.checks__buttons,
.frame {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-3);
}

.frame > :first-child {
  width: 9rem;
}

.hint {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.shot {
  display: block;
  max-width: 100%;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.shot--frame {
  max-height: 32rem;
}
</style>
