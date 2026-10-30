<script setup lang="ts">
/* Um aviso do agente dentro da conversa: a conversa foi aparada, a resposta foi parada ou o DMaker foi fechado no meio dela. */
import { noticeTitle, type NoticeItem } from '@/lib/agent'

defineProps<{ notice: NoticeItem }>()
</script>

<template>
  <p class="notice" :data-level="notice.level" :data-code="notice.code" role="status">
    <strong class="notice__title">{{ noticeTitle(notice.code) }}.</strong>
    {{ notice.text }}
  </p>
</template>

<style scoped>
.notice {
  max-width: min(46rem, 100%);
  padding: var(--space-2) var(--space-4);
  border: 1px solid var(--color-border);
  border-left-width: 3px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text-soft);
  font-size: var(--text-sm);
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.notice[data-level='info'] {
  border-left-color: var(--color-info);
}

.notice[data-level='warning'] {
  border-left-color: var(--color-warning);
}

.notice[data-level='error'] {
  border-left-color: var(--color-error);
}

.notice__title {
  color: var(--color-text);
}
</style>
