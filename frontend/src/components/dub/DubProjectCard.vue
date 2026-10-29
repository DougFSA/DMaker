<script setup lang="ts">
/* As falas do projeto de dublagem aberto: o resumo, a tabela editável e os botões de salvar, traduzir de novo, gerar e
   baixar as trilhas. Gerar e baixar as trilhas salvam antes, para o arquivo e a tela nunca divergirem. */
import { computed } from 'vue'
import JobRunStatus from '@/components/speech/JobRunStatus.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import DownloadButton from '@/components/ui/DownloadButton.vue'
import { useConfirm } from '@/composables/useConfirm'
import { DRAFT_STEPS, describeProject } from '@/lib/dub'
import { useDubbingStore } from '@/stores/dubbing'
import DubSegmentsTable from './DubSegmentsTable.vue'

const dub = useDubbingStore()
const confirm = useConfirm()

const project = computed(() => dub.project)
const summary = computed(() => (project.value ? describeProject(project.value) : ''))

/** Traduzir de novo joga fora o texto atual das falas sem trava (também o que a pessoa acabou de digitar), então confirma. */
async function retranslate(): Promise<void> {
  const accepted = await confirm({
    title: 'Traduzir de novo as falas destravadas?',
    description: 'O texto atual das falas sem trava é trocado por uma tradução nova. As travadas ficam como estão.',
    confirmLabel: 'Traduzir de novo',
  })
  if (accepted) await dub.retranslate()
}
</script>

<template>
  <AppCard v-if="project" title="Falas" :subtitle="summary">
    <template #actions>
      <AppBadge v-if="dub.dirty" tone="warning" dot>Alterações não salvas</AppBadge>
    </template>
    <div class="body">
      <DubSegmentsTable v-model="dub.rows" :speakers="project.speakers" :reports="dub.reports" :disabled="dub.busy" />
      <p class="note">
        O modo de voz, a voz, a voz original por baixo e o que fazer quando a fala não cabe, lá em cima, valem para esta
        dublagem e são salvos junto com as traduções.
      </p>
      <p v-if="dub.actionError" class="problem" role="alert">{{ dub.actionError }}</p>

      <div class="actions">
        <AppButton :loading="dub.saving" :disabled="!dub.canChangeProject" @click="dub.saveTranslations()">
          Salvar traduções
        </AppButton>
        <AppButton
          title="Traduz de novo só as falas sem a trava"
          :loading="dub.retranslation.running"
          :disabled="!dub.canChangeProject"
          @click="retranslate"
        >
          Traduzir de novo as destravadas
        </AppButton>
      </div>
      <JobRunStatus
        :job="dub.retranslation"
        title="Traduzir de novo"
        cancellable
        @cancel="dub.retranslation.cancel()"
      />

      <AppCheckbox
        v-model="dub.draft"
        :label="`Rascunho (${DRAFT_STEPS} passos de síntese, metade do tempo)`"
        :disabled="dub.busy"
      />
      <div class="actions">
        <AppButton variant="primary" :loading="dub.generation.running" :disabled="!dub.canChangeProject" @click="dub.render()">
          Gerar dublagem
        </AppButton>
        <DownloadButton
          label="Baixar trilhas"
          :resolve="dub.makeStems"
          :disabled="!dub.canChangeProject"
        />
      </div>
      <p class="note">
        As trilhas são um .zip com a voz dublada, o fundo e a voz original em WAV, para remixar em outro editor.
      </p>
      <JobRunStatus :job="dub.generation" title="Gerar dublagem" cancellable @cancel="dub.generation.cancel()" />
      <JobRunStatus :job="dub.stems" title="Exportar as trilhas" cancellable @cancel="dub.stems.cancel()" />
      <p v-if="dub.stemsNote" class="note" role="status">{{ dub.stemsNote }}</p>
    </div>
  </AppCard>
</template>

<style scoped>
.body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
  overflow-wrap: anywhere;
}

.problem {
  font-size: var(--text-sm);
  color: var(--color-error);
}
</style>
