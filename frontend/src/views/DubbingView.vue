<script setup lang="ts">
/* Dublagem: traduz a fala de um vídeo ou áudio e a refaz no outro idioma. Três passos com a revisão no meio: preparar
   (transcrever e traduzir), revisar as falas numa tabela e gerar o vídeo dublado. Cada fala sintetizada fica em cache,
   então corrigir uma tradução e gerar de novo refaz só aquela fala. */
import { computed, ref } from 'vue'
import DubPrepareCard from '@/components/dub/DubPrepareCard.vue'
import DubProjectCard from '@/components/dub/DubProjectCard.vue'
import DubResultCard from '@/components/dub/DubResultCard.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import { useProjectMedia } from '@/composables/useProjectMedia'
import { findProjectEntry } from '@/lib/dub'
import { useDubbingStore } from '@/stores/dubbing'
import { useWorkspaceStore } from '@/stores/workspace'

const dub = useDubbingStore()
const workspace = useWorkspaceStore()
// depois de "Usar no projeto" a mídia do projeto mudou: o seletor da tela lê de novo
const mediaKey = ref(0)

const projectMedia = useProjectMedia(computed(() => workspace.currentProject))

/**
 * De onde sai o "Usar no projeto": do arquivo escolhido ao preparar ou, numa dublagem reaberta, da mídia do projeto
 * aberto que tenha o mesmo caminho do arquivo dublado.
 */
const target = computed(() => {
  if (dub.entry) return { project: dub.entryProject, entry: dub.entry }
  const source = dub.project?.source
  const found = source ? findProjectEntry(projectMedia.entries.value, source) : null
  return { project: found ? workspace.currentProject : null, entry: found }
})
</script>

<template>
  <PageHeader title="Dublagem" subtitle="Dublar um vídeo ou áudio para outro idioma." />
  <div class="dubbing">
    <DubPrepareCard :media-key="mediaKey" />
    <DubProjectCard />
    <DubResultCard
      v-if="dub.outcome"
      :outcome="dub.outcome"
      :project="target.project"
      :entry="target.entry"
      @used="mediaKey += 1"
    />
  </div>
</template>

<style scoped>
.dubbing {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  max-width: 64rem;
}
</style>
