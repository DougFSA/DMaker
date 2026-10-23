<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { OutputFile } from '@/api'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { formatRelative, formatSizeMb, formatTimestamp } from '@/lib/format'

defineProps<{
  output: OutputFile
  /** Esconde o link para o projeto quando o card já está dentro da tela dele. */
  hideProject?: boolean
}>()
defineEmits<{ play: [output: OutputFile] }>()
</script>

<template>
  <article class="output">
    <button type="button" class="output__thumb" :aria-label="`Assistir ${output.name}`" @click="$emit('play', output)">
      <img v-if="output.thumbnail" :src="output.thumbnail" alt="" loading="lazy" />
      <span v-else class="output__placeholder"><AppIcon name="video" :size="32" /></span>
      <span class="output__play"><AppIcon name="play" :size="22" /></span>
    </button>

    <div class="output__body">
      <div class="output__badges">
        <AppBadge :tone="output.kind === 'final' ? 'success' : 'info'">
          {{ output.kind === 'final' ? 'Final' : 'Prévia' }}
        </AppBadge>
        <AppBadge v-if="output.preset">{{ output.preset }}</AppBadge>
      </div>
      <h3 class="output__name" :title="output.name">{{ output.name }}</h3>
      <p class="output__meta">
        <RouterLink v-if="!hideProject" :to="{ name: 'project', params: { name: output.project } }">
          {{ output.project }}
        </RouterLink>
        <span v-if="!hideProject"> · </span>
        {{ formatSizeMb(output.size_mb) }} ·
        <time :title="formatTimestamp(output.mtime)">{{ formatRelative(output.mtime) }}</time>
      </p>
      <div class="output__actions">
        <AppButton size="sm" variant="primary" @click="$emit('play', output)">
          <AppIcon name="play" :size="14" />
          Assistir
        </AppButton>
        <AppButton v-if="output.url" size="sm" :href="output.url" :download="output.name">
          <AppIcon name="download" :size="14" />
          Baixar
        </AppButton>
      </div>
    </div>
  </article>
</template>

<style scoped>
.output {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  transition:
    border-color var(--transition),
    box-shadow var(--transition);
}

.output:hover {
  border-color: var(--color-accent-soft);
  box-shadow: var(--glow-accent);
}

.output__thumb {
  position: relative;
  display: grid;
  place-items: center;
  width: 100%;
  aspect-ratio: 16 / 10;
  padding: 0;
  overflow: hidden;
  border: 0;
  background: #000;
}

.output__thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.output__placeholder {
  color: var(--color-text-muted);
}

.output__play {
  position: absolute;
  display: grid;
  place-items: center;
  width: 3rem;
  height: 3rem;
  border-radius: 50%;
  background: var(--color-accent);
  color: var(--color-on-accent);
  opacity: 0;
  transform: scale(0.9);
  transition:
    opacity var(--transition),
    transform var(--transition);
}

.output__thumb:hover .output__play,
.output__thumb:focus-visible .output__play {
  opacity: 1;
  transform: scale(1);
}

.output__body {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: var(--space-2);
  padding: var(--space-4);
}

.output__badges {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.output__name {
  font-size: var(--text-sm);
  font-weight: 600;
  overflow-wrap: anywhere;
}

.output__meta {
  font-size: var(--text-xs);
  color: var(--color-text-soft);
}

.output__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: auto;
  padding-top: var(--space-2);
}
</style>
