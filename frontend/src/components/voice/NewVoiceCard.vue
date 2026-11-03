<script setup lang="ts">
/* "Nova voz": clonar a partir de uma gravação ou desenhar por descrição. Os dois formulários ficam montados e só
   um aparece, para trocar de aba não perder o que já foi preenchido (nem uma gravação feita). */
import { ref } from 'vue'
import type { VoiceDesignOptions, VoiceOption } from '@/api'
import AppCard from '@/components/ui/AppCard.vue'
import SegmentedControl, { type SegmentOption } from '@/components/ui/SegmentedControl.vue'
import CloneVoiceForm from '@/components/voice/CloneVoiceForm.vue'
import DesignVoiceForm from '@/components/voice/DesignVoiceForm.vue'

defineProps<{ options: VoiceDesignOptions; brands: VoiceOption[] }>()

type Mode = 'clone' | 'design'
const MODES: SegmentOption<Mode>[] = [
  { value: 'clone', label: 'Clonar' },
  { value: 'design', label: 'Desenhar' },
]

const mode = ref<Mode>('clone')
</script>

<template>
  <AppCard title="Nova voz" subtitle="Clone uma voz que você tem permissão para usar, ou desenhe uma pela descrição.">
    <div class="new-voice">
      <SegmentedControl v-model="mode" :options="MODES" label="Como criar a voz" />
      <CloneVoiceForm v-show="mode === 'clone'" :languages="options.languages" :brands="brands" />
      <DesignVoiceForm v-show="mode === 'design'" :options="options" :brands="brands" />
    </div>
  </AppCard>
</template>

<style scoped>
.new-voice {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  align-items: stretch;
}

.new-voice > :first-child {
  align-self: flex-start;
}
</style>
