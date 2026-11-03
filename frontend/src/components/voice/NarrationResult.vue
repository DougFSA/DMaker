<script setup lang="ts">
/* A narração pronta: o player, os dados, Baixar e Inserir no projeto aberto. A posição da inserção é um campo
   ("Começa em"): em branco vale o cursor do editor, se ele está com o projeto aberto, ou o fim da última narração que
   o projeto já tem. */
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import DownloadButton from '@/components/ui/DownloadButton.vue'
import MediaPlayer from '@/components/ui/MediaPlayer.vue'
import { formatDuration } from '@/lib/format'
import { speedLabel } from '@/lib/narration'
import { downloadUrl, formatSeconds } from '@/lib/speech'
import { useNarrationStore, type NarrationItem } from '@/stores/narration'
import { useToastsStore } from '@/stores/toasts'
import { useWorkspaceStore } from '@/stores/workspace'

const props = defineProps<{ item: NarrationItem }>()

const narration = useNarrationStore()
const workspace = useWorkspaceStore()
const toasts = useToastsStore()
const player = ref<InstanceType<typeof MediaPlayer> | null>(null)

const meta = computed(() => [props.item.voiceName, formatDuration(props.item.duration), `velocidade ${speedLabel(props.item.speed)}`])
const defaultText = computed(() => formatSeconds(narration.cursorStart ?? narration.defaultStart))
const startHint = computed(() =>
  narration.cursorStart === null
    ? 'Em branco, a narração entra depois da última que o projeto já tem.'
    : 'Em branco, a narração entra onde está o cursor do editor.',
)

// "Ouvir" do histórico: a narração escolhida toca; o navegador pode recusar (autoplay) e então o player fica à vista
watch(
  () => narration.playStamp,
  async () => {
    await nextTick()
    try {
      await player.value?.play()
    } catch {
      toasts.push({ tone: 'info', title: 'Narração pronta', description: 'Use o player para ouvir.' })
    }
  },
)
</script>

<template>
  <AppCard title="Resultado" subtitle="O arquivo final, com o acabamento da voz.">
    <div class="result">
      <MediaPlayer
        ref="player"
        kind="audio"
        title="Narração"
        :src="item.audioUrl"
        :meta="meta"
        :refresh-key="item.id"
      />

      <div class="result__actions">
        <DownloadButton label="Baixar áudio" :url="downloadUrl(item.audioUrl)" />
      </div>

      <div class="insert">
        <AppNumberInput
          v-model="narration.insertStart"
          label="Começa em (s)"
          :min="0"
          :step="0.1"
          :placeholder="defaultText"
          :hint="startHint"
        />
        <div class="insert__action">
          <AppButton
            variant="primary"
            :disabled="!workspace.currentProject"
            :loading="narration.inserting"
            title="Acrescenta a narração em audio.narration do projeto aberto, na posição ao lado, e salva"
            @click="narration.insertIntoProject(item)"
          >
            Inserir no projeto aberto
          </AppButton>
        </div>
      </div>

      <p v-if="!workspace.currentProject" class="insert__note">
        Nenhum projeto aberto. Abra um em <RouterLink to="/projetos">Projetos</RouterLink> para inserir a narração nele.
      </p>
      <p v-else class="insert__note" :role="narration.insertNote ? 'status' : undefined">
        {{ narration.insertNote || `Projeto aberto: ${workspace.currentProject}.` }}
      </p>
    </div>
  </AppCard>
</template>

<style scoped>
.result {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.result__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.insert {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-3) var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.insert > :first-child {
  flex: 1 1 14rem;
}

.insert__note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
  overflow-wrap: anywhere;
}
</style>
