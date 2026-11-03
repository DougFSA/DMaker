<script setup lang="ts">
/* Pronúncia: o dicionário de como a voz fala siglas e nomes, global ou de uma marca. A lista, o formulário de
   adicionar e a frase de "Ouvir" ficam numa tela só. A casca da área Voz (VoiceShellView) já traz o título e as abas. */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { PronunciationEntry } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MediaPlayer from '@/components/ui/MediaPlayer.vue'
import PronunciationList from '@/components/voice/PronunciationList.vue'
import { useConfirm } from '@/composables/useConfirm'
import { brandOptions, languageLabel } from '@/lib/voice'
import { useCatalogStore } from '@/stores/catalog'
import { useNarrationStore } from '@/stores/narration'
import { usePronunciationStore } from '@/stores/pronunciation'
import { useToastsStore } from '@/stores/toasts'
import { useVoiceStore } from '@/stores/voice'

const pronunciation = usePronunciationStore()
const narration = useNarrationStore()
const voices = useVoiceStore()
const catalog = useCatalogStore()
const toasts = useToastsStore()
const confirm = useConfirm()

const player = ref<InstanceType<typeof MediaPlayer> | null>(null)
const brands = computed(() => brandOptions(catalog.brands))
const languages = computed(() => voices.options?.languages ?? [])
const voiceName = computed(() => narration.voiceList.find((voice) => voice.id === narration.voiceId)?.name ?? 'a voz automática')

onMounted(() => {
  void pronunciation.load()
  // Ouvir fala com a voz escolhida na Narração, então a lista de vozes precisa estar à mão
  void narration.loadVoices()
  void voices.loadOptions().catch(() => undefined)
  void catalog.load().catch(() => undefined)
})

// a frase pronta toca sozinha; o navegador pode recusar (autoplay) e então o player fica à vista
watch(
  () => pronunciation.sample?.stamp,
  async () => {
    await nextTick()
    try {
      await player.value?.play()
    } catch {
      toasts.push({ tone: 'info', title: 'Frase pronta', description: 'Use o player abaixo da lista para ouvir.' })
    }
  },
)

async function remove(entry: PronunciationEntry): Promise<void> {
  const accepted = await confirm({
    title: `Tirar "${entry.term}" do dicionário?`,
    description: `Idioma: ${languageLabel(entry.language, languages.value)}. A voz volta a ler o termo do jeito dela.`,
    confirmLabel: 'Tirar',
    tone: 'danger',
  })
  if (accepted) await pronunciation.remove(entry)
}
</script>

<template>
  <div class="pronunciation">
    <AppCard
      title="Dicionário de pronúncia"
      subtitle="Como a voz fala siglas, marcas e nomes estrangeiros. A legenda continua mostrando o termo como está escrito."
    >
      <div class="stack">
        <AppSelect
          :model-value="pronunciation.brand"
          label="Dicionário"
          placeholder="Global (todas as marcas)"
          :options="brands"
          @update:model-value="pronunciation.setBrand"
        />

        <p v-if="pronunciation.loading && pronunciation.entries.length === 0" class="note" role="status">Carregando...</p>

        <div v-else-if="pronunciation.failure" class="failure" role="alert">
          <p>{{ pronunciation.failure }}</p>
          <AppButton size="sm" @click="pronunciation.load()">Tentar de novo</AppButton>
        </div>

        <EmptyState
          v-else-if="pronunciation.entries.length === 0"
          icon="languages"
          title="Nenhum termo ainda"
          description="Adicione abaixo o primeiro termo e como a voz deve falá-lo."
        />

        <PronunciationList
          v-else
          :entries="pronunciation.entries"
          :languages="languages"
          :brands="brands"
          :listening="pronunciation.listening"
          @listen="pronunciation.listen($event)"
          @remove="remove"
        />

        <p class="note">Ouvir gera uma frase curta com {{ voiceName }}, a voz escolhida em Narração.</p>

        <MediaPlayer
          v-if="pronunciation.sample"
          ref="player"
          kind="audio"
          :title="`Como a voz fala ${pronunciation.sample.term}`"
          :src="pronunciation.sample.url"
          :refresh-key="pronunciation.sample.stamp"
        />
      </div>
    </AppCard>

    <AppCard title="Adicionar termo" subtitle="Vale no dicionário aberto acima.">
      <form class="stack" @submit.prevent="pronunciation.add()">
        <AppInput v-model="pronunciation.term" label="Termo" placeholder="Ex.: DMaker" />
        <AppInput v-model="pronunciation.spoken" label="Falar como" placeholder="Ex.: Di-mêiker" />
        <AppSelect v-model="pronunciation.language" label="Idioma da fala" :options="languages" />
        <div>
          <AppButton type="submit" variant="primary" :loading="pronunciation.adding" :disabled="!pronunciation.canAdd">
            Adicionar
          </AppButton>
        </div>
      </form>
    </AppCard>
  </div>
</template>

<style scoped>
.pronunciation {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
}

/* a partir de 1100 px a lista e o formulário ficam lado a lado (a interface responde até 1280 px) */
@media (min-width: 1100px) {
  .pronunciation {
    grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
  }
}

.stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.failure {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-error);
}
</style>
