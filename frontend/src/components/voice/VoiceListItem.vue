<script setup lang="ts">
/* Uma voz da biblioteca: nome, tipo, detalhes e as três ações (ouvir uma amostra, usar no roteiro, remover). */
import { computed } from 'vue'
import type { VoiceOption, VoiceProfile } from '@/api'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { isRemovable, voiceDetails, voiceKindLabel } from '@/lib/voice'

const props = defineProps<{
  voice: VoiceProfile
  languages: VoiceOption[]
  /** Esta é a voz escolhida para o roteiro. */
  selected: boolean
  /** O que dizer sobre a amostra: "Gerando amostra... 0:07", ou o erro. Vazio quando não há nada a dizer. */
  status: string
  /** A amostra falhou: o texto de `status` é um erro. */
  failed: boolean
  /** Uma amostra desta voz está sendo gerada. */
  previewing: boolean
}>()

defineEmits<{ preview: []; use: []; remove: [] }>()

const details = computed(() => voiceDetails(props.voice, props.languages))
</script>

<template>
  <li class="voice" :data-voice="voice.id">
    <div class="voice__main">
      <div class="voice__name">
        <strong>{{ voice.name }}</strong>
        <AppBadge>{{ voiceKindLabel(voice.kind) }}</AppBadge>
        <AppBadge v-if="selected" tone="accent" dot>Voz do roteiro</AppBadge>
      </div>
      <p v-if="details" class="voice__details">{{ details }}</p>
      <p v-if="status" :class="['voice__status', { 'is-error': failed }]" :role="failed ? 'alert' : 'status'">
        {{ status }}
      </p>
    </div>
    <div class="voice__actions">
      <AppButton
        size="sm"
        :disabled="previewing"
        :aria-label="`Ouvir uma amostra da voz ${voice.name}`"
        @click="$emit('preview')"
      >
        Ouvir
      </AppButton>
      <AppButton size="sm" :aria-label="`Usar a voz ${voice.name} no roteiro`" @click="$emit('use')">Usar</AppButton>
      <AppButton
        v-if="isRemovable(voice)"
        size="sm"
        variant="danger"
        :aria-label="`Remover a voz ${voice.name}`"
        @click="$emit('remove')"
      >
        Remover
      </AppButton>
    </div>
  </li>
</template>

<style scoped>
.voice {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3) var(--space-4);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
}

.voice__main {
  flex: 1 1 14rem;
  min-width: 0;
}

.voice__name {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.voice__details {
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  overflow-wrap: anywhere;
}

.voice__status {
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--color-accent-text);
  font-variant-numeric: tabular-nums;
}

.voice__status.is-error {
  color: var(--color-error);
}

.voice__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
</style>
