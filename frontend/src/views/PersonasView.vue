<script setup lang="ts">
/* Personas: o cadastro das personagens que falam no vídeo (ilustrada 2D, personagem 3D e realista, a partir de uma foto). Lista as prontas (só
   leitura) e as do usuário, cria e edita (nome, tipo, voz e a aparência que cada tipo aceita), apaga com confirmação
   e mostra uma prévia curta da persona falando uma frase. O servidor valida e desenha; a tela só pede. */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, type Persona, type PersonaKind } from '@/api'
import PageHeader from '@/components/layout/PageHeader.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import FileUpload from '@/components/ui/FileUpload.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MediaPlayer from '@/components/ui/MediaPlayer.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import { useVoiceChoices } from '@/composables/useVoiceChoices'
import {
  appearanceFields,
  appearanceWithDefaults,
  capabilitySummary,
  defaultAppearance,
  KIND_LABELS,
  PHOTO_RIGHTS_NOTICE,
  previewEstimateText,
} from '@/lib/personas'
import { usePersonasStore } from '@/stores/personas'

const store = usePersonasStore()
const voices = useVoiceChoices()

/** Quem o formulário edita: `null` é uma persona nova. */
const editing = ref<Persona | null>(null)
const name = ref('')
const kind = ref<PersonaKind>('2d')
const voice = ref('')
const appearance = ref<Record<string, string>>(defaultAppearance('2d'))
const phrase = ref('')
const selectedId = ref('')
const useProject = ref('')
const useText = ref('')
const usePlacement = ref<'segment' | 'overlay'>('segment')
const projects = ref<{ value: string; label: string }[]>([])
const photo = ref<File[]>([])

const kindOptions = [
  { value: '2d', label: KIND_LABELS['2d'] },
  { value: '3d', label: KIND_LABELS['3d'] },
  { value: 'realistic', label: KIND_LABELS.realistic },
]
const MAX_PHOTO_BYTES = 25 * 1024 * 1024
const fields = computed(() => appearanceFields(kind.value))
const engine = computed(() => store.engineOf(kind.value))
const selected = computed(() => store.personas.find((persona) => persona.id === selectedId.value) ?? null)
const run = computed(() => (selected.value ? store.previews[selected.value.id] : undefined))
const result = computed(() => (selected.value ? store.previewResults[selected.value.id] : undefined))
const isRealistic = computed(() => kind.value === 'realistic')
const needsPhoto = computed(() => isRealistic.value && !editing.value)
const estimateText = computed(() => previewEstimateText(selected.value ? store.estimates[selected.value.id] : undefined))
const canSave = computed(() => !!name.value.trim() && (!needsPhoto.value || photo.value.length > 0))
let estimateTimer: ReturnType<typeof setTimeout> | undefined

watch([selected, phrase], () => {
  clearTimeout(estimateTimer)
  const persona = selected.value
  if (persona) estimateTimer = setTimeout(() => void store.loadEstimate(persona, phrase.value), 300)
})

watch(kind, (next) => {
  if (!editing.value) appearance.value = defaultAppearance(next)
})

function startNew(): void {
  editing.value = null
  name.value = ''
  kind.value = '2d'
  voice.value = ''
  appearance.value = defaultAppearance('2d')
  photo.value = []
}

function edit(persona: Persona): void {
  editing.value = persona
  selectedId.value = persona.id
  name.value = persona.name
  kind.value = persona.kind
  voice.value = persona.voice ?? ''
  appearance.value = appearanceWithDefaults(persona.kind, persona.appearance)
}

async function save(): Promise<void> {
  if (!name.value.trim()) return
  const chosenVoice = voice.value || null
  if (editing.value) {
    const updated = await store.update(editing.value.id, {
      name: name.value.trim(),
      voice: chosenVoice,
      appearance: appearance.value,
    })
    if (updated) edit(updated)
    return
  }
  const created = needsPhoto.value
    ? await store.createRealistic(name.value.trim(), chosenVoice, photo.value[0]!)
    : await store.create({ name: name.value.trim(), kind: kind.value, voice: chosenVoice, appearance: appearance.value })
  if (created) {
    selectedId.value = created.id
    photo.value = []
    edit(created)
  }
}

async function remove(persona: Persona): Promise<void> {
  if (await store.remove(persona)) {
    if (selectedId.value === persona.id) selectedId.value = ''
    if (editing.value?.id === persona.id) startNew()
  }
}

function voiceName(id: string | null): string {
  if (!id) return 'voz automática'
  return voices.options.value.find((option) => option.value === id)?.label ?? id
}

async function useInProject(): Promise<void> {
  if (!selected.value || !useProject.value || !useText.value.trim()) return
  await store.use(selected.value, { project: useProject.value, text: useText.value.trim(), placement: usePlacement.value })
}

onMounted(async () => {
  void store.load()
  try {
    projects.value = (await api.projects.list()).map((item) => ({ value: item.name, label: item.name }))
  } catch {
    projects.value = []
  }
})
</script>

<template>
  <PageHeader title="Personas" subtitle="Personagens que falam no vídeo, em tela cheia ou no canto.">
    <AppButton @click="startNew">Nova persona</AppButton>
  </PageHeader>

  <div class="personas">
    <div v-if="store.failure" class="personas__failure" role="alert">
      <p>{{ store.failure }}</p>
      <AppButton size="sm" @click="store.load()">Tentar de novo</AppButton>
    </div>

    <div class="personas__grid">
      <div class="personas__lists">
        <AppCard title="Prontas" subtitle="Vêm com o DMaker e não mudam. Para ajustar, crie uma sua.">
          <ul class="list">
            <li v-for="persona in store.builtin" :key="persona.id" :data-persona="persona.id" class="item">
              <button type="button" class="item__main" @click="selectedId = persona.id">
                <strong>{{ persona.name }}</strong>
                <AppBadge>{{ KIND_LABELS[persona.kind] }}</AppBadge>
                <span class="item__voice">{{ voiceName(persona.voice) }}</span>
              </button>
            </li>
          </ul>
        </AppCard>

        <AppCard title="Minhas personas">
          <EmptyState
            v-if="store.mine.length === 0"
            title="Nenhuma persona sua ainda"
            description="Crie uma ao lado: ela fica salva e vale em qualquer projeto."
            icon="user"
          />
          <ul v-else class="list">
            <li v-for="persona in store.mine" :key="persona.id" :data-persona="persona.id" class="item">
              <button type="button" class="item__main" @click="selectedId = persona.id">
                <img v-if="persona.photo_url" class="item__photo" :src="persona.photo_url" :alt="`Foto de ${persona.name}`" />
                <strong>{{ persona.name }}</strong>
                <AppBadge>{{ KIND_LABELS[persona.kind] }}</AppBadge>
                <span class="item__voice">{{ voiceName(persona.voice) }}</span>
              </button>
              <div class="item__actions">
                <AppButton size="sm" @click="edit(persona)">Editar</AppButton>
                <AppButton size="sm" variant="danger" @click="remove(persona)">Apagar</AppButton>
              </div>
            </li>
          </ul>
        </AppCard>

        <AppCard v-if="selected" :title="`Prévia: ${selected.name}`" subtitle="Um vídeo curto da persona falando uma frase.">
          <img v-if="selected.photo_url" class="detail__photo" :src="selected.photo_url" :alt="`Foto de ${selected.name}`" />
          <p v-if="selected.kind === 'realistic'" class="personas__caps">
            {{ capabilitySummary(selected.kind, selected.expressions, selected.gestures) }}
          </p>
          <form class="preview" @submit.prevent="store.preview(selected, phrase)">
            <AppInput v-model="phrase" label="Frase" placeholder="Deixe vazio para a frase de exemplo" :maxlength="200" />
            <div class="preview__go">
              <AppButton type="submit" variant="primary" :loading="run?.running">Ver a persona falando</AppButton>
              <p v-if="estimateText" class="preview__estimate" data-estimate>{{ estimateText }}</p>
            </div>
          </form>
          <div v-if="run?.running" class="preview__progress">
            <ProgressBar :value="run.percent" :label="run.label || 'Preparando a prévia'" />
            <p>{{ run.label }}</p>
          </div>
          <p v-if="run?.error" class="personas__error" role="alert">{{ run.error }}</p>
          <MediaPlayer v-if="result" :src="result.output_url" kind="video" :title="selected.name" :meta="[`${result.duration_s} s`]" />
        </AppCard>

        <AppCard v-if="selected" title="Usar em um projeto" subtitle="Põe a persona falando no fim do projeto, em tela cheia ou no canto.">
          <form class="preview" @submit.prevent="useInProject">
            <AppSelect v-model="useProject" label="Projeto" :options="projects" placeholder="Escolha um projeto" />
            <AppSelect
              v-model="usePlacement"
              label="Onde"
              :options="[
                { value: 'segment', label: 'Tela cheia (um trecho novo)' },
                { value: 'overlay', label: 'No canto, sobre o vídeo' },
              ]"
            />
            <AppInput v-model="useText" label="O que ela fala" />
            <AppButton type="submit" variant="primary" :disabled="!useProject || !useText.trim()">Pôr no projeto</AppButton>
          </form>
        </AppCard>
      </div>

      <AppCard :title="editing ? `Editar ${editing.name}` : 'Nova persona'">
        <form class="form" @submit.prevent="save">
          <AppInput v-model="name" label="Nome" required :maxlength="80" />
          <AppSelect v-model="kind" label="Tipo" :options="kindOptions" :disabled="!!editing" />
          <p v-if="engine?.unavailable" class="personas__notice" role="status">
            {{ engine.unavailable }}
            <RouterLink to="/modelos">Abrir a tela de Modelos</RouterLink>
          </p>
          <AppSelect v-model="voice" label="Voz" :options="voices.options.value" placeholder="Voz automática" />

          <template v-if="isRealistic && !editing">
            <FileUpload
              v-model="photo"
              label="Foto"
              accept=".jpg,.jpeg,.png"
              accept-label="jpg ou png"
              :max-bytes="MAX_PHOTO_BYTES"
              button-label="Escolher a foto"
              hint="O lado menor precisa ter pelo menos 512 px. Rosto de frente, bem iluminado e sem óculos escuros."
            />
            <p class="personas__rights" role="note">{{ PHOTO_RIGHTS_NOTICE }}</p>
          </template>

          <fieldset v-if="fields.length > 0" class="appearance">
            <legend>Aparência</legend>
            <template v-for="field in fields" :key="field.key">
              <label v-if="field.kind === 'color'" class="color">
                <span>{{ field.label }}</span>
                <input v-model="appearance[field.key]" type="color" :aria-label="field.label" />
              </label>
              <AppSelect
                v-else-if="field.kind === 'choice'"
                v-model="appearance[field.key]"
                :label="field.label"
                :options="field.options ?? []"
              />
              <AppInput v-else v-model="appearance[field.key]" :label="field.label" :hint="field.hint" />
            </template>
          </fieldset>

          <p v-if="engine" class="personas__caps">
            {{ capabilitySummary(kind, engine.expressions, engine.gestures) }}
          </p>
          <div class="form__actions">
            <AppButton type="submit" variant="primary" :loading="store.saving" :disabled="!canSave">
              {{ editing ? 'Salvar' : 'Criar persona' }}
            </AppButton>
            <AppButton v-if="editing" @click="startNew">Cancelar</AppButton>
          </div>
        </form>
      </AppCard>
    </div>
  </div>
</template>

<style scoped>
.personas {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.personas__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
  gap: var(--space-5);
  align-items: start;
}

.personas__lists {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.personas__failure,
.personas__error {
  color: var(--color-error);
}

.personas__notice {
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-warning-soft, var(--color-surface-2));
}

.personas__rights {
  color: var(--color-text-soft);
  font-size: var(--text-sm);
  font-weight: 600;
}

.item__photo {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: var(--radius-md);
  object-fit: cover;
}

.detail__photo {
  width: 7.5rem;
  border-radius: var(--radius-md);
  object-fit: cover;
}

.preview__go {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.preview__estimate {
  color: var(--color-text-soft);
  font-size: var(--text-sm);
  margin: 0;
}

.personas__caps {
  color: var(--color-text-soft);
  font-size: var(--text-sm);
}

.list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  list-style: none;
  margin: 0;
  padding: 0;
}

.item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.item__main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  border: 0;
  background: none;
  color: inherit;
  cursor: pointer;
  padding: 0;
}

.item__voice {
  color: var(--color-text-soft);
  font-size: var(--text-sm);
}

.item__actions,
.form__actions {
  display: flex;
  gap: var(--space-2);
}

.form,
.preview {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.appearance {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
}

.color {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
</style>
