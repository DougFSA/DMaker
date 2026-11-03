<script setup lang="ts">
/* Os termos do dicionário: como a voz fala cada um, em que idioma e para quais marcas vale. Ouvir gera uma frase
   curta com o termo; Remover pede confirmação (quem usa é que sabe tirar o termo). */
import type { PronunciationEntry, VoiceOption } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import { languageLabel } from '@/lib/voice'
import { pronunciationKey, scopeLabel } from '@/lib/pronunciation'

defineProps<{
  entries: PronunciationEntry[]
  languages: VoiceOption[]
  brands: VoiceOption[]
  /** As entradas cuja frase está sendo gerada agora (a chave de `pronunciationKey`). */
  listening: Record<string, true>
}>()

defineEmits<{ listen: [entry: PronunciationEntry]; remove: [entry: PronunciationEntry] }>()
</script>

<template>
  <ul class="terms" aria-label="Termos do dicionário">
    <li
      v-for="entry in entries"
      :key="pronunciationKey(entry.term, entry.language) + entry.scope"
      class="term"
      :data-term="entry.term"
    >
      <div class="term__main">
        <p class="term__spoken">
          <strong>{{ entry.term }}</strong> <span aria-hidden="true">&rarr;</span><span class="visually-hidden"> se fala </span>
          {{ entry.spoken }}
        </p>
        <p class="term__meta">
          Idioma: {{ languageLabel(entry.language, languages) }} · Vale em: {{ scopeLabel(entry.scope, brands) }}
        </p>
      </div>
      <div class="term__actions">
        <AppButton
          size="sm"
          :disabled="!!listening[pronunciationKey(entry.term, entry.language)]"
          :aria-label="`Ouvir como se fala ${entry.term}`"
          title="Gera uma frase curta com a voz escolhida em Narração"
          @click="$emit('listen', entry)"
        >
          {{ listening[pronunciationKey(entry.term, entry.language)] ? 'Gerando...' : 'Ouvir' }}
        </AppButton>
        <AppButton size="sm" variant="danger" :aria-label="`Remover ${entry.term}`" @click="$emit('remove', entry)">
          Remover
        </AppButton>
      </div>
    </li>
  </ul>
</template>

<style scoped>
.terms {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.term {
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

.term__main {
  flex: 1 1 14rem;
  min-width: 0;
}

.term__spoken {
  overflow-wrap: anywhere;
}

.term__meta {
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.term__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
</style>
