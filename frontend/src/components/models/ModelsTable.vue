<script setup lang="ts">
/* A tabela dos modelos: nome, para que serve e as ações (baixar ou continuar, apagar) na primeira célula, depois o
   estado, quanto ocupa no disco e a licença. Enquanto um modelo baixa, os botões dele esperam e a linha mostra o
   andamento do job. */
import type { ModelStatus } from '@/api'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppTable from '@/components/ui/AppTable.vue'
import JobRunStatus, { type JobRunView } from '@/components/speech/JobRunStatus.vue'
import { canDownload, canRemove, downloadLabel, sizeCell, stateLabel, stateTone, usedByText } from '@/lib/models'

defineProps<{
  models: ModelStatus[]
  /** O download de cada modelo, pelo id (só existe depois do primeiro clique em Baixar). */
  downloads: Record<string, JobRunView>
  /** Diz se o modelo está sendo baixado ou apagado agora (os botões dele esperam). */
  busy: (modelId: string) => boolean
}>()

defineEmits<{ download: [model: ModelStatus]; remove: [model: ModelStatus] }>()
</script>

<template>
  <AppTable caption="Modelos de IA: estado, tamanho no disco e licença">
    <thead>
      <tr>
        <th scope="col">Modelo</th>
        <th scope="col">Estado</th>
        <th scope="col">No disco</th>
        <th scope="col">Licença</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="model in models" :key="model.id" :data-model="model.id">
        <td class="model">
          <div class="model__name">{{ model.name }}</div>
          <div class="model__purpose">{{ model.purpose }}</div>
          <div v-if="usedByText(model)" class="model__used">{{ usedByText(model) }}</div>
          <div class="actions">
            <div class="actions__buttons">
              <AppButton
                v-if="canDownload(model)"
                size="sm"
                variant="primary"
                :disabled="busy(model.id)"
                :aria-label="`${downloadLabel(model)}: ${model.name}`"
                @click="$emit('download', model)"
              >
                {{ downloadLabel(model) }}
              </AppButton>
              <AppButton
                v-if="canRemove(model)"
                size="sm"
                variant="danger"
                :disabled="busy(model.id)"
                :aria-label="`Apagar ${model.name}`"
                @click="$emit('remove', model)"
              >
                Apagar
              </AppButton>
            </div>
            <JobRunStatus v-if="downloads[model.id]" :job="downloads[model.id]!" :title="`Baixar ${model.name}`" />
          </div>
        </td>
        <td>
          <AppBadge :tone="stateTone(model.state)" dot>{{ stateLabel(model.state) }}</AppBadge>
        </td>
        <td class="size">
          <template v-if="sizeCell(model).size">{{ sizeCell(model).size }}</template>
          <div v-if="sizeCell(model).note" class="size__note">{{ sizeCell(model).note }}</div>
        </td>
        <td class="license">{{ model.license }}</td>
      </tr>
    </tbody>
  </AppTable>
</template>

<style scoped>
.model {
  min-width: 16rem;
  max-width: 30rem;
}

.model__name {
  font-weight: 600;
}

.model__purpose,
.model__used {
  margin-top: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.model__used {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.size {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.size__note {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.license {
  min-width: 6rem;
  color: var(--color-text-soft);
}

/* as ações moram na primeira célula, sob o texto: assim a tabela cabe em telas estreitas sem esconder o botão */
.actions {
  margin-top: var(--space-3);
}

.actions__buttons {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.actions :deep(.run) {
  margin-top: var(--space-2);
}
</style>
