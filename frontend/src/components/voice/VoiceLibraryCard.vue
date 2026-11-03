<script setup lang="ts">
/* A biblioteca de vozes: filtro por marca e, em cada voz, Ouvir (gera uma amostra e toca), Usar (leva a voz para o
   roteiro da Narração) e Remover (com confirmação). */
import { nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { errorMessage, type VoiceOption } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MediaPlayer from '@/components/ui/MediaPlayer.vue'
import VoiceListItem from '@/components/voice/VoiceListItem.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useNow } from '@/composables/useNow'
import { previewStatus } from '@/lib/voice'
import { useToastsStore } from '@/stores/toasts'
import { useVoiceStore } from '@/stores/voice'

defineProps<{ languages: VoiceOption[]; brands: VoiceOption[] }>()

const voices = useVoiceStore()
const toasts = useToastsStore()
const confirm = useConfirm()
const router = useRouter()
const now = useNow()

const brand = ref(voices.brandFilter)
const player = ref<InstanceType<typeof MediaPlayer> | null>(null)

watch(brand, (value) => void voices.setBrandFilter(value))

// a amostra pronta toca sozinha; o navegador pode recusar (política de autoplay) e então o player fica à vista
watch(
  () => voices.sample?.stamp,
  async () => {
    await nextTick()
    try {
      await player.value?.play()
    } catch {
      toasts.push({ tone: 'info', title: 'Amostra pronta', description: 'Use o player abaixo da lista para ouvir.' })
    }
  },
)

function statusOf(voiceId: string) {
  return previewStatus(voices.previews[voiceId], now.value)
}

function isPreviewing(voiceId: string): boolean {
  const preview = voices.previews[voiceId]
  return !!preview && !preview.error
}

function use(voiceId: string, name: string): void {
  voices.chooseVoice(voiceId)
  toasts.push({
    tone: 'success',
    title: `Voz "${name}" escolhida`,
    description: 'Ela será a voz do roteiro na Narração.',
    action: { label: 'Abrir a Narração', run: () => void router.push('/voz/narracao') },
  })
}

async function remove(voiceId: string, name: string): Promise<void> {
  const accepted = await confirm({
    title: `Remover a voz "${name}"?`,
    description: 'Isso apaga a gravação de referência dela. Não dá para desfazer.',
    confirmLabel: 'Remover',
    tone: 'danger',
  })
  if (!accepted) return
  try {
    await voices.remove(voiceId)
    toasts.push({ tone: 'success', title: 'Voz removida', description: name })
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não consegui remover a voz', description: errorMessage(error) })
  }
}
</script>

<template>
  <AppCard title="Biblioteca" subtitle="As vozes prontas, clonadas e desenhadas que a narração pode usar.">
    <div class="library">
      <AppSelect v-model="brand" label="Mostrar" :options="brands" placeholder="Todas as vozes" />

      <p v-if="voices.loading && voices.voices.length === 0" class="library__note" role="status">Carregando vozes...</p>

      <div v-else-if="voices.failure" class="library__failure" role="alert">
        <p>{{ voices.failure }}</p>
        <AppButton size="sm" @click="voices.loadVoices()">Tentar de novo</AppButton>
      </div>

      <EmptyState
        v-else-if="voices.voices.length === 0"
        icon="mic"
        title="Nenhuma voz ainda"
        description="Clone uma voz a partir de uma gravação ou desenhe uma pela descrição."
      />

      <ul v-else class="library__list" aria-label="Vozes da biblioteca">
        <VoiceListItem
          v-for="voice in voices.voices"
          :key="voice.id"
          :voice="voice"
          :languages="languages"
          :selected="voice.id === voices.selectedVoiceId"
          :status="statusOf(voice.id).text"
          :failed="statusOf(voice.id).failed"
          :previewing="isPreviewing(voice.id)"
          @preview="voices.preview(voice.id)"
          @use="use(voice.id, voice.name)"
          @remove="remove(voice.id, voice.name)"
        />
      </ul>

      <MediaPlayer
        v-if="voices.sample"
        ref="player"
        kind="audio"
        :title="`Amostra de ${voices.sample.voiceName}`"
        :src="voices.sample.url"
        :refresh-key="voices.sample.stamp"
      />
    </div>
  </AppCard>
</template>

<style scoped>
.library {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.library__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.library__note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.library__failure {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-error);
}
</style>
