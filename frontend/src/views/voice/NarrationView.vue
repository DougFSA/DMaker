<script setup lang="ts">
/* Narração: escrever o roteiro, ouvir cada fala assim que fica pronta, e levar o resultado para o projeto aberto
   ou para a fila. A casca da área Voz (VoiceShellView) já traz o título e as abas. */
import { computed, onMounted, watch } from 'vue'
import NarrationForm from '@/components/voice/NarrationForm.vue'
import NarrationHistory from '@/components/voice/NarrationHistory.vue'
import NarrationResult from '@/components/voice/NarrationResult.vue'
import { brandOptions } from '@/lib/voice'
import { useCatalogStore } from '@/stores/catalog'
import { useNarrationStore } from '@/stores/narration'
import { useVoiceStore } from '@/stores/voice'
import { useWorkspaceStore } from '@/stores/workspace'

const narration = useNarrationStore()
const voices = useVoiceStore()
const catalog = useCatalogStore()
const workspace = useWorkspaceStore()

const brands = computed(() => brandOptions(catalog.brands))
const languages = computed(() => voices.options?.languages ?? [])

onMounted(() => {
  void narration.loadVoices()
  // os idiomas e as marcas só alimentam seletores: se faltarem, a narração continua funcionando
  void voices.loadOptions().catch(() => undefined)
  void catalog.load().catch(() => undefined)
  void narration.refreshDefaultStart()
})

// outro projeto aberto, outro fim da última narração
watch(() => workspace.currentProject, () => void narration.refreshDefaultStart())
</script>

<template>
  <div class="narration">
    <NarrationForm :languages="languages" :brands="brands" />

    <div class="narration__side">
      <NarrationResult v-if="narration.current" :item="narration.current" />
      <NarrationHistory
        :items="narration.history"
        :current-id="narration.current?.id ?? null"
        :can-insert="!!workspace.currentProject"
        :inserting="narration.inserting"
        @play="narration.show($event)"
        @reuse="narration.reuseText($event)"
        @insert="narration.insertIntoProject($event)"
      />
    </div>
  </div>
</template>

<style scoped>
.narration {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
}

.narration__side {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  min-width: 0;
}

/* a partir de 1100 px o roteiro e o resultado ficam lado a lado (a interface responde até 1280 px) */
@media (min-width: 1100px) {
  .narration {
    grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  }
}
</style>
